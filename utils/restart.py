"""自动重启 OpenHam（用于更新/安装组件后）。

直接启动新进程（不经 cmd，避免引号/路径问题），随后退出当前实例。
新实例的单实例锁会重试等待几秒，等旧实例退出后再接管。
"""
import os
import sys
import subprocess

from utils.paths import _base_dir

DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


def restart_app():
    base = _base_dir()
    exe = os.path.join(base, "OpenHam.exe")
    try:
        if os.path.exists(exe):
            args = [exe]
        else:
            py = os.path.join(base, "runtime", "pythonw.exe")
            if not os.path.exists(py):
                py = sys.executable
            args = [py, os.path.join(base, "main.py")]
        subprocess.Popen(args, cwd=base, close_fds=True,
                         creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW)
    except Exception:
        pass
    try:
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
    except Exception:
        os._exit(0)
