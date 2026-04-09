import ctypes
import ctypes.wintypes


def disable_native_window_effects(hwnd: int) -> None:
    """Best-effort disable of Windows shadow, rounded corners, and border."""
    if not hwnd:
        return

    try:
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        dwmapi = None

    if dwmapi is not None:
        try:
            hwnd_value = ctypes.wintypes.HWND(hwnd)
            nc_rendering_disabled = ctypes.c_int(2)
            no_rounded_corners = ctypes.c_int(1)
            no_border_color = ctypes.c_uint(0xFFFFFFFE)

            dwmapi.DwmSetWindowAttribute(hwnd_value, 2, ctypes.byref(nc_rendering_disabled), ctypes.sizeof(nc_rendering_disabled))
            dwmapi.DwmSetWindowAttribute(hwnd_value, 33, ctypes.byref(no_rounded_corners), ctypes.sizeof(no_rounded_corners))
            dwmapi.DwmSetWindowAttribute(hwnd_value, 34, ctypes.byref(no_border_color), ctypes.sizeof(no_border_color))
        except Exception:
            pass

    try:
        user32 = ctypes.windll.user32
        get_class_long_ptr = getattr(user32, "GetClassLongPtrW", None)
        set_class_long_ptr = getattr(user32, "SetClassLongPtrW", None)
        if get_class_long_ptr and set_class_long_ptr:
            get_class_long_ptr.restype = ctypes.c_size_t
            hwnd_value = ctypes.wintypes.HWND(hwnd)
            style = get_class_long_ptr(hwnd_value, -26)
            if style & 0x00020000:
                set_class_long_ptr(hwnd_value, -26, ctypes.c_size_t(style & ~0x00020000))
                user32.SetWindowPos(hwnd_value, None, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)
    except Exception:
        pass
