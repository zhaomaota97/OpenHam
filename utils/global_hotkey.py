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


# ── 霸道版：低级键盘钩子 + 定时重装，抢在其它应用之前 ─────────────────────
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_MENU = 0x12
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class _KBDLL(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _LLHotkey:
    def __init__(self, mods, vk, callback):
        self.vk = vk
        self.need_alt = bool(mods & MOD_ALT)
        self.need_ctrl = bool(mods & MOD_CONTROL)
        self.need_shift = bool(mods & MOD_SHIFT)
        self.need_win = bool(mods & MOD_WIN)
        self.cb = callback
        self._u = ctypes.windll.user32
        self._k = ctypes.windll.kernel32
        # 64 位下必须设对 argtypes/restype，否则句柄被截断 → 安装失败
        self._k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._k.GetModuleHandleW.restype = wintypes.HMODULE
        self._u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HMODULE, wintypes.DWORD]
        self._u.SetWindowsHookExW.restype = wintypes.HHOOK
        self._u.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self._u.UnhookWindowsHookEx.restype = wintypes.BOOL
        self._u.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self._u.CallNextHookEx.restype = LRESULT
        self._u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._u.GetAsyncKeyState.restype = ctypes.c_short
        self._proc = HOOKPROC(self._hook)   # 保活
        self._hid = None

    def _down(self, vk):
        return bool(self._u.GetAsyncKeyState(vk) & 0x8000)

    def _match(self):
        return (self._down(VK_MENU) == self.need_alt
                and self._down(VK_CONTROL) == self.need_ctrl
                and self._down(VK_SHIFT) == self.need_shift
                and (self._down(VK_LWIN) or self._down(VK_RWIN)) == self.need_win)

    def _hook(self, nCode, wParam, lParam):
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = _KBDLL.from_address(lParam)
            if kb.vkCode == self.vk and self._match():
                try:
                    self.cb()        # 应尽量轻量（建议用队列连接派发实际动作）
                except Exception:
                    pass
                return 1             # 吞掉：别人收不到，也不弹系统菜单
        return self._u.CallNextHookEx(None, nCode, wParam, lParam)

    def install(self):
        hmod = self._k.GetModuleHandleW(None)
        self._hid = self._u.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, hmod, 0)
        return bool(self._hid)

    def reinstall(self):
        if self._hid:
            self._u.UnhookWindowsHookEx(self._hid)
            self._hid = None
        return self.install()


_ll_ref = None
_ll_timer = None


def claim_hotkey_aggressive(hotkey: str, callback, reinstall_ms: int = 2500) -> bool:
    """低级钩子抢占热键，并每隔 reinstall_ms 重装一次以保持在钩子链最前。
    成功返回 True。能压过 RegisterHotKey 占用者及其它低级钩子（谁更新谁靠前）。"""
    parsed = parse_hotkey(hotkey)
    if not parsed:
        return False
    mods, vk = parsed
    global _ll_ref, _ll_timer
    _ll_ref = _LLHotkey(mods, vk, callback)
    if not _ll_ref.install():
        _ll_ref = None
        return False
    from PyQt6.QtCore import QTimer
    _ll_timer = QTimer()
    _ll_timer.timeout.connect(_ll_ref.reinstall)
    _ll_timer.start(reinstall_ms)
    return True


# 额外的低级钩子热键（如划词翻译），各自独立安装，互不影响主热键。
_ll_extra = []


def add_hotkey_aggressive(hotkey: str, callback, reinstall_ms: int = 2500) -> bool:
    """再注册一个低级钩子热键（可多次调用，每个热键独立一条钩子+重装定时器）。
    callback 在钩子线程里被调用，应尽量轻量（建议内部用 Qt 信号派发到 UI 线程）。"""
    parsed = parse_hotkey(hotkey)
    if not parsed:
        return False
    mods, vk = parsed
    h = _LLHotkey(mods, vk, callback)
    if not h.install():
        return False
    from PyQt6.QtCore import QTimer
    t = QTimer()
    t.timeout.connect(h.reinstall)
    t.start(reinstall_ms)
    _ll_extra.append((h, t))   # 保活引用
    return True
