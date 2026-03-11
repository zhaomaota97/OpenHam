import sys
import os
import json
import ctypes
import threading
import subprocess
import time as _time
import re
from dotenv import load_dotenv
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QAction
import keyboard as kb

from window import InputWindow, PomodoroOverlay
from executor import execute, call_deepseek_stream, search_files, parse_pomodoro


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_single_instance():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "OpenHam_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:
        sys.exit(0)
    return mutex


# 子线程 -> 主线程通信信号
class HotkeySignal(QObject):
    triggered = pyqtSignal()

class AISignal(QObject):
    responded   = pyqtSignal(str)
    chunk       = pyqtSignal(str)
    stream_done = pyqtSignal()

class FileSignal(QObject):
    results = pyqtSignal(list)


def _show_toast(title: str, message: str):
    """PowerShell balloon tip — Windows 10/11 最可靠的气泡通知方式。"""
    safe_t = title.replace('"', "'")
    safe_m = message.replace('"', "'")
    script = (
        'Add-Type -AssemblyName System.Windows.Forms; '
        '$n = New-Object System.Windows.Forms.NotifyIcon; '
        '$n.Icon = [System.Drawing.SystemIcons]::Information; '
        '$n.Visible = $true; '
        f'$n.ShowBalloonTip(8000,"{safe_t}","{safe_m}",'
        '[System.Windows.Forms.ToolTipIcon]::Info); '
        'Start-Sleep 9; $n.Dispose()'
    )
    subprocess.Popen(
        ['powershell', '-WindowStyle', 'Hidden', '-NoProfile', '-Command', script],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def load_config():
    path = os.path.join(_base_dir(), "config.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_api_key():
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("[警告] 未设置 DEEPSEEK_API_KEY 环境变量，AI 功能将不可用")
    return api_key


def _make_tray_icon() -> QIcon:
    logo_path = os.path.join(_base_dir(), "logo.png")
    if os.path.exists(logo_path):
        return QIcon(logo_path)
    size = 64
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#c08020")))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawEllipse(4, 4, size - 8, size - 8)
    painter.end()
    return QIcon(px)


def main():
    _mutex = _ensure_single_instance()

    config = load_config()
    hotkey_str = config.get("hotkey", "<ctrl>+<F11>")
    api_key = load_api_key()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = InputWindow()
    signal = HotkeySignal()
    ai_signal = AISignal()
    ai_signal.responded.connect(window.show_ai_result)
    ai_signal.chunk.connect(window.append_ai_chunk)
    ai_signal.stream_done.connect(window.finish_ai_stream)

    # -- 系统托盘 --
    tray = QSystemTrayIcon(_make_tray_icon(), app)
    tray.setToolTip(f"OpenHam  ({hotkey_str})")

    tray_menu = QMenu()
    action_timer_label = QAction("🍅 剩余 --:--", tray_menu)
    action_timer_label.setEnabled(False)
    action_timer_label.setVisible(False)
    tray_menu.addAction(action_timer_label)
    action_timer_sep = tray_menu.addSeparator()
    action_timer_sep.setVisible(False)
    action_show = tray_menu.addAction("呼出窗口")
    tray_menu.addSeparator()
    action_quit = tray_menu.addAction("退出")

    action_show.triggered.connect(window.show_window)
    action_quit.triggered.connect(app.quit)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(
        lambda reason: window.show_window()
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick
        else None
    )
    tray.show()

    window.show_window()

    # 番茄钟悬浮层
    overlay = PomodoroOverlay()

    def on_hotkey():
        signal.triggered.emit()

    signal.triggered.connect(lambda: (
        window.hide_window() if window.isVisible() else window.show_window()
    ))

    # -- 番茄钟状态 --
    _timer_gen   = 0
    _timer_end   = 0.0

    countdown_qtimer = QTimer()
    countdown_qtimer.setInterval(1000)

    def _update_countdown():
        nonlocal _timer_end
        if _timer_end <= 0:
            countdown_qtimer.stop()
            return
        remaining = _timer_end - _time.time()
        if remaining <= 0:
            _timer_end = 0
            countdown_qtimer.stop()
            tray.setToolTip(f"OpenHam  ({hotkey_str})")
            action_timer_label.setVisible(False)
            action_timer_sep.setVisible(False)
            overlay.hide()
        else:
            m, s = divmod(int(remaining), 60)
            label = f"🍅 剩余 {m:02d}:{s:02d}"
            tray.setToolTip(f"OpenHam  {label}")
            action_timer_label.setText(label)
            overlay.update_text(f"🍅 {m:02d}:{s:02d}")

    countdown_qtimer.timeout.connect(_update_countdown)

    # -- AI --
    _ai_gen = 0

    def on_submitted(text: str):
        nonlocal _ai_gen, _timer_gen, _timer_end
        print(f"[on_submitted] 收到文本: {text!r}")

        # 番茄钟
        pomo = parse_pomodoro(text)
        if pomo is not None:
            action, mins = pomo
            _timer_gen += 1
            if action == "stop":
                _timer_end = 0
                countdown_qtimer.stop()
                tray.setToolTip(f"OpenHam  ({hotkey_str})")
                action_timer_label.setVisible(False)
                action_timer_sep.setVisible(False)
                overlay.hide()
                window.show_result("✅ 番茄钟已停止")
            else:
                my_gen = _timer_gen
                _timer_end = _time.time() + mins * 60
                action_timer_label.setText(f"🍅 剩余 {mins:02d}:00")
                action_timer_label.setVisible(True)
                action_timer_sep.setVisible(True)
                overlay.update_text(f"🍅 {mins:02d}:00")
                overlay.show()
                countdown_qtimer.start()
                window.show_result(f"✅ 🍅 {mins} 分钟，加油！")
                def _run(gen=my_gen, m=mins):
                    _time.sleep(m * 60)
                    if _timer_gen == gen:
                        _show_toast("🍅 番茄钟", f"{m} 分钟到了！好好休息一下 ☕")
                threading.Thread(target=_run, daemon=True).start()
            QTimer.singleShot(800, window.hide_window)
            return

        # 文件搜索模式
        if text.lstrip().startswith("找 "):
            return

        result = execute(text)
        print(f"[on_submitted] execute 结果: {result!r}")
        if result is not None:
            _ai_gen += 1
            window.show_result(result)
            if result.startswith("✅"):
                QTimer.singleShot(800, window.hide_window)
        elif api_key:
            _ai_gen += 1
            my_gen = _ai_gen
            print(f"[on_submitted] 启动 AI 线程 gen={my_gen}")
            window.show_thinking()
            def _call():
                print(f"[AI线程 gen={my_gen}] 开始流式调用 DeepSeek")
                try:
                    for piece in call_deepseek_stream(text, api_key):
                        if _ai_gen != my_gen:
                            print(f"[AI线程 gen={my_gen}] 已被新提交取消，退出")
                            return
                        ai_signal.chunk.emit(piece)
                    if _ai_gen == my_gen:
                        print(f"[AI线程 gen={my_gen}] 流式完成")
                        ai_signal.stream_done.emit()
                except Exception as e:
                    import traceback
                    print(f"[AI线程 gen={my_gen}] 未捕获异常: {e}")
                    traceback.print_exc()
                    if _ai_gen == my_gen:
                        ai_signal.responded.emit(f"❌ 线程异常：{e}")
            threading.Thread(target=_call, daemon=True).start()
        else:
            _ai_gen += 1

    window.submitted.connect(on_submitted)

    # -- 文件搜索 --
    file_signal = FileSignal()
    file_signal.results.connect(window.show_file_results)
    _search_gen = 0

    def on_search_requested(query: str):
        nonlocal _search_gen
        _search_gen += 1
        my_gen = _search_gen
        search_roots = config.get("search_roots") or None

        def _run():
            found = search_files(query, roots=search_roots)
            if _search_gen == my_gen:
                file_signal.results.emit(found)

        threading.Thread(target=_run, daemon=True).start()

    window.search_requested.connect(on_search_requested)

    # -- 全局快捷键 --
    kb_hotkey = re.sub(r'[<>]', '', hotkey_str).lower()
    kb.add_hotkey(kb_hotkey, on_hotkey, suppress=True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
