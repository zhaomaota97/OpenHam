"""OpenHam 中转服务器（relay）——跑在 ECS 上的 WebSocket 房间转发。

职责（保持极简）：
- 建房：服务端生成唯一 6 位房间号并回传（客户端再编成喵咪密码展示）。
- 进房：凭房间号加入，广播成员变动。
- 转发：relay 消息原样转发给房内其他人（聊天/游戏状态/文件分块都走它）。
- 退出/断线：成员移除；房主退出则转移；房间空了即销毁（房间自动过期）。

运行（在 ECS 上）：
    python3 -m pip install websockets
    python3 server.py            # 默认监听 0.0.0.0:9000
注意：需在云控制台「安全组」放行对应端口（默认 9000/TCP）。
"""
import os
import json
import asyncio
import secrets
import logging

import websockets
from websockets.http11 import Response
from websockets.datastructures import Headers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("relay")

HOST = os.environ.get("OPENHAM_RELAY_HOST", "0.0.0.0")
PORT = int(os.environ.get("OPENHAM_RELAY_PORT", "9000"))
MAX_MEMBERS = int(os.environ.get("OPENHAM_ROOM_MAX", "16"))  # 单房间人数硬上限（可配）
ROOM_CODE_LEN = 6       # 房间号位数（与喵咪密码一致）
PROTOCOL_VERSION = 1

rooms: dict[str, "Room"] = {}  # 房间号 -> Room

# 网页玩家（浏览器/手机访问 http://host:port/ 时返回）
_PLAYER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player.html")


def _load_player_html() -> bytes:
    try:
        with open(_PLAYER_PATH, "rb") as f:
            return f.read()
    except Exception:
        return b"<h1>player.html not found</h1>"


async def process_request(connection, request):
    """非 WebSocket 的普通 HTTP 请求 → 返回网页玩家；WS 升级请求放行。"""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    body = _load_player_html()
    headers = Headers([
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ])
    return Response(200, "OK", headers, body)


class Client:
    def __init__(self, ws, name: str | None):
        self.ws = ws
        self.id = secrets.token_hex(4)
        self.name = (name or "玩家")[:20]
        self.room: "Room | None" = None


class Room:
    def __init__(self, code: str, host: Client):
        self.code = code
        self.host_id = host.id
        self.members: dict[str, Client] = {}

    def add(self, c: Client):
        self.members[c.id] = c
        c.room = self

    def remove(self, cid: str):
        self.members.pop(cid, None)


def _new_room_code() -> str:
    """生成一个当前未占用的随机 6 位房间号。"""
    while True:
        code = f"{secrets.randbelow(10 ** ROOM_CODE_LEN):0{ROOM_CODE_LEN}d}"
        if code not in rooms:
            return code


async def _send(ws, obj: dict):
    try:
        await ws.send(json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass


async def _broadcast(room: Room, obj: dict, exclude: str | None = None):
    payload = json.dumps(obj, ensure_ascii=False)
    dead = []
    for cid, c in list(room.members.items()):
        if cid == exclude:
            continue
        try:
            await c.ws.send(payload)
        except Exception:
            dead.append(cid)
    for cid in dead:
        room.remove(cid)


def _members_brief(room: Room) -> list:
    return [{"id": c.id, "name": c.name} for c in room.members.values()]


# ── 消息处理 ────────────────────────────────────────────────────────────

async def handle_create(client: Client, msg: dict):
    if client.room:
        await _send(client.ws, {"type": "error", "code": "already_in_room", "msg": "已在房间内"})
        return
    if msg.get("name"):
        client.name = str(msg["name"])[:20]
    code = _new_room_code()
    room = Room(code, client)
    rooms[code] = room
    room.add(client)
    log.info("建房 %s  host=%s(%s)", code, client.name, client.id)
    await _send(client.ws, {
        "type": "created", "room": code,
        "self_id": client.id, "host_id": room.host_id,
    })


async def handle_join(client: Client, msg: dict):
    if client.room:
        await _send(client.ws, {"type": "error", "code": "already_in_room", "msg": "已在房间内"})
        return
    code = str(msg.get("room", "")).strip()
    room = rooms.get(code)
    if not room:
        await _send(client.ws, {"type": "error", "code": "no_room", "msg": "房间不存在或已关闭"})
        return
    if len(room.members) >= MAX_MEMBERS:
        await _send(client.ws, {"type": "error", "code": "room_full", "msg": "房间已满"})
        return
    if msg.get("name"):
        client.name = str(msg["name"])[:20]
    room.add(client)
    log.info("进房 %s  <- %s(%s)  人数=%d", code, client.name, client.id, len(room.members))
    await _send(client.ws, {
        "type": "joined", "room": code,
        "self_id": client.id, "host_id": room.host_id,
        "members": _members_brief(room),
    })
    await _broadcast(room, {"type": "peer_join", "id": client.id, "name": client.name}, exclude=client.id)


async def handle_relay(client: Client, msg: dict):
    """通用转发：data 原样发给房内其他人；带 to 则单发给指定成员。"""
    room = client.room
    if not room:
        await _send(client.ws, {"type": "error", "code": "not_in_room", "msg": "尚未进入房间"})
        return
    out = {"type": "relay", "from": client.id, "name": client.name, "data": msg.get("data")}
    to = msg.get("to")
    if to:
        target = room.members.get(to)
        if target:
            await _send(target.ws, out)
    else:
        await _broadcast(room, out, exclude=client.id)


async def leave_room(client: Client):
    room = client.room
    if not room:
        return
    room.remove(client.id)
    client.room = None
    log.info("离开 %s  <- %s(%s)", room.code, client.name, client.id)
    if not room.members:
        rooms.pop(room.code, None)
        log.info("房间 %s 已空，销毁", room.code)
        return
    # 房主退出 → 把房主转给剩下的某位
    if client.id == room.host_id:
        room.host_id = next(iter(room.members))
        await _broadcast(room, {"type": "host_changed", "host_id": room.host_id})
    await _broadcast(room, {"type": "peer_leave", "id": client.id})


DISPATCH = {
    "create": handle_create,
    "join": handle_join,
    "relay": handle_relay,
}


async def handler(ws):
    client = Client(ws, None)
    await _send(ws, {"type": "welcome", "server": "openham-relay", "version": PROTOCOL_VERSION})
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                await _send(ws, {"type": "error", "code": "bad_json", "msg": "消息不是合法 JSON"})
                continue
            mtype = msg.get("type")
            if mtype == "leave":
                await leave_room(client)
                continue
            fn = DISPATCH.get(mtype)
            if not fn:
                await _send(ws, {"type": "error", "code": "unknown_type", "msg": f"未知消息类型: {mtype}"})
                continue
            await fn(client, msg)
    except websockets.ConnectionClosed:
        pass
    finally:
        await leave_room(client)


async def main():
    log.info("OpenHam relay 启动于 ws://%s:%d", HOST, PORT)
    async with websockets.serve(handler, HOST, PORT, ping_interval=20, ping_timeout=20,
                                process_request=process_request):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("relay 已停止")
