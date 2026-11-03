"""Windows desktop shell. The existing HTTP entry point remains usable on its own."""
from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import io
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8000
HOME_URL = f"http://{HOST}:{PORT}/"
logger = logging.getLogger("mmpfp.desktop")


def show_error(message: str) -> None:
    """Also works before dependencies or the WebView have been initialized."""
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, str(message), "MMPFP", 0x10)
    elif sys.stderr is not None:
        sys.stderr.write(f"MMPFP: {message}\n")


class LogStream(io.TextIOBase):
    def __init__(self, level: int):
        self.level = level

    @property
    def encoding(self) -> str:
        return "utf-8"

    def write(self, text: str) -> int:
        if text.strip():
            logging.getLogger("mmpfp.console").log(self.level, text.rstrip())
        return len(text)

    def flush(self) -> None:
        pass


def configure_logging() -> None:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "desktop.log", maxBytes=5 * 1024 * 1024,
        backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # pythonw has no standard streams; both print() and Uvicorn errors go to the log.
    sys.stdout = LogStream(logging.INFO)
    sys.stderr = LogStream(logging.ERROR)


class SingleInstance:
    """A project-scoped Windows mutex and an auto-reset 'show window' event."""

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        declarations = {
            "CreateMutexW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            "CreateEventW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetEvent": ([wintypes.HANDLE], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        digest = hashlib.sha256(str(project_root.resolve()).casefold().encode()).hexdigest()[:20]
        name = f"Local\\MMPFP-{digest}"
        self.mutex = self.kernel.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not self.mutex:
            raise ctypes.WinError(error)
        self.primary = error != 183  # ERROR_ALREADY_EXISTS
        self.event = self.kernel.CreateEventW(None, False, False, name + "-show")
        if not self.event:
            error = ctypes.get_last_error()
            self.kernel.CloseHandle(self.mutex)
            self.mutex = None
            raise ctypes.WinError(error)

    def notify_show(self) -> None:
        if not self.kernel.SetEvent(self.event):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait_for_show(self, timeout_ms: int = 250) -> bool:
        result = self.kernel.WaitForSingleObject(self.event, timeout_ms)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self) -> None:
        for name in ("event", "mutex"):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


class LocalServer:
    def __init__(self, app: Any = "main:app", host: str = HOST, port: int = PORT):
        self.app, self.host, self.port = app, host, port
        self.server: Any = None
        self.thread: threading.Thread | None = None
        self.socket: socket.socket | None = None
        self.error: BaseException | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task | None = None

    def start(self, timeout: float = 15) -> None:
        import uvicorn

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((self.host, self.port))
            sock.setblocking(False)
        except OSError as exc:
            sock.close()
            raise RuntimeError(
                f"无法监听 {self.host}:{self.port}。请先关闭占用端口的服务（包括原控制台服务）。"
            ) from exc
        self.socket = sock
        self.port = sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(
            self.app, host=self.host, port=self.port, workers=1,
            reload=False, lifespan="on", log_config=None,
            timeout_graceful_shutdown=10,
        ))

        def serve() -> None:
            async def run_server() -> None:
                self.loop = asyncio.get_running_loop()
                self.task = asyncio.current_task()
                if not self.server.should_exit:
                    await self.server.serve(sockets=[sock])

            try:
                asyncio.run(run_server())
            except asyncio.CancelledError:
                logger.info("Server startup cancelled")
            except BaseException as exc:
                self.error = exc
                logger.exception("Local server failed")

        self.thread = threading.Thread(target=serve, name="mmpfp-server")
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive():
                self.stop()
                raise RuntimeError("本地服务启动失败，请检查配置及 logs/desktop.log。") from self.error
            if time.monotonic() >= deadline:
                self.stop()
                raise RuntimeError("本地服务启动超时，请检查 logs/desktop.log。")
            time.sleep(0.05)

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            if not self.server.started and self.loop is not None and self.task is not None:
                try:
                    self.loop.call_soon_threadsafe(self.task.cancel)
                except RuntimeError:
                    pass  # The server may already have closed its event loop.
        if self.thread is not None and self.thread is not threading.current_thread():
            # Do not abandon lifespan cleanup or terminate a write in progress.
            self.thread.join()
        if self.socket is not None:
            self.socket.close()
            self.socket = None


PREPARE_EXIT_JS = """(async () => {
    if (typeof window.mmpfpPrepareExit === 'function') return await window.mmpfpPrepareExit();
    if (location.pathname.replace(/\\/+$/, '') === '/solution-journal')
        return {ok: false, error: '编辑器尚未就绪，请稍后再退出。'};
    return {ok: true};
})()"""


class DesktopApplication:
    def __init__(self, webview: Any, pystray: Any, image: Any, instance: SingleInstance,
                 server: LocalServer | None = None):
        self.webview, self.pystray, self.image = webview, pystray, image
        self.instance = instance
        self.server = server or LocalServer()
        self.window: Any = None
        self.tray: Any = None
        self.tray_thread: threading.Thread | None = None
        self.watch_thread: threading.Thread | None = None
        self.watch_stop = threading.Event()
        self.tray_ready = threading.Event()
        self.tray_error: BaseException | None = None
        self.exit_lock = threading.Lock()
        self.allow_close = False

    def show(self, *_: Any) -> None:
        if self.window is not None and not self.allow_close:
            self.window.show()
            self.window.restore()

    def on_closing(self) -> bool:
        if self.allow_close:
            return True
        self.window.hide()
        return False

    def prepare_exit(self, timeout: float = 15) -> None:
        completed = threading.Event()
        results: list[Any] = []

        def receive(result: Any) -> None:
            results.append(result)
            completed.set()

        self.window.evaluate_js(PREPARE_EXIT_JS, callback=receive)
        if not completed.wait(timeout):
            raise RuntimeError("等待编辑器保存超时，已取消退出。")
        result = results[0]
        if not isinstance(result, dict) or result.get("ok") is not True:
            message = result.get("error", "编辑器保存失败。") if isinstance(result, dict) else "编辑器保存失败。"
            raise RuntimeError(message)

    def request_exit(self, *_: Any) -> None:
        if self.exit_lock.acquire(blocking=False):
            threading.Thread(target=self._exit, name="mmpfp-exit").start()

    def _exit(self) -> None:
        try:
            self.prepare_exit()
            self.server.stop()
            self.allow_close = True
            self.window.destroy()
        except Exception as exc:
            logger.exception("Exit cancelled")
            try:
                self.window.evaluate_js("window.mmpfpCancelExit?.()")
                self.show()
            except Exception:
                logger.exception("Could not restore window")
            show_error(f"退出失败，应用继续运行。\n{exc}")
        finally:
            self.exit_lock.release()

    def _watch_instance(self) -> None:
        while not self.watch_stop.is_set():
            if self.instance.wait_for_show():
                self.show()

    def _start_watcher(self) -> None:
        self.watch_thread = threading.Thread(target=self._watch_instance, name="mmpfp-instance", daemon=True)
        self.watch_thread.start()

    def run(self) -> None:
        try:
            self.server.start()
            self.window = self.webview.create_window(
                "MMPFP", f"http://{self.server.host}:{self.server.port}/",
                width=1200, height=850, min_size=(900, 600),
                text_select=True, hidden=True,
            )
            self.window.events.closing += self.on_closing
            self.tray = self.pystray.Icon("mmpfp", self.image, "MMPFP", menu=self.pystray.Menu(
                self.pystray.MenuItem("打开窗口", self.show, default=True),
                self.pystray.MenuItem("退出", self.request_exit),
            ))

            def tray_setup(icon: Any) -> None:
                icon.visible = True
                self.tray_ready.set()

            def run_tray() -> None:
                try:
                    self.tray.run(setup=tray_setup)
                except BaseException as exc:
                    self.tray_error = exc
                    self.tray_ready.set()
                    logger.exception("Tray failed")

            self.tray_thread = threading.Thread(target=run_tray, name="mmpfp-tray")
            self.tray_thread.start()
            if not self.tray_ready.wait(5) or self.tray_error is not None:
                raise RuntimeError("无法创建系统托盘，请检查 logs/desktop.log。") from self.tray_error
            storage = PROJECT_ROOT / ".desktop-storage"
            storage.mkdir(exist_ok=True)
            self.webview.start(
                self._start_watcher, gui="edgechromium", debug=False,
                private_mode=False, storage_path=str(storage),
            )
        finally:
            self.watch_stop.set()
            if self.watch_thread is not None:
                self.watch_thread.join(timeout=2)
            if self.tray is not None:
                self.tray.stop()
            if self.tray_thread is not None:
                self.tray_thread.join(timeout=5)
            self.server.stop()


def main() -> int:
    if sys.platform != "win32":
        show_error("桌面入口目前仅支持 Windows。其他平台请使用原服务端入口。")
        return 1
    instance: SingleInstance | None = None
    try:
        instance = SingleInstance()
        if not instance.primary:
            return 0
        configure_logging()
        logger.info("Starting desktop application")
        try:
            import webview
            import pystray
            from PIL import Image, ImageDraw
        except ImportError as exc:
            raise RuntimeError("桌面依赖缺失。请在项目目录运行：uv sync --extra desktop") from exc
        image = Image.new("RGB", (64, 64), "#2563eb")
        draw = ImageDraw.Draw(image)
        draw.line([(12, 48), (12, 16), (32, 36), (52, 16), (52, 48)], fill="white", width=7)
        DesktopApplication(webview, pystray, image, instance).run()
        logger.info("Desktop application stopped")
        return 0
    except Exception as exc:
        logger.exception("Desktop startup failed")
        show_error(f"{exc}\n\n详细信息：{PROJECT_ROOT / 'logs' / 'desktop.log'}")
        return 1
    finally:
        if instance is not None:
            instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
