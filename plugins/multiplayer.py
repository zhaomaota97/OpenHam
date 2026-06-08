"""联机插件：和朋友跨公网一起聊天、玩游戏。

把原本写在 main.py 里的联机功能抽成自带插件，可在「插件管理」里开关。
输入「联机 / 聊天 / 房间」即可打开联机窗口。
"""
from core.plugin_manager import openham_plugin

_api = None
_win = None


def setup_multiplayer(api):
    """插件生命周期钩子：仅创建联机窗口（不加托盘项，只靠输入「联机」触发）。"""
    global _api, _win
    _api = api
    # 延迟导入：插件被禁用时根本不加载联机相关模块
    from ui.multiplayer_window import MultiplayerWindow
    _win = MultiplayerWindow()


@openham_plugin(
    trigger=["联机", "聊天", "房间"],
    desc="🎮 和朋友联机：聊天 + 一起玩游戏",
    setup=setup_multiplayer,
)
def execute_multiplayer(text, *args, **kwargs):
    if _win is not None:
        _win.show_window()
        return {"type": "result", "content": "✅ 已打开联机窗口"}
    return {"type": "error", "content": "❌ 联机插件未就绪"}
