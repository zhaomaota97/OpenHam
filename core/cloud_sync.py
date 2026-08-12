"""云同步：AI 聊天（ai_chat/sessions.json）与待办（todo/tasks.json）按账号 sub 存到网关。
末次写入生效（last-write-wins）：登录/启动时 pull 覆盖本地，本地改动后 push。
脚本/插件不同步。"""
import json
import os
import threading

import requests

from core import app_config

GATEWAY = "https://gateway.focus.beer"


def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(kind: str):
    if kind == "todo":
        d = os.path.join(_base_dir(), "todo")
    elif kind == "chat":
        d = os.path.join(_base_dir(), "ai_chat")
    else:
        return None
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "tasks.json" if kind == "todo" else "sessions.json")


def _headers():
    t = app_config.get_token()
    return {"Authorization": f"Bearer {t}"} if t else None


def pull(kind: str) -> bool:
    """拉云端该 kind 文档，存在则覆盖本地文件。返回是否用了云端数据。"""
    h = _headers()
    p = _path(kind)
    if not h or not p:
        return False
    try:
        r = requests.get(f"{GATEWAY}/sync/{kind}", headers=h, timeout=10)
        if not r.ok:
            return False
        data = r.json().get("data")
        if data is None:
            return False
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def push(kind: str, data=None) -> None:
    """把本地(或给定) kind 文档推到云端。"""
    h = _headers()
    p = _path(kind)
    if not h or not p:
        return
    try:
        if data is None:
            if not os.path.exists(p):
                return
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        requests.put(f"{GATEWAY}/sync/{kind}", headers={**h, "Content-Type": "application/json"},
                     json=data, timeout=10)
    except Exception:
        pass


def push_async(kind: str, data=None) -> None:
    """后台推送，不阻塞 UI。"""
    threading.Thread(target=push, args=(kind, data), daemon=True).start()


def pull_all() -> dict:
    """登录/启动时把云端数据拉到本地。返回各 kind 是否命中云端。"""
    return {k: pull(k) for k in ("chat", "todo")}
