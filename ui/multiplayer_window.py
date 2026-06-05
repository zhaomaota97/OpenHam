"""OpenHam 联机窗口：建房 / 进房 / 聊天。

- 建房：连 relay → create_room → 把房间号编成喵咪密码展示 + 复制。
- 进房：粘贴喵咪密码 → 解码 → join_room。
- 聊天：relay 通用转发通道，data 形如 {"t":"chat","text": "..."}。

relay 连接与 asyncio 细节都封装在 core.relay_client 里，本窗口只连信号、调方法。
"""
import os
import tempfile

from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget,
    QHBoxLayout, QVBoxLayout, QApplication, QFileDialog,
)
from PyQt6.QtCore import Qt

from ui.window_base import OpenHamWindowBase
from core.relay_client import RelayClient
from core import app_config, meow_code, game_package, game_transfer
from core.game_package import GamePackageError


class MultiplayerWindow(OpenHamWindowBase):
    def __init__(self):
        super().__init__(title="联机", shadow_size=0, min_w=560, min_h=480)
        self.title_lbl.setText("联机")

        self.client = RelayClient()
        self._connected = False
        self._pending = None       # 连接成功后要执行的动作
        self._room_meow = ""       # 当前房间的喵咪密码（用于复制）
        # 游戏相关
        self._reasm = game_transfer.Reassembler()
        self._game_win = None
        self._published = None      # (zip_bytes, name) 房主已发布的游戏，用于补发新人

        self._build_content()
        self._wire_client()
        self._set_in_room(False)

    # ── UI ────────────────────────────────────────────────────────────

    def _build_content(self):
        root = QWidget()
        root.setStyleSheet(self._qss())
        v = QVBoxLayout(root)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        # 连接条：昵称（服务器地址固定在内置 ECS，移到设置里管理）
        conn = QHBoxLayout(); conn.setSpacing(8)
        self.nick_input = QLineEdit(self._default_nickname())
        self.nick_input.setPlaceholderText("昵称")
        conn.addWidget(QLabel("昵称"))
        conn.addWidget(self.nick_input, 1)
        v.addLayout(conn)

        # 建房 / 进房
        action = QHBoxLayout(); action.setSpacing(8)
        self.create_btn = QPushButton("建房")
        self.create_btn.setObjectName("primary")
        self.create_btn.clicked.connect(self._on_create)
        self.meow_input = QLineEdit()
        self.meow_input.setPlaceholderText("粘贴房间口令")
        self.join_btn = QPushButton("进房")
        self.join_btn.clicked.connect(self._on_join)
        action.addWidget(self.create_btn)
        action.addWidget(self.meow_input, 1)
        action.addWidget(self.join_btn)
        v.addLayout(action)

        # 状态行：房间喵咪密码 + 复制
        status = QHBoxLayout(); status.setSpacing(8)
        self.status_lbl = QLabel("未进入房间")
        self.status_lbl.setObjectName("status")
        self.status_lbl.setWordWrap(True)
        self.copy_btn = QPushButton("复制")
        self.copy_btn.clicked.connect(self._copy_meow)
        self.copy_btn.hide()
        self.publish_btn = QPushButton("🎮 发布游戏")
        self.publish_btn.clicked.connect(self._on_publish)
        status.addWidget(self.status_lbl, 1)
        status.addWidget(self.publish_btn)
        status.addWidget(self.copy_btn)
        v.addLayout(status)

        # 中部：成员列表 + 聊天记录
        mid = QHBoxLayout(); mid.setSpacing(10)
        self.member_list = QListWidget()
        self.member_list.setObjectName("members")
        self.member_list.setFixedWidth(150)
        self.member_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setObjectName("chat")
        mid.addWidget(self.member_list)
        mid.addWidget(self.chat_log, 1)
        v.addLayout(mid, 1)

        # 底部：输入 + 发送
        bottom = QHBoxLayout(); bottom.setSpacing(8)
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("房内发言")
        self.msg_input.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self._on_send)
        bottom.addWidget(self.msg_input, 1)
        bottom.addWidget(self.send_btn)
        v.addLayout(bottom)

        self.content_layout.addWidget(root)

    # ── 信号接线 ───────────────────────────────────────────────────────

    def _wire_client(self):
        c = self.client
        c.connected.connect(self._on_connected)
        c.disconnected.connect(self._on_disconnected)
        c.created.connect(self._on_created)
        c.joined.connect(self._on_joined)
        c.peer_joined.connect(self._on_peer_joined)
        c.peer_left.connect(self._on_peer_left)
        c.host_changed.connect(lambda _hid: self._refresh_members())
        c.message.connect(self._on_message)
        c.error.connect(self._on_error)

    # ── 动作 ──────────────────────────────────────────────────────────

    def _default_nickname(self) -> str:
        saved = (app_config.get("nickname") or "").strip()
        if saved:
            return saved
        import socket
        return os.environ.get("COMPUTERNAME") or socket.gethostname() or "玩家"

    def _nickname(self) -> str:
        return self.nick_input.text().strip() or self._default_nickname()

    def _ensure_connected_then(self, action):
        """已连接则直接执行；否则先连接，连上后再执行。"""
        app_config.save_settings({"nickname": self.nick_input.text().strip()})
        if self._connected:
            action()
            return
        self._pending = action
        self._system("正在连接服务器…")
        self.client.start(app_config.get("relay_url"))

    def _on_create(self):
        self._ensure_connected_then(lambda: self.client.create_room(self._nickname()))

    def _on_join(self):
        meow = self.meow_input.text().strip()
        if not meow:
            self._system("请先粘贴喵咪密码")
            return
        try:
            room = meow_code.decode(meow)
        except meow_code.MeowCodeError:
            self._system("喵咪密码无法识别，请检查是否复制完整")
            return
        self._ensure_connected_then(lambda: self.client.join_room(room, self._nickname()))

    def _on_send(self):
        text = self.msg_input.text().strip()
        if not text or not self.client.room:
            return
        self.client.send_data({"t": "chat", "text": text})
        self._append(f"我", text, mine=True)
        self.msg_input.clear()

    def _copy_meow(self):
        if self._room_meow:
            QApplication.clipboard().setText(self._room_meow)
            self._system("已复制喵咪密码，发给朋友吧～")

    # ── 客户端信号处理 ─────────────────────────────────────────────────

    def _on_connected(self):
        self._connected = True
        if self._pending:
            act, self._pending = self._pending, None
            act()

    def _on_disconnected(self, reason: str):
        self._connected = False
        self._set_in_room(False)
        self._system(f"已断开：{reason}")

    def _on_created(self, room: str):
        self._room_meow = meow_code.encode(room)
        self.status_lbl.setText(f"房间已创建 ·  {self._room_meow}")
        self.copy_btn.show()
        self._set_in_room(True)
        self._refresh_members()
        self._system("房间已创建，把喵咪密码发给朋友即可一起玩")

    def _on_joined(self, msg: dict):
        self._room_meow = meow_code.encode(msg.get("room", ""))
        self.status_lbl.setText(f"已进入房间 ·  {self._room_meow}")
        self.copy_btn.show()
        self._set_in_room(True)
        self._refresh_members()
        self._system("已进入房间")

    def _on_peer_joined(self, peer: dict):
        self._refresh_members()
        self._system(f"🟢 {peer.get('name')} 加入了房间")
        # 房主：已发布的游戏补发给新加入者
        if self._published and self.client.is_host:
            self._send_game_to(peer.get("id"))
            self._system(f"📦 正在把游戏补发给 {peer.get('name')}")

    def _on_peer_left(self, _pid: str):
        self._refresh_members()
        self._system("🔴 有人离开了房间")

    def _on_message(self, m: dict):
        data = m.get("data") or {}
        if not isinstance(data, dict):
            return
        t = data.get("t")
        if t == "chat":
            self._append(m.get("name", "?"), str(data.get("text", "")))
        elif t == "game_meta":
            self._reasm.on_meta(data)
            self._system(f"📥 正在接收游戏「{data.get('name')}」…")
        elif t == "game_chunk":
            done = self._reasm.on_chunk(data)
            if done is not None:
                self._receive_game(done, self._reasm.name)
        elif t == "game_msg":
            if self._game_win is not None:
                payload = data.get("payload")
                if isinstance(payload, dict):
                    payload = {**payload, "_from": m.get("name")}
                self._game_win.deliver(payload)

    # ── 游戏：发布 / 接收 / 打开 ────────────────────────────────────────

    def _on_publish(self):
        if not self.client.room:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择游戏目录（含 index.html）")
        if not folder:
            return
        try:
            data = game_package.pack_folder(folder)
        except GamePackageError as e:
            self._system(f"⚠️ 打包失败：{e}")
            return
        name = game_package.package_name(data)
        self._published = (data, name)
        self._system(f"🎮 已发布游戏「{name}」（{len(data)//1024} KB），正在分发…")
        self._send_game_to(None)          # 广播给房内所有人
        self._open_game(data, name)       # 房主自己也打开

    def _send_game_to(self, target):
        if not self._published:
            return
        data, name = self._published
        for msg in game_transfer.chunk_package(data, name):
            self.client.send_data(msg, to=target)

    def _receive_game(self, data: bytes, name: str):
        self._system(f"✅ 游戏「{name}」接收完成，正在打开…")
        self._open_game(data, name)

    def _open_game(self, data: bytes, name: str):
        try:
            dest = tempfile.mkdtemp(prefix="openham_game_")
            info = game_package.extract_package(data, dest)
        except GamePackageError as e:
            self._system(f"⚠️ 解包失败：{e}")
            return
        if self._game_win is None:
            from ui.game_window import GameWindow  # 延迟加载，避免未玩游戏时也载入 WebEngine
            self._game_win = GameWindow(self._on_game_send)
        self._game_win.load_game(
            info["entry_path"], self.client.self_id or "", self.client.is_host, info["name"]
        )
        self._game_win.show_window_centered()
        self._game_win.raise_()

    def _on_game_send(self, payload):
        """游戏 JS 发来的操作 → 经 relay 广播给房间其他人。"""
        self.client.send_data({"t": "game_msg", "payload": payload})

    def _on_error(self, code: str, msg: str):
        self._system(f"⚠️ {msg}（{code}）")

    # ── 辅助 ──────────────────────────────────────────────────────────

    def _refresh_members(self):
        self.member_list.clear()
        for cid, name in self.client.members.items():
            label = name
            if cid == self.client.self_id:
                label += "（我）"
            if cid == self.client.host_id:
                label = "👑 " + label
            self.member_list.addItem(label)

    def _set_in_room(self, in_room: bool):
        self.msg_input.setEnabled(in_room)
        self.send_btn.setEnabled(in_room)
        self.publish_btn.setEnabled(in_room)
        self.create_btn.setEnabled(not in_room)
        self.join_btn.setEnabled(not in_room)
        self.meow_input.setEnabled(not in_room)
        if not in_room:
            self.copy_btn.hide()
            self.member_list.clear()
            self._published = None
            self._reasm.reset()

    def _append(self, name: str, text: str, mine: bool = False):
        color = "#c9b173" if mine else "#9fd0c0"
        self.chat_log.append(
            f'<span style="color:{color};font-weight:bold;">{name}</span>'
            f'<span style="color:#d8cfb8;">：{text}</span>'
        )

    def _system(self, text: str):
        self.chat_log.append(f'<span style="color:#6f6a55;">— {text} —</span>')

    # ── 生命周期 ───────────────────────────────────────────────────────

    def show_window(self):
        if not self.nick_input.text().strip():
            self.nick_input.setText(self._default_nickname())
        self.show_window_centered()
        self.raise_()
        self.activateWindow()

    def hide_window(self):
        # 关窗即退出房间、断开连接
        try:
            self.client.leave()
            self.client.stop()
        except Exception:
            pass
        self._connected = False
        super().hide_window()

    def _qss(self) -> str:
        return """
            QWidget { background: transparent; }
            QLabel { color: #a99b7c; font-size: 12px; }
            QLabel#status { color: #c09030; font-size: 13px; font-weight: bold; }
            QLineEdit {
                background: rgba(21,18,13,0.92); color: #e6dcc2;
                border: 1px solid #4a3f2a; border-radius: 6px; padding: 7px 9px;
            }
            QLineEdit:focus { border-color: #c08c1e; }
            QLineEdit:disabled { color: #6f6552; }
            QTextEdit#chat {
                background: rgba(21,18,13,0.92); color: #d8cfb8;
                border: 1px solid #4a3f2a; border-radius: 8px; padding: 8px;
                font-size: 13px;
            }
            QListWidget#members {
                background: rgba(28,25,18,0.85); color: #d8cfb8;
                border: 1px solid #4a3f2a; border-radius: 8px; padding: 4px;
                font-size: 13px;
            }
            QListWidget#members::item { padding: 4px 6px; border-radius: 4px; }
            QPushButton {
                background: rgba(192,140,30,0.10); color: #e6dcc2;
                border: 1px solid #4a3f2a; border-radius: 6px; padding: 7px 14px;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(192,140,30,0.20); }
            QPushButton#primary { background: #c08c1e; color: #1c1a14; font-weight: bold; border: none; }
            QPushButton#primary:hover { background: #d39c28; }
            QPushButton:disabled { color: #6f6552; background: rgba(192,140,30,0.05); }
        """
