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
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QAction, QKeySequence
import keyboard as kb

from ui import InputWindow, ScriptManagerOverlay
from ui.plugin_manager_window import PluginManagerWindow
from ui.settings_window import SettingsWindow
from ui.tray import _make_tray_icon, _show_toast
from core.script_engine import execute, set_script_overlay
from core.ai_client import call_deepseek_stream
from utils.paths import _base_dir
from core.signals import HotkeySignal, AISignal, FileSignal, InfoSignal




def _ensure_single_instance():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "OpenHam_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:
        sys.exit(0)
    return mutex




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


def _format_hotkey_label(hotkey: str) -> str:
    text = hotkey.replace("<", "").replace(">", "")
    parts = [p.strip() for p in text.split("+") if p.strip()]
    pretty = []
    for part in parts:
        lower = part.lower()
        if lower == "ctrl":
            pretty.append("Ctrl")
        elif lower == "alt":
            pretty.append("Alt")
        elif lower == "shift":
            pretty.append("Shift")
        elif lower == "space":
            pretty.append("Space")
        else:
            pretty.append(part.upper() if lower.startswith("f") else part.capitalize())
    return "+".join(pretty)


def main():
    _mutex = _ensure_single_instance()

    config = load_config()
    hotkey_str = config.get("hotkey", "<alt>+<space>")
    # 兼容 pynput 风格的配置（如果在 config.json 里写了 <alt> 需要剥离尖括号）
    clean_hotkey = hotkey_str.replace("<", "").replace(">", "")
    api_key = load_api_key()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = InputWindow()
    # ── 浮层组件 ──
    script_overlay = ScriptManagerOverlay()
    plugin_manager_overlay = PluginManagerWindow()
    settings_window = SettingsWindow(config)
    set_script_overlay(script_overlay)
    
    signal = HotkeySignal()
    ai_signal = AISignal()
    ai_signal.responded.connect(window.show_ai_result)
    ai_signal.chunk.connect(window.append_ai_chunk)
    ai_signal.stream_done.connect(window.finish_ai_stream)
    info_signal = InfoSignal()
    info_signal.info.connect(window.show_info)


    # -- 插件系统预备 --
    from core.plugin_manager import load_plugins, plugin_api
    plugin_api.register_handler("open_script_manager", script_overlay.open)
    plugin_api.register_handler("open_plugin_manager", plugin_manager_overlay.show_window)
    
    # -- 系统托盘 --
    tray = QSystemTrayIcon(_make_tray_icon(), app)
    tray.setToolTip(f"OpenHam  ({hotkey_str})")
    hotkey_label = _format_hotkey_label(hotkey_str)

    tray_menu = QMenu()
    tray_menu.setStyleSheet("""
        QMenu {
            background-color: #fcfcfc;
            color: #111111;
            border: none;
            border-radius: 8px;
            padding: 4px 0;
        }
        QMenu::item {
            background-color: transparent;
            padding: 4px 14px;
            margin: 0 3px;
            border-radius: 4px;
        }
        QMenu::item:selected {
            background-color: #e6e6e6;
            color: #111111;
        }
        QMenu::item:disabled {
            color: #8f8f8f;
            background-color: transparent;
        }
        QMenu::separator {
            height: 1px;
            background: #dddddd;
            margin: 6px 10px;
        }
    """)
    action_title = tray_menu.addAction("OpenHam 0.1.0")
    action_title.setEnabled(False)
    action_show = tray_menu.addAction("打开主窗口")
    action_show.setShortcut(QKeySequence(hotkey_label))
    action_show.setShortcutVisibleInContextMenu(True)
    action_script_config = tray_menu.addAction("脚本配置")
    action_plugin_config = tray_menu.addAction("插件管理")
    action_settings = tray_menu.addAction("设置...")
    tray_menu.addSeparator()
    action_quit = tray_menu.addAction("Exit")
    
    # 向插件注册底层能力
    plugin_api.register_handler("get_tray_menu", lambda: tray_menu)
    plugin_api.register_handler("get_tray_icon", lambda: tray)
    plugin_api.register_handler("get_main_window", lambda: window)
    plugin_api.register_handler("get_tray_hotkey_str", lambda: hotkey_str)
    plugin_api.register_handler("get_config", lambda key, default=None: config.get(key, default))
    plugin_api.register_handler("show_toast", _show_toast)
    
    # 全部核心依赖注册完毕，触发插件 setup 生命周期钩子
    load_plugins()

    action_show.triggered.connect(window.show_window)
    action_script_config.triggered.connect(script_overlay.open)
    action_plugin_config.triggered.connect(plugin_manager_overlay.show_window)
    action_settings.triggered.connect(settings_window.show_window)
    action_quit.triggered.connect(app.quit)
    tray.setContextMenu(tray_menu)
    def _on_tray_activated(reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            window.show_window()

    tray.activated.connect(_on_tray_activated)
    tray.show()

    window.show_window()

    _last_hotkey_time = 0.0
    def on_hotkey():
        nonlocal _last_hotkey_time
        now = _time.time()
        if now - _last_hotkey_time < 0.3:
            return
        _last_hotkey_time = now
        signal.triggered.emit()

    signal.triggered.connect(lambda: (
        window.hide_window() if window.isVisible() else window.show_window()
    ))
    kb.add_hotkey(clean_hotkey, on_hotkey, suppress=True)

    # -- AI --
    _ai_gen = 0

    def on_submitted(text: str):
        nonlocal _ai_gen
        print(f"[on_submitted] 收到文本: {text!r}")

        # 内置：管理面
        if text.strip() in ("脚本", "脚本配置"):
            script_overlay.open()
            window.show_result("✅ 已打开脚本管理器")
            QTimer.singleShot(800, window.hide_window)
            return

        # 插件系统调度
        from core.plugin_manager import execute_plugin
        plugin_result = execute_plugin(text.strip())
        if plugin_result:
            p_type = plugin_result.get("type", "text")
            p_content = plugin_result.get("content", "")
            if p_type == "info":
                window.show_info(p_content)
            elif p_type == "qr":
                window.show_qr(p_content)
            else:
                window.show_result(p_content)
                if "✅" in str(p_content):
                    QTimer.singleShot(800, window.hide_window)
            return

        # 文件搜索模式
        if text.lstrip().startswith("找 "):
            return


        result = execute(text)
        print(f"[on_submitted] execute 结果: {result!r}")
        if result is not None:
            _ai_gen += 1
            if result.startswith("ℹ️"):
                window.show_info(result[2:].strip())
            else:
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
