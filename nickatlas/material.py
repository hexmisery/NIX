import sys


def apply_material(window):
    if sys.platform == "darwin":
        window.evaluate_js("document.documentElement.classList.add('native-glass')")
        return True
    if sys.platform != "win32" or sys.getwindowsversion().build < 19041:
        return False
    import ctypes
    from ctypes import wintypes
    from System import Action
    from System.Drawing import Color

    class Margins(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]

    class AccentPolicy(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_int) for name in ("state", "flags", "color", "animation")
        ]

    class CompositionData(ctypes.Structure):
        _fields_ = [
            ("attribute", ctypes.c_int),
            ("data", ctypes.c_void_p),
            ("size", ctypes.c_size_t),
        ]

    applied = []

    def configure():
        native = window.native
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        dwm.DwmExtendFrameIntoClientArea.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(Margins),
        ]
        dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        handle = native.Handle.ToInt64()
        material, dark, rounded = ctypes.c_int(1), ctypes.c_int(1), ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(handle, 38, ctypes.byref(material), 4)
        if (
            dwm.DwmExtendFrameIntoClientArea(
                handle, ctypes.byref(Margins(-1, -1, -1, -1))
            )
            != 0
        ):
            return

        user = ctypes.WinDLL("user32")
        composition = user.SetWindowCompositionAttribute
        composition.argtypes = [wintypes.HWND, ctypes.POINTER(CompositionData)]
        composition.restype = wintypes.BOOL
        accent = AccentPolicy(3, 0, 0, 0)
        data = CompositionData(
            19,
            ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
            ctypes.sizeof(accent),
        )
        if not composition(handle, ctypes.byref(data)):
            material.value = 3
            if dwm.DwmSetWindowAttribute(handle, 38, ctypes.byref(material), 4) != 0:
                return
        dwm.DwmSetWindowAttribute(handle, 20, ctypes.byref(dark), 4)
        dwm.DwmSetWindowAttribute(handle, 33, ctypes.byref(rounded), 4)
        native.BackColor = Color.Black
        native.webview.DefaultBackgroundColor = Color.Transparent
        applied.append(True)

    window.native.Invoke(Action(configure))
    if applied:
        window.evaluate_js("document.documentElement.classList.add('native-glass')")
    return bool(applied)
