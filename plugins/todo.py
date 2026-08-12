"""任务插件：Google Tasks 风格的待办清单窗口。

入口：主程序输入框里以 `++` 开头唤起（无其它触发词）。
- `++`        → 仅打开窗口
- `++买牛奶`   → 打开窗口并在当前清单新建一条「买牛奶」

窗口本体见 ui/todo_window.TodoWindow；插件只负责单例创建与唤起/转发。
"""
from core.plugin_manager import openham_plugin
from core.skills import Skill, register_skill
from core import task_store

_window = None   # 单例窗口


# ── Layer 2 技能：任务能力注册成 skill，供 agent 路由调用（与窗口共享同一数据源）──
def _skill_add_task(arg: str) -> str:
    t = task_store.add_task(arg)
    if not t:
        return "（任务标题为空，没添加）"
    due = t.get("due")
    return f"✅ 已添加待办事项：{t['title']}" + (f"（截止 {due}）" if due else "")


def _skill_list_tasks(arg: str) -> str:
    tasks = task_store.list_tasks()
    if not tasks:
        return "📋 当前没有未完成的任务"
    lines = [f"📋 未完成任务（{len(tasks)}）："] + [f"· {t['title']}" for t in tasks]
    return "\n".join(lines)


register_skill(Skill(
    name="add_task",
    when_to_use="用户想新增/记录一条待办任务时。例：『记一下买牛奶』『提醒我明天交报告』『加个任务：联系客户』。",
    arg_hint="要新增的任务（去掉『记一下/提醒我』之类引导词，但要保留时间词如『明天/后天/下周三/3天后』，系统会自动解析成截止日期）",
    mutating=True,
    handler=_skill_add_task,
))
register_skill(Skill(
    name="list_tasks",
    when_to_use="用户想查看/询问自己有哪些待办任务时。例：『我有哪些任务』『今天要做什么』『看下待办』。",
    arg_hint="无需参数",
    mutating=False,
    handler=_skill_list_tasks,
))


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
    desc="待办清单",
    tray_label="待办清单",
    tray_open="open_todo",
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
