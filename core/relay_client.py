"""OpenHam 联机客户端：连接 ECS 上的 relay，封装建房/进房/收发。

把 asyncio 的 websockets 跑在后台线程里，对外暴露 Qt 信号（线程安全，
自动派发回 UI 线程）。UI 只需连信号、调方法，无需关心 asyncio。

注意：本类只负责"传输"，房间号用裸 6 位数字。喵咪密码的编/解码由 UI 层
（core.meow_code）处理：建房后把 created 的房间号 encode 展示；进房前把
用户粘贴的喵串 decode 成数字再传进来。
"""
import json
import asyncio
import threading

import websockets
from PyQt6.QtCore import QObject, pyqtSignal

from core.logging_setup import get_logger

log = get_logger("relay_client")


class RelayClient(QObject):
    # 连接生命周期
    connected = pyqtSignal()
    disconnected = pyqtSignal(str)        # reason
    # 房间
    created = pyqtSignal(str)             # 房间号（裸 6 位）
    joined = pyqtSignal(dict)             # {room, self_id, host_id, members}
    peer_joined = pyqtSignal(dict)        # {id, name}
    peer_left = pyqtSignal(str)           # id
    host_changed = pyqtSignal(str)        # host_id
    # 数据
    message = pyqtSignal(dict)            # {from, name, data}
    error = pyqtSignal(str, str)          # code, msg

    def __init__(self):
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._thread: threading.Thread | None = None
        self._url: str | None = None
        self._running = False
        # 会话状态（供 UI 查询）
        self.self_id: str | None = None
        self.room: str | None = None
        self.host_id: str | None = None
        self.members: dict[str, str] = {}   # id -> name

    @property
    def is_host(self) -> bool:
        return self.self_id is not None and self.self_id == self.host_id

    # ── 生命周期（UI 线程调用）──────────────────────────────────────────

    def start(self, url: str):
        """连接到 relay，例如 ws://1.2.3.4:9000"""
        if self._running:
            return
        self._url = url
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        loop, ws = self._loop, self._ws
        if loop is None:
            return
        if ws is not None:
            # 优雅关闭：关掉 ws 后 async for 自然结束，run_until_complete 正常返回，
            # 避免硬停循环把未执行的发送协程掐断
            asyncio.run_coroutine_threadsafe(ws.close(), loop)
        elif loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            log.exception("relay 客户端线程异常: %s", e)
        finally:
            try:
                self._loop.close()
            finally:
                self._loop = None

    async def _connect_and_listen(self):
        try:
            async with websockets.connect(self._url, open_timeout=8, ping_interval=20) as ws:
                self._ws = ws
                log.info("已连接 relay: %s", self._url)
                self.connected.emit()
                async for raw in ws:
                    self._dispatch(raw)
        except Exception as e:
            log.warning("relay 连接失败/中断: %s", e)
            self.error.emit("connect_failed", str(e))
        finally:
            self._ws = None
            self._reset_session()
            self.disconnected.emit("连接已关闭")

    def _reset_session(self):
        self.self_id = self.room = self.host_id = None
        self.members = {}

    def _dispatch(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        t = msg.get("type")
        if t == "welcome":
            return
        if t == "created":
            self.self_id = msg.get("self_id")
            self.room = msg.get("room")
            self.host_id = msg.get("host_id")
            self.members = {self.self_id: "我"}
            self.created.emit(self.room)
        elif t == "joined":
            self.self_id = msg.get("self_id")
            self.room = msg.get("room")
            self.host_id = msg.get("host_id")
            self.members = {m["id"]: m["name"] for m in msg.get("members", [])}
            self.joined.emit(msg)
        elif t == "peer_join":
            self.members[msg.get("id")] = msg.get("name")
            self.peer_joined.emit({"id": msg.get("id"), "name": msg.get("name")})
        elif t == "peer_leave":
            self.members.pop(msg.get("id"), None)
            self.peer_left.emit(msg.get("id"))
        elif t == "host_changed":
            self.host_id = msg.get("host_id")
            self.host_changed.emit(self.host_id)
        elif t == "relay":
            self.message.emit(msg)
        elif t == "error":
            self.error.emit(msg.get("code", ""), msg.get("msg", ""))

    # ── 发送（UI 线程调用，转交到 asyncio 线程执行）──────────────────────

    def _send(self, obj: dict):
        loop, ws = self._loop, self._ws
        if not loop or not ws:
            log.warning("尚未连接，丢弃消息: %s", obj.get("type"))
            return
        data = json.dumps(obj, ensure_ascii=False)
        asyncio.run_coroutine_threadsafe(ws.send(data), loop)

    def create_room(self, name: str = "玩家"):
        self._send({"type": "create", "name": name})

    def join_room(self, room: str, name: str = "玩家"):
        """room 为裸 6 位房间号（喵咪密码请先在 UI 层 decode）。"""
        self._send({"type": "join", "room": room, "name": name})

    def send_data(self, data, to: str | None = None):
        """转发任意数据给房内其他人（聊天/游戏状态/文件分块都走这里）。"""
        msg = {"type": "relay", "data": data}
        if to:
            msg["to"] = to
        self._send(msg)

    def leave(self):
        self._send({"type": "leave"})
