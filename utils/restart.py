"""自动重启 OpenHam（用于更新/安装组件后）。

先排程一个延迟 2 秒再启动的进程（等当前实例退出、释放单实例锁），随后退出当前实例。
"""
import os
import sys
import subprocess

from utils.paths import _base_dir


def restart_app():
    base = _base_dir()
    exe = os.path.join(base, "OpenHam.exe")
    if os.path.exists(exe):
        inner = f'timeout /t 2 /nobreak >nul & start "" "{exe}"'
    else:
        py = os.path.join(base, "runtime", "pythonw.exe")
        if not os.path.exists(py):
            py = sys.executable
        inner = f'timeout /t 2 /nobreak >nul & start "" "{py}" "{os.path.join(base, "main.py")}"'
    try:
        subprocess.Popen(["cmd", "/c", inner], creationflags=0x08000000)  # CREATE_NO_WINDOW
    except Exception:
        pass
    try:
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
    except Exception:
        os._exit(0)
