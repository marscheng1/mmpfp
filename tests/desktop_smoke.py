"""Opt-in Windows GUI smoke test: pytest tests/desktop_smoke.py -s.

Not collected by the normal test_*.py suite. Uses temporary data and a random port;
it never launches or shuts down the developer's production service.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

import desktop
import main


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for GUI state")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI only")
def test_real_webview_tray_and_exit_save(tmp_path: Path, monkeypatch):
    import webview
    import pystray
    from PIL import Image

    root = tmp_path / "solutions"
    root.mkdir()
    records = tmp_path / "records.json"
    records.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(desktop, "PROJECT_ROOT", tmp_path)
    for name, value in {
        "SOLUTIONS_DIR": str(root), "DATA_FILE": str(records),
        "META_FILE": str(tmp_path / "meta.json"),
        "LEDGER_FACTS_FILE": str(tmp_path / "facts.json"),
        "LEDGER_LINKS_FILE": str(tmp_path / "links.json"),
        "records_cache": [], "pass_count": 0,
    }.items():
        monkeypatch.setattr(main, name, value)
    for name in ("day_count_cache", "day_sum_cache", "month_count_cache", "month_sum_cache"):
        monkeypatch.setattr(main, name, getattr(main, name).copy())
    errors = []
    monkeypatch.setattr(desktop, "show_error", errors.append)
    loaded = threading.Event()
    create_window = webview.create_window

    def create(*args, **kwargs):
        assert kwargs.get("hidden") is True
        window = create_window(*args, **kwargs)
        window.events.loaded += loaded.set
        return window

    instance = desktop.SingleInstance(tmp_path)
    app = desktop.DesktopApplication(
        SimpleNamespace(create_window=create, start=webview.start), pystray,
        Image.new("RGB", (64, 64), "#2563eb"), instance,
        desktop.LocalServer(main.app, port=0),
    )
    failures = []
    checker = None

    def verify():
        try:
            assert loaded.wait(40), "Homepage did not load"
            assert not app.window.native.Visible, "Startup must remain in the tray"
            assert app.window.evaluate_js("document.title") == "MMPFP"
            assert app.window.evaluate_js("!!document.querySelector('.heatmap-wrapper')")
            app.window.evaluate_js("localStorage.setItem('desktop-smoke', 'persistent')")
            assert app.window.evaluate_js("localStorage.getItem('desktop-smoke')") == "persistent"

            # The tray's explicit open action reveals the initially hidden window.
            app.show()
            wait_until(lambda: app.window.native.Visible)

            # Closing the native window must be intercepted and leave the server alive.
            app.window.destroy()
            wait_until(lambda: not app.window.native.Visible)
            base = f"http://127.0.0.1:{app.server.port}"
            payload = [{"time": 1700000000, "status": True, "pid": "smoke", "rid": "smoke"}]
            request = Request(base + "/api/push_record", json.dumps(payload).encode(),
                              {"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=3) as response:
                assert response.status == 200

            second = desktop.SingleInstance(tmp_path)
            try:
                assert not second.primary
                second.notify_show()
                wait_until(lambda: app.window.native.Visible)
            finally:
                second.close()

            # Exercise the exact production editor hook against real HTTP APIs.
            html = (Path(main.PAGE_DIR) / "solution-journal.html").read_text(encoding="utf-8")
            hook = html.split("            window.mmpfpCancelExit =", 1)[1]
            hook = "window.mmpfpCancelExit =" + hook.split("            // ---------- API 辅助 ----------", 1)[0]
            setup = """
                var desktopExitState = null, desktopExitGeneration = 0;
                var cmEditor = {getOption: () => false, setOption: () => {}, getValue: () => 'unsaved desktop draft'};
                var timerInterval = null, isCompleted = false, saveTimer = null, timerTick = 17;
                var dirty = true, currentFilePath = 'smoke/report.md', committedContent = '';
                var commitInProgress = false, metaData = {}, saveStatus = {};
                var fileWriteQueue = Promise.resolve();
                function stopTimer() {} function startTimer() {}
                function normalizeMetaPath(p) { return p.replace(/\\.md$/i, ''); }
                async function apiPost(url, data) {
                    const response = await fetch(url, {method: 'POST', headers: {'Content-Type':'application/json'}, body:JSON.stringify(data)});
                    if (!response.ok) throw Error('HTTP ' + response.status);
                    return response.json();
                }
                function enqueueFileWrite(fn) { const task = fileWriteQueue.then(fn, fn); fileWriteQueue = task.catch(() => {}); return task; }
            """
            app.window.evaluate_js(setup + hook)
            app.request_exit()
        except BaseException as exc:
            failures.append(exc)
            app.allow_close = True
            app.window.destroy()

    start_watcher = app._start_watcher

    def start_check():
        nonlocal checker
        start_watcher()
        checker = threading.Thread(target=verify, name="desktop-smoke-check")
        checker.start()

    app._start_watcher = start_check
    try:
        app.run()
    finally:
        instance.close()
        if checker is not None:
            checker.join(timeout=5)
    assert not failures, repr(failures)
    assert not errors, repr(errors)
    assert not app.server.thread.is_alive()
    assert (root / "smoke/report.md").read_text(encoding="utf-8") == "unsaved desktop draft"
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["smoke/report"]["elapsed"] == 17
    assert json.loads(records.read_text(encoding="utf-8"))[0]["rid"] == "smoke"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows script host only")
def test_hidden_launcher_with_actual_uv_trampoline(tmp_path: Path):
    import ctypes
    from ctypes import wintypes

    # Copy the actual uv console trampoline into a temporary project, not the app data.
    project = Path(desktop.__file__).resolve().parent
    scripts = tmp_path / ".venv/Scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(project / ".venv/Scripts/pythonw.exe", scripts / "pythonw.exe")
    shutil.copy2(project / ".venv/pyvenv.cfg", scripts.parent / "pyvenv.cfg")
    shutil.copy2(project / "launch-desktop.vbs", tmp_path / "launch-desktop.vbs")
    (tmp_path / "desktop.py").write_text('''
import ctypes, json, time
from pathlib import Path
ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
window = ctypes.windll.kernel32.GetConsoleWindow()
ctypes.windll.user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
Path(__file__).with_name('probe.json').write_text(json.dumps({
    'visible_console': bool(window and ctypes.windll.user32.IsWindowVisible(window))
}))
time.sleep(2)
Path(__file__).with_name('probe.done').touch()
''', encoding="utf-8")
    user32 = ctypes.WinDLL("user32")
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    def visible_consoles():
        handles = set()

        @callback_type
        def check(handle, _):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(handle, name, len(name))
            if name.value in {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"} and user32.IsWindowVisible(handle):
                handles.add(handle)
            return True

        user32.EnumWindows(check, 0)
        return handles

    before = visible_consoles()
    host = Path(__import__("os").environ["SystemRoot"]) / "System32/wscript.exe"
    subprocess.run([str(host), "//Nologo", str(tmp_path / "launch-desktop.vbs")],
                   check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    wait_until(lambda: (tmp_path / "probe.json").exists())
    probe = json.loads((tmp_path / "probe.json").read_text())
    assert probe["visible_console"] is False
    assert not (visible_consoles() - before), "Launcher created a visible command window"
    wait_until(lambda: (tmp_path / "probe.done").exists())
