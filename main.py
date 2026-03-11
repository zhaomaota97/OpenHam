import sys
import os
import json
import ctypes
import threading
from dotenv import load_dotenv  # ← 添加这行
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush
from pynput import keyboard


from window import InputWindow
from executor import execute, call_deepseek_stream


def _base_dir() -> str:
    """返回 config.json 所在目录：打包后为 exe 所在目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_single_instance():
    """用 Windows 命名互斥体保证单实例，已有实例时直接退出。"""
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "OpenHam_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    return mutex  # 保持引用，防止被 GC 释放


# pynput 运行在子线程，需要通过 Qt 信号跨线程通信
class HotkeySignal(QObject):
    triggered = pyqtSignal()

class AISignal(QObject):
    responded   = pyqtSignal(str)  # 错误时使用
    chunk       = pyqtSignal(str)  # 流式文本片段
    stream_done = pyqtSignal()     # 流结束，移除光标

def load_config():
    path = os.path.join(_base_dir(), "config.json")
    if not os.path.exists(path):
        return {}   # 找不到配置文件时使用默认值
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_api_key():
    """从环境变量读取 API 密钥，防止明文存储。"""
    # 加载 .env 文件（如果存在）
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("[警告] 未设置 DEEPSEEK_API_KEY 环境变量，AI 功能将不可用")
    return api_key


def _make_tray_icon() -> QIcon:
    """优先使用 logo.png，找不到时退回代码生成图标。"""
    logo_path = os.path.join(_base_dir(), "logo.png")
    if os.path.exists(logo_path):
        return QIcon(logo_path)
    # 兜底：代码生成暖金圆形图标
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
    _mutex = _ensure_single_instance()  # 单实例检测，已运行则退出

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

    # ── 系统托盘 ──────────────────────────────────────────
    tray = QSystemTrayIcon(_make_tray_icon(), app)
    tray.setToolTip(f"OpenHam  ({hotkey_str})")

    tray_menu = QMenu()
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

    # 启动时自动弹出窗口
    window.show_window()

    # 快捷键触发 → 发信号 → 主线程显示窗口
    def on_hotkey():
        signal.triggered.emit()

    signal.triggered.connect(lambda: (
        window.hide_window() if window.isVisible() else window.show_window()
    ))

    # 指令提交处理
    _ai_gen = 0   # 每次新提交自增，旧线程检测到不一致后自动放弃

    def on_submitted(text: str):
        nonlocal _ai_gen
        print(f"[on_submitted] 收到文本: {text!r}")
        result = execute(text)
        print(f"[on_submitted] execute 结果: {result!r}")
        if result is not None:
            # 命中预设指令
            _ai_gen += 1
            window.show_result(result)
            if result.startswith("✅"):
                QTimer.singleShot(800, window.hide_window)
        elif api_key:
            # 未命中 → 立即显示"正在思考"并调用 AI
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
            # 没有 API Key，什么都不做
            _ai_gen += 1

    window.submitted.connect(on_submitted)

    # 启动全局快捷键监听
    listener = keyboard.GlobalHotKeys({hotkey_str: on_hotkey})
    listener.start()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()


