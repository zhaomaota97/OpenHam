"""任务数据层（单一数据源）。

待办窗口（ui/todo_window）和 agent 的 task skill 都坐在这个 store 上读写同一份
todo/tasks.json，schema 完全一致——窗口里加的任务和「说一句话」加的任务无差别。

- 底层函数（_load/_save/_make_task…）原样来自 todo_window，迁来此处共享；
- 高层 API（add_task/list_tasks/complete_task）供 skill 调用。
"""
import os
import re
import json
import time
import uuid
import datetime


# ── 自然语言时间解析（把「明天/后天/下周三/3天后」等解析成 due='YYYY-MM-DD'，并从标题移除）──
_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
             "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}


def _clean_title(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"^[我要去得的地把，,、\s]+", "", t)   # 去掉解析后残留的引导/助词
    t = re.sub(r"[，,、的\s]+$", "", t)
    return t.strip()


def parse_due(title: str):
    """从标题抽相对日期 → (clean_title, due|None)。解析不到则 due=None、标题原样清理。"""
    t = title or ""
    today = datetime.date.today()
    due = None
    for pat, days in (("大后天", 3), ("后天", 2), ("明天", 1), ("明日", 1), ("今天", 0), ("今日", 0)):
        if pat in t:
            due = today + datetime.timedelta(days=days)
            t = t.replace(pat, "", 1)
            break
    if due is None:
        m = re.search(r"(\d+)\s*天后", t)
        if m:
            due = today + datetime.timedelta(days=int(m.group(1)))
            t = t[:m.start()] + t[m.end():]
    if due is None:
        m = re.search(r"(下)?(?:周|星期|礼拜)([一二三四五六天日1-7])", t)
        if m and _WEEKDAYS.get(m.group(2)) is not None:
            wd = _WEEKDAYS[m.group(2)]
            delta = (wd - today.weekday()) % 7
            if m.group(1):            # “下周X”
                delta += 7
            elif delta == 0:          # 光说“周X”且正好今天 → 视为下一个该星期几
                delta = 7
            due = today + datetime.timedelta(days=delta)
            t = t[:m.start()] + t[m.end():]
    return (_clean_title(t) or (title or "").strip()), (due.isoformat() if due else None)


# ── 底层 ────────────────────────────────────────────────────────────
def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_path() -> str:
    d = os.path.join(_base_dir(), "todo")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "tasks.json")


def _now() -> float:
    return time.time()


def _make_sub(title: str) -> dict:
    return {"id": uuid.uuid4().hex, "title": title or "", "done": False}


def _make_task(title: str) -> dict:
    return {"id": uuid.uuid4().hex, "title": title or "", "notes": "",
            "due": None, "done": False, "created": _now(),
            "completed": None, "subtasks": []}


def _make_list(name: str) -> dict:
    return {"id": uuid.uuid4().hex, "name": name or "我的任务",
            "created": _now(), "tasks": [], "sort": "my"}


def _norm_task(t: dict) -> dict:
    t.setdefault("id", uuid.uuid4().hex)
    t.setdefault("title", "")
    t.setdefault("notes", "")
    t.setdefault("due", None)
    t.setdefault("done", False)
    t.setdefault("created", _now())
    t.setdefault("completed", None)
    subs = t.get("subtasks") or []
    t["subtasks"] = [{"id": s.get("id", uuid.uuid4().hex),
                      "title": s.get("title", ""), "done": bool(s.get("done"))}
                     for s in subs]
    return t


def _load() -> dict:
    p = _data_path()
    data = None
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
    if not isinstance(data, dict) or not data.get("lists"):
        data = {"lists": [_make_list("我的任务")], "current": None}
    for lst in data["lists"]:
        lst.setdefault("id", uuid.uuid4().hex)
        lst.setdefault("name", "我的任务")
        lst.setdefault("sort", "my")
        lst["tasks"] = [_norm_task(t) for t in lst.get("tasks", [])]
    ids = [l["id"] for l in data["lists"]]
    if data.get("current") not in ids:
        data["current"] = ids[0]
    return data


def _save(data: dict):
    try:
        with open(_data_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[task_store] 保存失败: {e}")
        return
    # 改动后推到云端（已登录才会真正发送；后台线程不阻塞）
    try:
        from core import cloud_sync
        cloud_sync.push_async("todo", data)
    except Exception:
        pass


# ── 高层 API（供 skill / 外部调用）────────────────────────────────────
def _cur_list(data: dict, list_id: str = None) -> dict:
    lid = list_id or data.get("current")
    return next((l for l in data["lists"] if l["id"] == lid), data["lists"][0])


def add_task(title: str, list_id: str = None) -> dict | None:
    """在指定清单（默认当前清单）新建一条任务，插到首位。
    会从自然语言里解析相对日期（明天/后天/下周三…）写入 due，并清理标题。
    返回该任务（标题为空则 None）。"""
    title = (title or "").strip()
    if not title:
        return None
    clean, due = parse_due(title)
    task = _make_task(clean or title)
    task["due"] = due
    data = _load()
    _cur_list(data, list_id)["tasks"].insert(0, task)
    _save(data)
    return task


def list_tasks(include_done: bool = False, list_id: str = None) -> list:
    """返回当前（或指定）清单的任务列表。默认只看未完成。"""
    data = _load()
    out = []
    for t in _cur_list(data, list_id)["tasks"]:
        if t.get("done") and not include_done:
            continue
        out.append(t)
    return out
