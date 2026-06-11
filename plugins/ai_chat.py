"""AI 对话插件：常规聊天软件式界面（参考 Monica）。

- 支持保存历史会话、切换会话、新建会话；
- 助手回复用 Markdown 渲染、流式输出、携带上下文；
- 模型沿用全局 AI 配置（core.ai_client）。

触发后弹出独立窗口（ui/ai_chat_window.AIChatWindow），插件本体只负责
单例创建与唤起。窗口在 setup 阶段（GUI 线程）预创建，避免首次触发卡顿。
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


@openham_plugin(
    trigger=["对话", "ai对话", "chat", "聊天", "ai"],
    desc="🧠 AI 对话（多轮 / 保存历史 / Markdown）",
    setup=setup_ai_chat,
)
def execute_ai_chat(text: str):
    global _window
    if _window is None:
        # setup 未成功时兜底再建一次
        try:
            from ui.ai_chat_window import AIChatWindow
            _window = AIChatWindow()
        except Exception as e:
            return {"type": "error", "content": f"❌ 无法打开 AI 对话：{e}"}
    _window.open()
    return {"type": "result", "content": "✅ 已打开 AI 对话"}
