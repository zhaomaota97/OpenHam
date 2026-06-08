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
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QAction, QKeySequence
import keyboard as kb

# ── Qt WebEngine 预初始化（必须在 QApplication 创建前完成）──────────────
# 游戏沙箱窗口用 QWebEngineView。Qt 要求其初始化早于 QApplication，否则
# 首次打开游戏窗口会直接闪退。这里在创建 QApplication 之前先就位。
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
try:
    from PyQt6 import QtWebEngineWidgets as _qtwe  # noqa: F401  仅为提前初始化 WebEngine
except Exception:
    _qtwe = None

from ui import InputWindow, ScriptManagerOverlay
from ui.plugin_manager_window import PluginManagerWindow
from ui.settings_window import SettingsWindow
from ui.multiplayer_window import MultiplayerWindow
from ui.tray import _make_tray_icon, _show_toast
from core.script_engine import execute, set_script_overlay
from core.ai_client import call_deepseek_stream
from core import app_config
from core.logging_setup import setup_logging, get_logger
from utils.paths import _base_dir
from core.signals import HotkeySignal, AISignal, FileSignal, InfoSignal, AppSignal
from utils.search import search_files
from utils.app_index import search_apps
from utils.global_hotkey import register_global_hotkey, claim_hotkey_aggressive

log = get_logger("main")




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
    # 兼容旧版 .env，并以用户设置（设置界面填写）为优先来源
    load_dotenv()
    api_key = app_config.get_api_key()
    if not api_key:
        log.warning("未配置 DeepSeek API Key，AI 功能不可用（可在「设置 → AI 模型」中填写）")
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


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin():
    """以管理员身份重启自身（弹 UAC）。无控制台优先用 pythonw.exe。"""
    try:
        exe = sys.executable
        pw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(pw):
            exe = pw
        script = os.path.abspath(sys.argv[0])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, f'"{script}"', None, 1)
    except Exception as e:
        log.warning("以管理员重启失败：%s", e)


def main():
    setup_logging()
    log.info("OpenHam 启动")
    # 强制管理员：非管理员则尝试以管理员重启，当前实例退出（不授权则不运行）
    if os.name == "nt" and not _is_admin():
        log.info("非管理员身份，尝试以管理员重启")
        _relaunch_as_admin()
        sys.exit(0)
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
    multiplayer_window = MultiplayerWindow()
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
    action_multiplayer = tray_menu.addAction("联机")
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
    action_multiplayer.triggered.connect(multiplayer_window.show_window)
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
    ), Qt.ConnectionType.QueuedConnection)
    # 优先用 Win32 RegisterHotKey 抢占（OS 级，压制系统菜单，优先级最高）；
    # 失败（组合被别的应用占用）再回退到 keyboard 库的低级钩子。
    try:
        _hwnd = int(window.winId())
        if claim_hotkey_aggressive(hotkey_str, on_hotkey):
            log.info("全局热键已用低级钩子抢占（可压过其它应用）：%s", hotkey_str)
        elif register_global_hotkey(app, _hwnd, hotkey_str, on_hotkey):
            log.info("全局热键已用 RegisterHotKey 注册：%s", hotkey_str)
        else:
            log.warning("热键抢占失败，回退 keyboard 库")
            kb.add_hotkey(clean_hotkey.lower(), on_hotkey, suppress=True)
    except Exception as e:
        log.exception("注册全局热键异常，回退 keyboard 库：%s", e)
        kb.add_hotkey(clean_hotkey.lower(), on_hotkey, suppress=True)

    # -- AI --
    _ai_gen = 0

    def on_submitted(text: str):
        nonlocal _ai_gen
        log.debug("收到文本: %r", text)

        # 内置：管理面
        if text.strip() in ("脚本", "脚本配置"):
            script_overlay.open()
            window.show_result("✅ 已打开脚本管理器")
            QTimer.singleShot(800, window.hide_window)
            return

        if text.strip() in ("联机", "聊天", "房间"):
            multiplayer_window.show_window()
            window.show_result("✅ 已打开联机窗口")
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
        log.debug("execute 结果: %r", result)
        if result is not None:
            _ai_gen += 1
            if result.startswith("ℹ️"):
                window.show_info(result[2:].strip())
            else:
                window.show_result(result)
                if result.startswith("✅"):
                    QTimer.singleShot(800, window.hide_window)
        elif app_config.get_api_key():
            # 实时读取 Key：用户在设置界面改完无需重启即可生效
            _ai_gen += 1
            my_gen = _ai_gen
            log.info("启动 AI 线程 gen=%d", my_gen)
            window.show_thinking()
            def _call():
                try:
                    for piece in call_deepseek_stream(text):
                        if _ai_gen != my_gen:
                            log.debug("AI 线程 gen=%d 已被新提交取消", my_gen)
                            return
                        ai_signal.chunk.emit(piece)
                    if _ai_gen == my_gen:
                        log.info("AI 线程 gen=%d 流式完成", my_gen)
                        ai_signal.stream_done.emit()
                except Exception as e:
                    log.exception("AI 线程 gen=%d 异常: %s", my_gen, e)
                    if _ai_gen == my_gen:
                        ai_signal.responded.emit(f"❌ 线程异常：{e}")
            threading.Thread(target=_call, daemon=True).start()
        else:
            _ai_gen += 1
            window.show_ai_result("❌ 未配置 API Key：请在「设置 → AI 模型」中填入你的 DeepSeek Key")

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

    # -- 应用启动器搜索 --
    app_signal = AppSignal()
    app_signal.results.connect(window.show_app_results)
    _app_gen = 0

    def on_app_search_requested(query: str):
        nonlocal _app_gen
        _app_gen += 1
        my_gen = _app_gen

        def _run():
            try:
                found = search_apps(query)
            except Exception as e:
                log.exception("应用搜索异常: %s", e)
                found = []
            if _app_gen == my_gen:
                app_signal.results.emit(found)

        threading.Thread(target=_run, daemon=True).start()

    window.app_search_requested.connect(on_app_search_requested)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
