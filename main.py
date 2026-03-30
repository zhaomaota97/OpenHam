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

from ui import InputWindow, PomodoroOverlay, GitLabOverlay, ScriptManagerOverlay, ScreenCaptureOverlay
from ui.tray import _make_tray_icon, _show_toast
from core.script_engine import execute, set_script_overlay
from core.ai_client import call_deepseek_stream
from utils.search import search_files
from utils.system_tools import parse_pomodoro, get_system_info, generate_qr_bytes
from utils.paths import _base_dir
from utils.ocr_tools import extract_text_from_image
import asyncio

from gitlab import preset as gitlab_preset
from gitlab.watched_repos import WatchedReposManager
from core.signals import HotkeySignal, AISignal, FileSignal, InfoSignal, GitLabSignal, BranchResultSignal, OCRSignal




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




def main():
    _mutex = _ensure_single_instance()

    config = load_config()
    hotkey_str = config.get("hotkey", "ctrl+f11")
    # 兼容 pynput 风格的配置（如果在 config.json 里写了 <alt> 需要剥离尖括号）
    clean_hotkey = hotkey_str.replace("<", "").replace(">", "")
    api_key = load_api_key()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = InputWindow()
    # ── 脚本管理器浮层 ──
    script_overlay = ScriptManagerOverlay()
    set_script_overlay(script_overlay)
    signal = HotkeySignal()
    ai_signal = AISignal()
    ai_signal.responded.connect(window.show_ai_result)
    ai_signal.chunk.connect(window.append_ai_chunk)
    ai_signal.stream_done.connect(window.finish_ai_stream)
    info_signal = InfoSignal()
    info_signal.info.connect(window.show_info)

    # -- GitLab 关注仓库管理 --
    _gl_token = os.getenv("GITLAB_TOKEN", "").strip() or None
    manager = WatchedReposManager(gitlab_preset.GITLAB_BASE_URL, _gl_token)

    gitlab_overlay = GitLabOverlay()
    gitlab_signal = GitLabSignal()
    gitlab_signal.data.connect(gitlab_overlay.update_data)
    branch_result_signal = BranchResultSignal()
    branch_result_signal.result.connect(gitlab_overlay.show_branch_choices)

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
    action_script_config = tray_menu.addAction("脚本配置")
    tray_menu.addSeparator()
    action_quit = tray_menu.addAction("退出")

    action_show.triggered.connect(window.show_window)
    action_script_config.triggered.connect(script_overlay.open)
    action_quit.triggered.connect(app.quit)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(
        lambda reason: window.show_window()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    window.show_window()

    # 番茄钟悬浮层
    overlay = PomodoroOverlay()

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

    # -- OCR 屏幕抓取与文字识别 --
    ocr_hotkey_str = config.get("ocr_hotkey", "ctrl+f12")
    clean_ocr_hotkey = ocr_hotkey_str.replace("<", "").replace(">", "")
    ocr_overlay = ScreenCaptureOverlay()
    ocr_signal = OCRSignal()

    def on_ocr_finished(text: str):
        window.result_label.setText("")
        if text and text.strip():
            # 自动复制到剪贴板
            app.clipboard().setText(text)
            window.show_result("✅ 识别结果已复制到剪贴板")
            window.show_window()
        else:
            window.show_result("❌ 本地 OCR 未识别到文本")
            window.show_window()

    def on_capture_finished(pixmap: QPixmap):
        window.show_window()
        window.input.clear()
        window.result_label.setStyleSheet("color: #8a7040; font-size: 12px;")
        window.result_label.setText("🔍 正在识别截屏文字…")
        
        def _bg_ocr():
            try:
                text = asyncio.run(extract_text_from_image(pixmap.toImage()))
            except Exception:
                text = ""
            ocr_signal.finished.emit(text)
            
        threading.Thread(target=_bg_ocr, daemon=True).start()

    ocr_overlay.capture_finished.connect(on_capture_finished)
    ocr_signal.triggered.connect(ocr_overlay.start_capture)
    ocr_signal.finished.connect(on_ocr_finished)
    
    def on_ocr_hotkey():
        ocr_signal.triggered.emit()

    kb.add_hotkey(clean_ocr_hotkey, on_ocr_hotkey, suppress=True)

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

        # 屏幕文字识别 (本地 OCR)
        if text.lower() in ("ocr", "提取文字", "截图翻译"):
            ocr_signal.triggered.emit()
            window.show_result("✅ 请框选需要识别的区域（按 ESC 取消）")
            return

        # 电脑信息
        if text == "电脑信息":
            window.show_info(get_system_info())
            return

        # 剪贴板转二维码
        if text == "转二维码":
            clip = QApplication.clipboard().text().strip()
            if not clip:
                window.show_result("❌ 剪贴板为空")
                return
            png = generate_qr_bytes(clip)
            if png is None:
                window.show_result("❌ 请先安装 qrcode 库")
                return
            window.show_qr(png)
            return

        # GitLab 仓库提交查询（网络请求，异步执行）
        if gitlab_preset.is_gitlab_query(text):
            _ai_gen += 1
            my_gen = _ai_gen
            gitlab_overlay.show_loading()
            window.input.clear()
            window.hide_window()
            def _gitlab_call(t=text, gen=my_gen):
                result = manager.fetch_structured()
                if _ai_gen == gen:
                    gitlab_signal.data.emit(result)
            threading.Thread(target=_gitlab_call, daemon=True).start()
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

    # -- GitLab 浮层信号 --
    def _reload_edit():
        gitlab_overlay.load_edit_repos(
            manager.get_repos(),
            manager.is_webhook_enabled(),
            manager.get_webhook_url(),
        )

    def on_gitlab_refresh():
        gitlab_overlay.show_loading()
        def _fetch():
            gitlab_signal.data.emit(manager.fetch_structured())
        threading.Thread(target=_fetch, daemon=True).start()

    def on_branch_fetch(url: str):
        def _fetch():
            branch_result_signal.result.emit(url, manager.fetch_branches(url))
        threading.Thread(target=_fetch, daemon=True).start()

    def on_repo_add(url: str, name: str, branches: list):
        manager.add_or_update(url, name, branches)
        _reload_edit()

    def on_repo_remove(url: str):
        manager.remove(url)
        _reload_edit()

    def on_webhook_toggle(enabled: bool):
        manager.set_webhook_enabled(enabled)
        if enabled:
            manager.start_webhook_server(
                lambda: gitlab_signal.data.emit(manager.fetch_structured())
            )
        _reload_edit()

    gitlab_overlay.refresh_requested.connect(on_gitlab_refresh)
    gitlab_overlay.edit_mode_opened.connect(_reload_edit)
    gitlab_overlay.branch_fetch_requested.connect(on_branch_fetch)
    gitlab_overlay.repo_add_requested.connect(on_repo_add)
    gitlab_overlay.repo_remove_requested.connect(on_repo_remove)
    gitlab_overlay.webhook_toggle.connect(on_webhook_toggle)

    # 启动 ETag 后台轮询（30秒，有新提交自动刷新浮层）
    manager.start_polling(lambda data: gitlab_signal.data.emit(data))

    # -- 全局快捷键 --
    kb_hotkey = re.sub(r'[<>]', '', hotkey_str).lower()
    kb.add_hotkey(kb_hotkey, on_hotkey, suppress=True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
