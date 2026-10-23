import base64
import os
from pathlib import Path
import sys

from .paths import assets
from .web_bridge import DesktopAPI


def document():
    folder = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "web"
    template = (folder / "index.html").read_text(encoding="utf-8")
    font = "data:font/ttf;base64," + base64.b64encode(
        (assets() / "Onest.ttf").read_bytes()
    ).decode("ascii")
    style = (folder / "style.css").read_text(encoding="utf-8").replace("__FONT__", font)
    return template.replace("__STYLE__", style).replace(
        "__SCRIPT__", (folder / "app.js").read_text(encoding="utf-8")
    )


class InstanceLock:
    def __init__(self, root):
        if _legacy_running(root):
            raise ValueError("Close the older NIX window first")
        self.handle = (Path(root) / "desktop.lock").open("a+b")
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise ValueError("NIX is already running") from None

    def close(self):
        self.handle.close()


def _legacy_running(root):
    try:
        data = (Path(root) / "app.lock").read_text(encoding="utf-8").splitlines()
        pid = int(data[0])
        if not 0 < pid < 2**32:
            return False
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(buffer))
                if not kernel.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(length)
                ):
                    return False
                return Path(buffer.value).name.lower() in (
                    "nix.exe",
                    "nickatlas.exe",
                    "python.exe",
                    "pythonw.exe",
                )
            finally:
                kernel.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, IndexError):
        return False


def run_desktop(root):
    import webview

    lock = InstanceLock(root)
    api = None
    try:
        api = DesktopAPI(root)
        window = webview.create_window(
            "NIX",
            html=document(),
            js_api=api,
            width=1180,
            height=790,
            min_size=(780, 540),
            frameless=True,
            easy_drag=False,
            shadow=True,
            background_color="#242424",
            text_select=False,
            transparent=sys.platform in ("win32", "darwin"),
            vibrancy=sys.platform == "darwin",
        )
        api._window = window
        from .material import apply_material

        def material_ready():
            try:
                apply_material(window)
            except (OSError, AttributeError, RuntimeError):
                pass

        window.events.loaded += material_ready
        webview.settings["ALLOW_DOWNLOADS"] = False
        webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

        webview.start(
            gui="edgechromium" if sys.platform == "win32" else None, private_mode=True
        )
    finally:
        if api:
            api._shutdown()
        lock.close()
