import os
import shutil as _shutil
import string as _string
import platform as _platform
import socket as _socket
import re as _re
import io as _io

def get_system_info() -> str:
    """获取 CPU / 内存 / 磁盘 / 系统版本 / 本机 IP。"""
    try:
        import winreg as _winreg
        key = _winreg.OpenKey(
            _winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        cpu = _winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        _winreg.CloseKey(key)
    except Exception:
        cpu = _platform.processor() or "未知"

    try:
        import ctypes as _ctypes
        import ctypes.wintypes
        class _MEMSTAT(_ctypes.Structure):
            _fields_ = [
                ("dwLength",                _ctypes.c_ulong),
                ("dwMemoryLoad",            _ctypes.c_ulong),
                ("ullTotalPhys",            _ctypes.c_ulonglong),
                ("ullAvailPhys",            _ctypes.c_ulonglong),
                ("ullTotalPageFile",        _ctypes.c_ulonglong),
                ("ullAvailPageFile",        _ctypes.c_ulonglong),
                ("ullTotalVirtual",         _ctypes.c_ulonglong),
                ("ullAvailVirtual",         _ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", _ctypes.c_ulonglong),
            ]
        ms = _MEMSTAT()
        ms.dwLength = _ctypes.sizeof(ms)
        _ctypes.windll.kernel32.GlobalMemoryStatusEx(_ctypes.byref(ms))
        ram_str = f"{ms.ullTotalPhys / 1024**3:.0f} GB"
    except Exception:
        ram_str = "未知"

    disk_lines = []
    for letter in _string.ascii_uppercase:
        p = f"{letter}:\\"
        if os.path.exists(p):
            try:
                d = _shutil.disk_usage(p)
                disk_lines.append(
                    f"磁盘{letter}    剩余 {d.free/1024**3:.0f} GB / 共 {d.total/1024**3:.0f} GB"
                )
            except Exception:
                pass
    disk_str = "\n".join(disk_lines) if disk_lines else "未知"

    try:
        v = _platform.win32_ver()
        os_str = f"Windows {v[0]}  Build {v[1]}"
    except Exception:
        os_str = _platform.system()

    try:
        ip = _socket.gethostbyname(_socket.gethostname())
    except Exception:
        ip = "未知"

    return "\n".join([
        f"CPU   {cpu}",
        f"内存  {ram_str}",
        disk_str,
        f"系统  {os_str}",
        f"IP    {ip}",
    ])

def generate_qr_bytes(text: str) -> bytes | None:
    """将 text 生成二维码，返回 PNG bytes；未安装 qrcode 时返回 None。"""
    try:
        import qrcode as _qr
        img = _qr.make(text)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return None
