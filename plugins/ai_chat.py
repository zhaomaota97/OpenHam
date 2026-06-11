"""AI 对话插件：Monica 风格的多 Bot 聊天窗口。

入口：主程序输入框里以 `--` 开头即唤起（无其它触发词）。
- `--`            → 仅打开窗口
- `--什么是土豆粉` → 打开窗口并自动发送「什么是土豆粉」

窗口本体见 ui/ai_chat_window.AIChatWindow；插件只负责单例创建与唤起/转发。
"""
from core.plugin_manager import openham_plugin

_window = None   # 单例窗口


def setup_ai_chat(api):
    """插件加载时预创建对话窗口（运行在 GUI 主线程）。"""
    global _window
    try:
        from ui.ai_chat_window import AIChatWindow
        _window = AIChatWindow()
    except Exception as e:
        print(f"[ai_chat] 窗口预创建失败: {e}")
        _window = None


def _ensure_window():
    global _window
    if _window is None:
        from ui.ai_chat_window import AIChatWindow
        _window = AIChatWindow()
    return _window


def match_dashdash(text: str) -> bool:
    """以 `--` 开头即触发（作为 AI 对话的快捷命令前缀）。"""
    return text.strip().startswith("--")


@openham_plugin(
    match=match_dashdash,
    desc="🧠 AI 对话（-- 前缀唤起 / 多 Bot / 多轮 / Markdown）",
    setup=setup_ai_chat,
)
def execute_ai_chat(text: str):
    try:
        win = _ensure_window()
    except Exception as e:
        return {"type": "error", "content": f"❌ 无法打开 AI 对话：{e}"}

    query = text.strip()[2:].strip()   # 去掉前导 --
    if query:
        win.send_text(query)
        preview = query if len(query) <= 16 else query[:16] + "…"
        return {"type": "result", "content": f"✅ 已发送：{preview}"}
    win.open()
    return {"type": "result", "content": "✅ 已打开 AI 对话"}
