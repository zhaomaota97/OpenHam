import sys
import os
import json
import ctypes
import threading
import subprocess
import time as _time
import re
from dotenv import load_dotenv
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QAction, QKeySequence, QFont
import keyboard as kb

# ── 高 DPI 感知（必须在创建任何窗口之前）──────────────────────────────
# 不声明 DPI 感知时，系统缩放(125%/150%)会把窗口当位图拉伸 → 文字发虚。
# 这里声明 Per-Monitor V2，让 Qt 按真实像素渲染，文字才清晰。
def _set_dpi_aware():
    try:
        # PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
_set_dpi_aware()

# ── Qt WebEngine 预初始化（必须在 QApplication 创建前完成）──────────────
# 游戏沙箱窗口用 QWebEngineView。Qt 要求其初始化早于 QApplication，否则
# 首次打开游戏窗口会直接闪退。这里在创建 QApplication 之前先就位。
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
try:
    from PyQt6 import QtWebEngineWidgets as _qtwe  # noqa: F401  仅为提前初始化 WebEngine
except Exception:
    _qtwe = None

from ui import InputWindow, ScriptManagerOverlay
from ui import icons
from ui import theme
from ui.plugin_manager_window import PluginManagerWindow
from ui.settings_window import SettingsWindow
from ui.tray import _make_tray_icon, _show_toast
from core.script_engine import execute, set_script_overlay
from core.ai_client import call_deepseek_stream
from core import app_config
from core.logging_setup import setup_logging, get_logger
from utils.paths import _base_dir
from core.signals import HotkeySignal, AISignal, FileSignal, InfoSignal, AppSignal, UpdateSignal
from core import updater
from utils.search import search_files
from utils.app_index import search_apps
from utils.global_hotkey import register_global_hotkey, claim_hotkey_aggressive

log = get_logger("main")




def _ensure_single_instance():
    k = ctypes.windll.kernel32
    for _ in range(30):  # 最多等 3 秒：自动重启时旧实例可能还没退出释放锁
        mutex = k.CreateMutexW(None, False, "OpenHam_SingleInstance")
        if k.GetLastError() != 183:   # 不是 ERROR_ALREADY_EXISTS → 拿到锁
            return mutex
        k.CloseHandle(mutex)
        _time.sleep(0.1)
    sys.exit(0)




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


def _ensure_qtawesome():
    """图标库必须就绪：缺失则当场从镜像装上（约 3MB，很快），保证图标可见。
    增量更新的依赖同步偶尔会失败，这里作为兜底，避免界面图标全空。"""
    import importlib.util
    if importlib.util.find_spec("qtawesome") is not None:
        return
    try:
        import subprocess
        log.info("检测到缺少 qtawesome，正在安装…")
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        subprocess.run([sys.executable, "-m", "pip", "install", "qtawesome"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=flags, timeout=180)
        importlib.invalidate_caches()
    except Exception as e:
        log.warning("自动安装 qtawesome 失败：%s（图标将降级显示）", e)


def main():
    setup_logging()
    log.info("OpenHam 启动")
    _mutex = _ensure_single_instance()
    _ensure_qtawesome()

    config = load_config()
    hotkey_str = config.get("hotkey", "<alt>+<space>")
    # 兼容 pynput 风格的配置（如果在 config.json 里写了 <alt> 需要剥离尖括号）
    clean_hotkey = hotkey_str.replace("<", "").replace(">", "")
    api_key = load_api_key()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # 统一清晰的 UI 字体（微软雅黑 UI 在 Windows 上中英文都锐利）
    _ui_font = QFont("Microsoft YaHei UI", 10)
    _ui_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(_ui_font)
    # 加载 Qt 中文翻译：让标准右键菜单（撤销/剪切/复制/粘贴/全选等）显示中文
    try:
        from PyQt6.QtCore import QTranslator, QLibraryInfo
        _tr_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        app._qt_translators = []
        for _name in ("qtbase_zh_CN", "qt_zh_CN"):
            _t = QTranslator()
            if _t.load(_name, _tr_dir):
                app.installTranslator(_t)
                app._qt_translators.append(_t)   # 保持引用，避免被回收
    except Exception as _e:
        log.warning("加载 Qt 中文翻译失败：%s", _e)
    # 全局浅色主题：右键菜单、提示、滚动条、对话框等标准控件统一「精致白」
    app.setStyleSheet(theme.app_qss())

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

    tray_menu = QMenu()   # 样式继承全局 theme.app_qss()
    action_title = tray_menu.addAction("OpenHam 0.1.0")
    action_title.setEnabled(False)
    action_show = tray_menu.addAction("打开主窗口")
    action_show.setShortcut(QKeySequence(hotkey_label))
    action_show.setShortcutVisibleInContextMenu(True)
    action_script_config = tray_menu.addAction("脚本配置")
    action_plugin_config = tray_menu.addAction("插件管理")
    action_settings = tray_menu.addAction("设置...")
    action_update = tray_menu.addAction("检查更新")
    tray_menu.addSeparator()
    action_quit = tray_menu.addAction("退出")
    
    # 主界面最近一次「一次性 AI 问答」{q, a}，供 -- 快捷指令携带上一轮上下文；
    # 任何非 -- 操作都会把它清空（见 on_submitted），只有一次性 AI 完成时再填充。
    _last_oneshot = None

    def _pop_last_oneshot():
        nonlocal _last_oneshot
        v = _last_oneshot
        _last_oneshot = None     # 取走即清空，避免下一次 -- 误带旧上下文
        return v

    # 向插件注册底层能力
    plugin_api.register_handler("get_tray_menu", lambda: tray_menu)
    plugin_api.register_handler("get_tray_icon", lambda: tray)
    plugin_api.register_handler("get_main_window", lambda: window)
    plugin_api.register_handler("get_tray_hotkey_str", lambda: hotkey_str)
    plugin_api.register_handler("get_config", lambda key, default=None: config.get(key, default))
    plugin_api.register_handler("show_toast", _show_toast)
    plugin_api.register_handler("pop_last_oneshot", _pop_last_oneshot)

    # 插件注册全局热键：低级钩子在钩子线程触发，这里用 Qt 信号派发回 UI 线程执行
    class _PluginHotkeySignal(QObject):
        fired = pyqtSignal(object)
    _pl_hotkey_sig = _PluginHotkeySignal()
    _pl_hotkey_sig.fired.connect(lambda cb: cb(), Qt.ConnectionType.QueuedConnection)
    app._pl_hotkey_sig = _pl_hotkey_sig   # 保活

    def _register_plugin_hotkey(hotkey_combo, callback):
        from utils.global_hotkey import add_hotkey_aggressive
        try:
            ok = add_hotkey_aggressive(hotkey_combo, lambda: _pl_hotkey_sig.fired.emit(callback))
            log.info("插件全局热键注册 %s：%s", hotkey_combo, "成功" if ok else "失败")
            return ok
        except Exception as e:
            log.warning("插件全局热键注册失败 %s：%s", hotkey_combo, e)
            return False
    plugin_api.register_handler("register_hotkey", _register_plugin_hotkey)

    # 全部核心依赖注册完毕，触发插件 setup 生命周期钩子
    load_plugins()

    # AI 聊天插件启用时（注册了 open_chat），在托盘菜单「联机」下、「设置」上加「聊天」项。
    # 放在 load_plugins() 之后，确保「联机」「设置」都已就位，顺序确定。
    if "open_chat" in plugin_api._handlers:
        chat_act = QAction("聊天", tray_menu)
        chat_act.triggered.connect(lambda: plugin_api.call("open_chat"))
        _acts = tray_menu.actions()
        _lianji = next((a for a in _acts if a.text() == "联机"), None)
        if _lianji is not None:                       # 插在「联机」之后
            _i = _acts.index(_lianji)
            _after = _acts[_i + 1] if _i + 1 < len(_acts) else None
            tray_menu.insertAction(_after, chat_act) if _after else tray_menu.addAction(chat_act)
        else:                                          # 无联机则插在「设置」之前
            _settings = next((a for a in _acts if a.text().startswith("设置")), None)
            tray_menu.insertAction(_settings, chat_act) if _settings else tray_menu.addAction(chat_act)

    # 文字游戏插件启用时（注册了 open_text_game），在「聊天」之后、「设置」之前加「文字游戏」项。
    if "open_text_game" in plugin_api._handlers:
        game_act = QAction("文字游戏", tray_menu)
        game_act.triggered.connect(lambda: plugin_api.call("open_text_game"))
        _acts = tray_menu.actions()
        _chat = next((a for a in _acts if a.text() == "聊天"), None)
        if _chat is not None:                          # 插在「聊天」之后
            _i = _acts.index(_chat)
            _after = _acts[_i + 1] if _i + 1 < len(_acts) else None
            tray_menu.insertAction(_after, game_act) if _after else tray_menu.addAction(game_act)
        else:
            _settings = next((a for a in _acts if a.text().startswith("设置")), None)
            tray_menu.insertAction(_settings, game_act) if _settings else tray_menu.addAction(game_act)

    action_show.triggered.connect(window.show_window)
    action_script_config.triggered.connect(script_overlay.open)
    action_plugin_config.triggered.connect(plugin_manager_overlay.show_window)
    action_settings.triggered.connect(settings_window.show_window)

    # ── 增量更新 ──────────────────────────────────────────────────────
    update_signal = UpdateSignal()
    _upd = {"dlg": None}

    def _check_update(manual=False):
        def _w():
            has, ver, url, notes = updater.check_update(app_config.get("update_url"))
            if has:
                update_signal.available.emit(ver, url, notes)
            elif manual:
                update_signal.done.emit(True, "__latest__")
        threading.Thread(target=_w, daemon=True).start()

    def _on_update_available(ver, url, notes):
        tip = "检测到新版本，是否现在更新？\n更新完成后将自动重启 OpenHam。"
        if QMessageBox.question(None, "软件更新", tip) != QMessageBox.StandardButton.Yes:
            return
        from PyQt6.QtWidgets import QProgressDialog
        dlg = QProgressDialog("正在下载更新…", None, 0, 0, None)
        dlg.setWindowTitle("OpenHam 更新")
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setMinimumWidth(360)
        dlg.show()
        _upd["dlg"] = dlg

        def _apply():
            try:
                ok = updater.apply_update(url, progress_cb=lambda d, t: update_signal.progress.emit(d, t))
                update_signal.done.emit(ok, "" if ok else "更新失败")
            except Exception as e:
                update_signal.done.emit(False, str(e))
        threading.Thread(target=_apply, daemon=True).start()

    def _on_update_progress(done, total):
        dlg = _upd["dlg"]
        if dlg is None:
            return
        if total > 0 and done < total:
            dlg.setMaximum(total)
            dlg.setValue(done)
            dlg.setLabelText(f"正在下载更新…  {done/1024:.0f} / {total/1024:.0f} KB")
        else:
            dlg.setMaximum(0)  # 下载完成 → 进入应用/校验依赖阶段（不确定进度）
            dlg.setValue(0)
            dlg.setLabelText("正在应用更新、校验依赖…")

    def _on_update_done(ok, message):
        dlg = _upd["dlg"]
        if dlg is not None:
            dlg.close()
            _upd["dlg"] = None
        if message == "__latest__":
            QMessageBox.information(None, "检查更新", "已是最新版本。")
        elif ok:
            QMessageBox.information(None, "更新完成", "更新已完成，OpenHam 将自动重启以应用更新。")
            from utils.restart import restart_app
            restart_app()
        else:
            QMessageBox.warning(None, "更新失败", message or "更新失败，请检查网络。")

    update_signal.available.connect(_on_update_available)
    update_signal.progress.connect(_on_update_progress)
    update_signal.done.connect(_on_update_done)
    action_update.triggered.connect(lambda: _check_update(manual=True))
    QTimer.singleShot(5000, lambda: _check_update(manual=False))  # 启动后台静默检查
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
        nonlocal _ai_gen, _last_oneshot
        log.debug("收到文本: %r", text)

        # 非 -- 操作都重置「上一轮一次性问答」；-- 指令保留它以便携带上下文
        if not text.strip().startswith("--"):
            _last_oneshot = None

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
                nonlocal _last_oneshot
                answer = ""
                try:
                    for piece in call_deepseek_stream(text):
                        if _ai_gen != my_gen:
                            log.debug("AI 线程 gen=%d 已被新提交取消", my_gen)
                            return
                        answer += piece
                        ai_signal.chunk.emit(piece)
                    if _ai_gen == my_gen:
                        log.info("AI 线程 gen=%d 流式完成", my_gen)
                        # 记录这轮一次性问答，供随后的 -- 指令携带为上下文
                        if answer.strip() and not answer.lstrip().startswith("❌"):
                            _last_oneshot = {"q": text, "a": answer}
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
