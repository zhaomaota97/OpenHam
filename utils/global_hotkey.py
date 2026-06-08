"""用 Win32 RegisterHotKey 抢占全局热键。

相比 keyboard 库的低级钩子，RegisterHotKey 在操作系统层注册热键，会直接
压制系统默认行为（例如 Alt+Space 不再弹窗口系统菜单），是最权威的占用方式。
通过 Qt 的原生事件过滤器接收 WM_HOTKEY 消息，与 Qt 事件循环无缝配合。
"""
import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
_HOTKEY_ID = 0xB001

# 非字母数字键名 → 虚拟键码
_VK = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "delete": 0x2E,
}


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt_x", wintypes.LONG), ("pt_y", wintypes.LONG),
    ]


def parse_hotkey(hotkey: str):
    """'<alt>+<space>' → (modifiers, vk)；无法解析返回 None。"""
    s = hotkey.replace("<", "").replace(">", "").lower()
    mods = MOD_NOREPEAT
    vk = None
    for part in s.split("+"):
        p = part.strip()
        if not p:
            continue
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "super", "meta", "cmd"):
            mods |= MOD_WIN
        elif p in _VK:
            vk = _VK[p]
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            vk = 0x70 + (int(p[1:]) - 1)
    if vk is None:
        return None
    return mods, vk


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = _MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self._cb()
        return False, 0


_filter_ref = None  # 保活，防止被 GC


def register_global_hotkey(app, hwnd: int, hotkey: str, callback) -> bool:
    """注册全局热键。成功返回 True；失败（如组合被其他 RegisterHotKey 应用占用）返回 False。"""
    parsed = parse_hotkey(hotkey)
    if not parsed:
        return False
    mods, vk = parsed
    global _filter_ref
    _filter_ref = _HotkeyFilter(callback)
    app.installNativeEventFilter(_filter_ref)

    user32 = ctypes.windll.user32
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey(wintypes.HWND(hwnd), _HOTKEY_ID)  # 先解注册，幂等
    ok = user32.RegisterHotKey(wintypes.HWND(hwnd), _HOTKEY_ID, mods, vk)
    return bool(ok)
