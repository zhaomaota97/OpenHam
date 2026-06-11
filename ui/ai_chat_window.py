"""AI 对话插件窗口：常规聊天软件式界面（参考 Monica）。

特性：
- 左侧会话列表，可新建 / 切换 / 删除会话；会话历史持久化到磁盘。
- 右侧消息流：用户消息为深色气泡、助手消息用 QTextBrowser 原生渲染 Markdown
  （代码块/列表/表格等），无需 WebEngine 或第三方 markdown 库。
- 流式响应：逐片段追加并实时重渲染当前助手气泡。
- 携带上下文：每次发送都把整段会话历史传给模型。
- 模型沿用全局 AI 配置（core.ai_client / user_settings.json 中的 Key 与模型）。
"""
import os
import json
import time
import uuid
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QScrollArea, QPlainTextEdit, QMenu,
    QSizePolicy, QTextBrowser,
)

from ui.window_base import OpenHamWindowBase
from ui import icons, theme
from core.ai_client import call_chat_stream


def _data_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "ai_chat")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "sessions.json")


def _load_sessions() -> list:
    p = _data_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        sessions = data.get("sessions", [])
        # 兼容性兜底：补全字段
        for s in sessions:
            s.setdefault("id", uuid.uuid4().hex)
            s.setdefault("title", "新对话")
            s.setdefault("created", time.time())
            s.setdefault("messages", [])
        return sessions
    except Exception:
        return []


def _save_sessions(sessions: list):
    p = _data_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"sessions": sessions}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class _Bubble(QFrame):
    """单条消息气泡。用户=深色纯文本标签；助手=浅色 Markdown 渲染。"""

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._raw = ""
        self.setObjectName("bubble")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)

        if role == "user":
            self.label = QLabel("")
            self.label.setWordWrap(True)
            self.label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self.label.setStyleSheet("color: #ffffff; background: transparent;"
                                     " font-size: 13px; border: none;")
            lay.addWidget(self.label)
            self.setStyleSheet(
                f"#bubble {{ background: {theme.ACCENT}; border-radius: 12px; }}")
            self.browser = None
        else:
            self.browser = QTextBrowser()
            self.browser.setOpenExternalLinks(True)
            self.browser.setFrameShape(QFrame.Shape.NoFrame)
            self.browser.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setStyleSheet(
                "QTextBrowser { background: transparent; border: none;"
                " color: #1d1d1f; font-size: 13px; }")
            lay.addWidget(self.browser)
            self.setStyleSheet(
                f"#bubble {{ background: {theme.SUBTLE};"
                f" border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
            self.label = None

    def set_text(self, text: str):
        self._raw = text
        if self.role == "user":
            self.label.setText(text)
        else:
            self.browser.setMarkdown(text)
            self._fit_height()

    def set_width(self, px: int):
        if px < 80:
            px = 80
        if self.role == "user":
            self.label.setMaximumWidth(px)
        else:
            self.browser.setFixedWidth(px)
            self._fit_height()

    def _fit_height(self):
        if self.role != "user" and self.browser is not None:
            doc = self.browser.document()
            doc.setTextWidth(self.browser.viewport().width()
                             or self.browser.width())
            h = int(doc.size().height()) + 6
            self.browser.setFixedHeight(max(24, h))


class _ChatSignals(QObject):
    chunk = pyqtSignal(int, str)   # (gen, piece)
    done = pyqtSignal(int)
    error = pyqtSignal(int, str)


class AIChatWindow(OpenHamWindowBase):
    """AI 对话主窗口（单例，由插件 setup 创建并复用）。"""

    def __init__(self):
        super().__init__(title="💬 AI 对话", min_w=860, min_h=560)
        self.resize(980, 640)

        self.sessions = _load_sessions()
        self.cur_id = self.sessions[0]["id"] if self.sessions else None
        self._bubbles = []           # 当前会话渲染中的 _Bubble 列表
        self._rows = []              # 每条消息对应的行容器（用于整行销毁）
        self._gen = 0                # 流式请求代号，用于取消过期请求
        self._streaming = False
        self._assistant_bubble = None
        self._assistant_text = ""

        self._sig = _ChatSignals()
        self._sig.chunk.connect(self._on_chunk)
        self._sig.done.connect(self._on_done)
        self._sig.error.connect(self._on_error)

        self._build_ui()

        if not self.sessions:
            self._new_session(persist=False)
        else:
            self._refresh_session_list()
            self._load_current()

    # ── 界面 ──────────────────────────────────────────────────────────
    def _build_ui(self):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # 左侧栏
        side = QWidget()
        side.setFixedWidth(232)
        side.setStyleSheet(f"background: {theme.CARD};"
                           f" border-right: 1px solid {theme.BORDER};")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 12, 12, 12)
        sv.setSpacing(10)

        self.new_btn = QPushButton("  新建会话")
        self.new_btn.setObjectName("primary")
        self.new_btn.setIcon(icons.qicon("add", color="#ffffff"))
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(lambda: self._new_session())
        sv.addWidget(self.new_btn)

        self.session_list = QListWidget()
        self.session_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._session_menu)
        self.session_list.itemClicked.connect(self._on_session_clicked)
        sv.addWidget(self.session_list, 1)
        h.addWidget(side)

        # 右侧聊天区
        right = QWidget()
        right.setStyleSheet(f"background: {theme.BG};")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.msg_host = QWidget()
        self.msg_host.setStyleSheet("background: transparent;")
        self.msg_layout = QVBoxLayout(self.msg_host)
        self.msg_layout.setContentsMargins(22, 20, 22, 20)
        self.msg_layout.setSpacing(14)
        self.msg_layout.addStretch(1)
        self.scroll.setWidget(self.msg_host)
        rv.addWidget(self.scroll, 1)

        # 输入区
        bar = QWidget()
        bar.setStyleSheet(f"background: {theme.CARD};"
                          f" border-top: 1px solid {theme.BORDER};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 14, 18, 16)
        bl.setSpacing(10)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("输入消息，Enter 发送，Shift+Enter 换行…")
        self.input.setFixedHeight(54)
        self.input.installEventFilter(self)
        bl.addWidget(self.input, 1)

        self.send_btn = QPushButton("  发送")
        self.send_btn.setObjectName("primary")
        self.send_btn.setIcon(icons.qicon("send", color="#ffffff"))
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedHeight(54)
        self.send_btn.clicked.connect(self._send)
        bl.addWidget(self.send_btn)
        rv.addWidget(bar)

        h.addWidget(right, 1)
        self.content_layout.addWidget(row, 1)

    # ── 会话管理 ──────────────────────────────────────────────────────
    def _cur(self) -> dict | None:
        for s in self.sessions:
            if s["id"] == self.cur_id:
                return s
        return None

    def _new_session(self, persist: bool = True):
        cur = self._cur()
        # 当前会话还空着就别再开新的，直接复用
        if cur is not None and not cur["messages"]:
            self.session_list.setFocus()
            self.input.setFocus()
            return
        s = {"id": uuid.uuid4().hex, "title": "新对话",
             "created": time.time(), "messages": []}
        self.sessions.insert(0, s)
        self.cur_id = s["id"]
        if persist:
            _save_sessions(self.sessions)
        self._refresh_session_list()
        self._load_current()
        self.input.setFocus()

    def _refresh_session_list(self):
        self.session_list.clear()
        for s in self.sessions:
            it = QListWidgetItem(icons.qicon("chat"), s["title"] or "新对话")
            it.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.session_list.addItem(it)
            if s["id"] == self.cur_id:
                self.session_list.setCurrentItem(it)

    def _on_session_clicked(self, item: QListWidgetItem):
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid == self.cur_id:
            return
        self._gen += 1            # 取消可能在跑的流
        self._set_streaming(False)
        self.cur_id = sid
        self._load_current()

    def _session_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if item is None:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_del = menu.addAction(icons.qicon("delete"), "删除会话")
        chosen = menu.exec(self.session_list.mapToGlobal(pos))
        if chosen == act_del:
            self._delete_session(sid)

    def _delete_session(self, sid: str):
        self.sessions = [s for s in self.sessions if s["id"] != sid]
        if self.cur_id == sid:
            self._gen += 1
            self._set_streaming(False)
            self.cur_id = self.sessions[0]["id"] if self.sessions else None
        _save_sessions(self.sessions)
        if not self.sessions:
            self._new_session(persist=True)
            return
        self._refresh_session_list()
        self._load_current()

    # ── 消息渲染 ──────────────────────────────────────────────────────
    def _clear_messages(self):
        for w in self._rows:
            w.setParent(None)
            w.deleteLater()
        self._rows = []
        self._bubbles = []

    def _add_bubble(self, role: str, text: str) -> _Bubble:
        bubble = _Bubble(role)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        # 插在末尾 stretch 之前
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, wrap)
        self._rows.append(wrap)
        self._bubbles.append(bubble)
        bubble.set_width(self._bubble_width(role))
        bubble.set_text(text)
        return bubble

    def _bubble_width(self, role: str) -> int:
        vw = self.scroll.viewport().width() or 700
        avail = vw - 44  # 减去左右内边距
        return int(avail * (0.74 if role == "assistant" else 0.66))

    def _load_current(self):
        self._clear_messages()
        cur = self._cur()
        if cur is None:
            return
        if not cur["messages"]:
            self._show_empty_hint()
        for m in cur["messages"]:
            self._add_bubble(m["role"], m["content"])
        self._scroll_to_bottom()

    def _show_empty_hint(self):
        # 空会话的居中提示
        hint = QLabel("有什么可以帮你的？\n\n直接在下方输入开始对话吧")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {theme.TEXT3}; font-size: 14px;"
                           " background: transparent;")
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wl = QVBoxLayout(wrap)
        wl.addWidget(hint)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, wrap)
        self._rows.append(wrap)   # 纳入统一清理，但不入 _bubbles（无需测宽）

    # ── 发送 / 流式 ───────────────────────────────────────────────────
    def _send(self):
        if self._streaming:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        cur = self._cur()
        if cur is None:
            self._new_session()
            cur = self._cur()
        # 首条消息：清掉空提示
        if not cur["messages"]:
            self._clear_messages()
        self.input.clear()

        cur["messages"].append({"role": "user", "content": text})
        self._add_bubble("user", text)
        self._assistant_text = ""
        self._assistant_bubble = self._add_bubble("assistant", "▍")
        self._scroll_to_bottom()
        self._maybe_title(cur, text)
        _save_sessions(self.sessions)

        history = [{"role": m["role"], "content": m["content"]}
                   for m in cur["messages"]]
        self._gen += 1
        gen = self._gen
        self._set_streaming(True)

        def work():
            try:
                for piece in call_chat_stream(history):
                    if gen != self._gen:
                        return
                    self._sig.chunk.emit(gen, piece)
                if gen == self._gen:
                    self._sig.done.emit(gen)
            except Exception as e:
                if gen == self._gen:
                    self._sig.error.emit(gen, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_chunk(self, gen: int, piece: str):
        if gen != self._gen or self._assistant_bubble is None:
            return
        self._assistant_text += piece
        self._assistant_bubble.set_text(self._assistant_text + " ▍")
        self._scroll_to_bottom()

    def _on_done(self, gen: int):
        if gen != self._gen:
            return
        if self._assistant_bubble is not None:
            self._assistant_bubble.set_text(self._assistant_text)
        cur = self._cur()
        if cur is not None:
            cur["messages"].append(
                {"role": "assistant", "content": self._assistant_text})
            _save_sessions(self.sessions)
        self._set_streaming(False)
        self._scroll_to_bottom()

    def _on_error(self, gen: int, msg: str):
        if gen != self._gen:
            return
        self._assistant_text += f"\n\n❌ {msg}"
        if self._assistant_bubble is not None:
            self._assistant_bubble.set_text(self._assistant_text)
        cur = self._cur()
        if cur is not None:
            cur["messages"].append(
                {"role": "assistant", "content": self._assistant_text})
            _save_sessions(self.sessions)
        self._set_streaming(False)

    def _maybe_title(self, session: dict, first_user_text: str):
        if session["title"] and session["title"] != "新对话":
            return
        t = first_user_text.strip().replace("\n", " ")
        session["title"] = (t[:18] + "…") if len(t) > 18 else t or "新对话"
        self._refresh_session_list()

    def _set_streaming(self, on: bool):
        self._streaming = on
        self.send_btn.setEnabled(not on)
        self.send_btn.setText("  回复中…" if on else "  发送")
        if not on:
            self._assistant_bubble = None

    # ── 杂项 ──────────────────────────────────────────────────────────
    def _scroll_to_bottom(self):
        def go():
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(0, go)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False  # 换行
                self._send()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for b in self._bubbles:
            b.set_width(self._bubble_width(b.role))

    def open(self):
        """供插件调用：居中显示并聚焦输入框。"""
        self.show_window_centered()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
