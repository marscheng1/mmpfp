import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from urllib.request import urlopen

from fastapi import FastAPI
import pytest

import desktop


def test_server_waits_for_lifespan_and_stops_cleanly():
    events = []

    @asynccontextmanager
    async def lifespan(app):
        events.append("starting")
        await asyncio.sleep(0.05)
        events.append("ready")
        yield
        events.append("saved")

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    def index():
        return {"ready": True}

    server = desktop.LocalServer(app, port=0)
    try:
        server.start()
        assert events == ["starting", "ready"]
        with urlopen(f"http://127.0.0.1:{server.port}/", timeout=2) as response:
            assert response.status == 200
    finally:
        server.stop()
    assert events[-1] == "saved"
    assert not server.thread.is_alive()
    with socket.socket() as check:
        assert check.connect_ex(("127.0.0.1", server.port)) != 0


def test_server_port_conflict_does_not_touch_existing_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = desktop.LocalServer(FastAPI(), port=listener.getsockname()[1])
        with pytest.raises(RuntimeError, match="占用端口"):
            server.start()
        assert server.thread is None
        assert listener.fileno() != -1


def test_startup_failure_is_reported_and_thread_cleaned_up():
    @asynccontextmanager
    async def lifespan(app):
        raise RuntimeError("invalid configuration")
        yield

    server = desktop.LocalServer(FastAPI(lifespan=lifespan), port=0)
    with pytest.raises(RuntimeError, match="启动失败"):
        server.start()
    assert not server.thread.is_alive()
    assert server.socket is None


def test_startup_timeout_cancels_startup():
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.sleep(60)
        yield

    server = desktop.LocalServer(FastAPI(lifespan=lifespan), port=0)
    with pytest.raises(RuntimeError, match="启动超时"):
        server.start(timeout=0.1)
    assert not server.thread.is_alive()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel objects")
def test_single_instance_signals_primary_and_releases_handles(tmp_path: Path):
    first = desktop.SingleInstance(tmp_path)
    second = desktop.SingleInstance(tmp_path)
    try:
        assert first.primary
        assert not second.primary
        second.notify_show()
        assert first.wait_for_show(500)
        assert not first.wait_for_show(10)  # auto-reset event
    finally:
        second.close()
        first.close()
    third = desktop.SingleInstance(tmp_path)
    try:
        assert third.primary
    finally:
        third.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop entry")
def test_repeated_launch_stays_in_tray(monkeypatch):
    calls = []
    instance = SimpleNamespace(primary=False, notify_show=lambda: calls.append("show"),
                               close=lambda: calls.append("close"))
    monkeypatch.setattr(desktop, "SingleInstance", lambda: instance)
    assert desktop.main() == 0
    assert calls == ["close"]


class FakeWindow:
    def __init__(self, result=None):
        self.result = result if result is not None else {"ok": True}
        self.actions = []

    def show(self):
        self.actions.append("show")

    def restore(self):
        self.actions.append("restore")

    def hide(self):
        self.actions.append("hide")

    def destroy(self):
        self.actions.append("destroy")

    def evaluate_js(self, script, callback=None):
        self.actions.append("prepare" if callback else "cancel")
        if callback:
            callback(self.result)


def shell(result=None):
    server = SimpleNamespace(stop=lambda: window.actions.append("stop"))
    window = FakeWindow(result)
    app = desktop.DesktopApplication(None, None, None, None, server)
    app.window = window
    return app, window


def test_window_close_hides_without_stopping_service():
    app, window = shell()
    assert app.on_closing() is False
    assert window.actions == ["hide"]
    app.show()
    assert window.actions[-2:] == ["show", "restore"]


def test_exit_saves_before_stopping_and_destroying_window():
    app, window = shell()
    app.exit_lock.acquire()
    app._exit()
    assert window.actions == ["prepare", "stop", "destroy"]
    assert app.allow_close
    assert app.on_closing() is True


def test_failed_save_cancels_exit_without_stopping_server(monkeypatch):
    app, window = shell({"ok": False, "error": "disk full"})
    errors = []
    monkeypatch.setattr(desktop, "show_error", errors.append)
    app.exit_lock.acquire()
    app._exit()
    assert "stop" not in window.actions
    assert "destroy" not in window.actions
    assert window.actions == ["prepare", "cancel", "show", "restore"]
    assert "disk full" in errors[0]
    assert not app.allow_close
    assert not app.exit_lock.locked()


def test_save_timeout_cancels_exit():
    app, window = shell()
    window.evaluate_js = lambda *args, **kwargs: None
    with pytest.raises(RuntimeError, match="超时"):
        app.prepare_exit(timeout=0.01)


@pytest.mark.parametrize("result", [None, {}, {"ok": False}])
def test_unconfirmed_save_never_allows_shutdown(result):
    app, window = shell()
    window.result = result
    with pytest.raises(RuntimeError):
        app.prepare_exit()
