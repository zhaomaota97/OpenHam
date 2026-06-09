"""划词翻译 / 剪贴板翻译插件。

两种用法：
- 划词：在任意软件里选中文字，按 Ctrl+Alt+Z → 自动抓取选中文字并翻译。
- 手动：在输入框输入「翻译 <文字>」翻译这段；只输入「翻译」则翻译当前剪贴板。

翻译走内置 DeepSeek：中文→英文，其它→简体中文。结果显示在主窗口。
"""
import threading

from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer
from PyQt6.QtWidgets import QApplication

from core.plugin_manager import openham_plugin

_SELECT_HOTKEY = "<ctrl>+<alt>+z"   # 划词翻译热键（低级钩子会吞掉此键，故选用极少冲突的组合）

_state = {"win": None, "sig": None, "old_clip": "", "busy": False}


class _Sig(QObject):
    done = pyqtSignal(str)


def _ai_translate(text: str) -> str:
    from core.ai_client import call_deepseek_sync
    from core import app_config
    sys_prompt = (
        "你是专业翻译引擎。规则：输入若主要是中文，翻译成自然、地道的英文；"
        "否则翻译成自然、地道的简体中文。只输出译文本身，不要加引号、不要解释、"
        "不要注音、不要保留原文。保持原意与语气。"
    )
    return call_deepseek_sync(text, app_config.get_api_key(), sys_prompt, max_tokens=2048)


def _emit(msg: str):
    if _state["sig"]:
        _state["sig"].done.emit(msg)


def _do_translate(text: str):
    text = (text or "").strip()
    if not text:
        _emit("没有可翻译的文字")
        return
    # 太长的截断，避免误把整篇文档塞进去
    if len(text) > 4000:
        text = text[:4000]
    _emit("正在翻译…")

    def work():
        try:
            out = _ai_translate(text)
        except Exception as e:
            out = f"翻译失败：{e}"
        _emit((out or "（无译文）").strip())

    threading.Thread(target=work, daemon=True).start()


def _grab_selection_and_translate():
    """热键触发：抓取选中文字再翻译。在 UI 线程执行。

    关键：用户此刻仍按住 Ctrl+Alt，直接模拟的 Ctrl+C 会被按住的 Alt 污染成
    Ctrl+Alt+C（不是复制）。所以先等用户松开 Ctrl/Alt，再发干净的 Ctrl+C。
    """
    if _state.get("busy"):
        return
    _state["busy"] = True
    _state["old_clip"] = (QApplication.clipboard().text() or "")
    _wait_release_then_copy(0)


def _wait_release_then_copy(tries: int):
    import ctypes
    try:
        u = ctypes.windll.user32
        ctrl = bool(u.GetAsyncKeyState(0x11) & 0x8000)   # VK_CONTROL
        alt = bool(u.GetAsyncKeyState(0x12) & 0x8000)    # VK_MENU(Alt)
    except Exception:
        ctrl = alt = False
    if (ctrl or alt) and tries < 40:                     # 最多等 ~600ms
        QTimer.singleShot(15, lambda: _wait_release_then_copy(tries + 1))
        return
    import keyboard as kb
    try:
        kb.send("ctrl+c")
    except Exception:
        pass
    QTimer.singleShot(160, _after_copy)


def _after_copy():
    cb = QApplication.clipboard()
    sel = (cb.text() or "").strip()
    old = (_state.get("old_clip") or "").strip()
    _state["busy"] = False
    # 剪贴板没变 → 说明没复制到新选中内容（没选中/不可复制），不翻译旧内容
    if not sel or sel == old:
        _emit("没有选中文字，请先选中再按 Ctrl+Alt+Z")
        return
    # 还原用户原来的剪贴板，避免被我们 Ctrl+C 污染
    QTimer.singleShot(60, lambda: cb.setText(_state.get("old_clip") or ""))
    _do_translate(sel)


def setup_translate(api):
    win = api.call("get_main_window")
    _state["win"] = win
    sig = _Sig()

    def _on_done(t: str):
        if win is not None:
            if not win.isVisible():
                win.show_window()
            win.show_info(t)

    sig.done.connect(_on_done, Qt.ConnectionType.QueuedConnection)
    _state["sig"] = sig

    # 注册划词翻译全局热键
    api.call("register_hotkey", _SELECT_HOTKEY, _grab_selection_and_translate)


@openham_plugin(
    trigger=["翻译", "fy", "translate"],
    desc="划词翻译（选中文字按 Ctrl+Alt+Z；或「翻译 文字」/复制后输入「翻译」）",
    setup=setup_translate,
)
def execute_translate(text, *args, **kwargs):
    parts = (text or "").strip().split(maxsplit=1)
    body = parts[1].strip() if len(parts) > 1 else ""
    if not body:
        body = (QApplication.clipboard().text() or "").strip()
    if not body:
        return {"type": "error", "content": "❌ 「翻译」后输入文字，或先复制要翻译的内容再输入「翻译」"}
    _do_translate(body)
    return {"type": "info", "content": "正在翻译…"}
