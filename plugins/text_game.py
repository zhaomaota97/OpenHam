"""文字游戏插件：AI 文字冒险 / RPG 引擎。

输入「文字游戏」/「文字冒险」/「冒险」唤起；托盘菜单亦提供「文字游戏」项。
窗口本体见 ui/text_game_window.TextGameWindow；插件只负责单例创建与唤起。
"""
from core.plugin_manager import openham_plugin

_window = None   # 单例窗口


def setup_text_game(api):
    """插件加载时预创建窗口（运行在 GUI 主线程）。"""
    global _window
    try:
        from ui.text_game_window import TextGameWindow
        _window = TextGameWindow()
    except Exception as e:
        print(f"[text_game] 窗口预创建失败: {e}")
        _window = None
    # 注册「打开文字游戏」能力：main.py 据此在托盘菜单加项（仅插件启用时）
    api.register_handler("open_text_game", _open)


def _ensure_window():
    global _window
    if _window is None:
        from ui.text_game_window import TextGameWindow
        _window = TextGameWindow()
    return _window


def _open():
    try:
        _ensure_window().open()
    except Exception as e:
        print(f"[text_game] 打开失败: {e}")


@openham_plugin(
    trigger=["文字游戏", "文字冒险", "冒险"],
    desc="文字游戏（AI 文字冒险 / RPG 引擎）",
    setup=setup_text_game,
)
def execute_text_game(text: str):
    try:
        _ensure_window().open()
    except Exception as e:
        return {"type": "error", "content": f"❌ 无法打开文字游戏：{e}"}
    return {"type": "result", "content": "✅ 已打开文字游戏"}
