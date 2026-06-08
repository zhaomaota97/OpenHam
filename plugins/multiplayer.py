"""联机插件：和朋友跨公网一起聊天、玩游戏。

把原本写在 main.py 里的联机功能抽成自带插件，可在「插件管理」里开关。
启用后：托盘菜单出现「联机」项，输入「联机」也能打开。
"""
from PyQt6.QtGui import QAction

from core.plugin_manager import openham_plugin

_api = None
_win = None


def setup_multiplayer(api):
    """插件生命周期钩子：创建联机窗口，并往托盘菜单加入「联机」项。
    热重载安全：先移除残留的旧「联机」项，避免重复或指向旧窗口。"""
    global _api, _win
    _api = api
    # 延迟导入：插件被禁用时根本不加载联机相关模块
    from ui.multiplayer_window import MultiplayerWindow
    _win = MultiplayerWindow()

    tray_menu = api.call("get_tray_menu")
    if tray_menu:
        for a in list(tray_menu.actions()):
            if a.text() == "联机":
                tray_menu.removeAction(a)
        act = QAction("联机", tray_menu)
        act.triggered.connect(lambda: _win.show_window())
        anchor = next((a for a in tray_menu.actions() if a.text().startswith("设置")), None)
        if anchor:
            tray_menu.insertAction(anchor, act)
        else:
            tray_menu.addAction(act)


@openham_plugin(
    trigger=["联机"],
    desc="🎮 和朋友联机：聊天 + 一起玩游戏",
    setup=setup_multiplayer,
)
def execute_multiplayer(text, *args, **kwargs):
    if _win is not None:
        _win.show_window()
        return {"type": "result", "content": "✅ 已打开联机窗口"}
    return {"type": "error", "content": "❌ 联机插件未就绪"}
