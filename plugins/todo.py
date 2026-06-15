"""任务插件：Google Tasks 风格的待办清单窗口。

入口：主程序输入框里以 `++` 开头唤起（无其它触发词）。
- `++`        → 仅打开窗口
- `++买牛奶`   → 打开窗口并在当前清单新建一条「买牛奶」

窗口本体见 ui/todo_window.TodoWindow；插件只负责单例创建与唤起/转发。
"""
from core.plugin_manager import openham_plugin

_window = None   # 单例窗口


def setup_todo(api):
    """插件加载时预创建任务窗口（运行在 GUI 主线程）。"""
    global _window
    try:
        from ui.todo_window import TodoWindow
        _window = TodoWindow()
    except Exception as e:
        print(f"[todo] 窗口预创建失败: {e}")
        _window = None
    # 注册「打开任务」能力：main.py 据此在托盘菜单加「任务」项（仅插件启用时）
    api.register_handler("open_todo", _tray_open_todo)


def _tray_open_todo():
    try:
        _ensure_window().open()
    except Exception as e:
        print(f"[todo] 打开任务失败: {e}")


def _ensure_window():
    global _window
    if _window is None:
        from ui.todo_window import TodoWindow
        _window = TodoWindow()
    return _window


def match_plusplus(text: str) -> bool:
    """以 `++` 开头即触发。"""
    return text.strip().startswith("++")


@openham_plugin(
    match=match_plusplus,
    desc="任务（++ 前缀唤起 / 清单 / 子任务 / 到期日 / 拖拽排序）",
    setup=setup_todo,
)
def execute_todo(text: str):
    try:
        win = _ensure_window()
    except Exception as e:
        return {"type": "error", "content": f"❌ 无法打开任务：{e}"}
    title = text.strip()[2:].strip()   # 去掉前导 ++
    if title:
        win.add_quick(title)
        preview = title if len(title) <= 16 else title[:16] + "…"
        return {"type": "result", "content": f"✅ 已添加任务：{preview}"}
    win.open()
    return {"type": "result", "content": "✅ 已打开任务"}
