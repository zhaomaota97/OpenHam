"""开机自启动（写当前用户的 Run 注册表项，无需管理员权限）。"""
import os
import sys

from utils.paths import _base_dir

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NAME = "OpenHam"


def _command() -> str:
    """开机启动要执行的命令。优先用 OpenHam.exe，源码运行则用便携 pythonw。"""
    base = _base_dir()
    exe = os.path.join(base, "OpenHam.exe")
    if os.path.exists(exe):
        return f'"{exe}"'
    py = os.path.join(base, "runtime", "pythonw.exe")
    if not os.path.exists(py):
        py = sys.executable
    return f'"{py}" "{os.path.join(base, "main.py")}"'


def is_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, _NAME)
        return True
    except (FileNotFoundError, OSError):
        return False
    except Exception:
        return False


def set_enabled(on: bool):
    import winreg
    if on:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, _NAME, 0, winreg.REG_SZ, _command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, _NAME)
        except FileNotFoundError:
            pass
