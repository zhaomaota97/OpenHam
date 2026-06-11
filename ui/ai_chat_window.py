"""AI 对话插件窗口：Monica 风格的聊天界面。

布局（三栏）：
- 最左细图标栏：品牌 logo + Chat（当前）+ 新建会话。
- 会话侧栏：搜索框 + 「新建会话」+ 按时间分组（今天/昨天/7 天内/更早）的会话列表。
- 右侧消息区：用户消息为右侧浅灰气泡；助手消息为「头像 + 名称 + 模型标签 + 纯 Markdown 正文」
  （无气泡，QTextBrowser 原生渲染 Markdown，无需 WebEngine / 第三方库）。

其余：流式响应、携带上下文、会话持久化；模型沿用全局 AI 配置（core.ai_client）。
"""
import os
import time
import uuid
import json
import datetime
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QScrollArea, QPlainTextEdit, QMenu,
    QLineEdit, QTextBrowser,
)

from ui.window_base import OpenHamWindowBase
from ui import icons, theme
from core import app_config
from core.ai_client import call_chat_stream


def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_path() -> str:
    d = os.path.join(_base_dir(), "ai_chat")
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


def _time_group(ts: float) -> str:
    try:
        d_now = datetime.date.today()
        d_ts = datetime.date.fromtimestamp(ts or time.time())
        delta = (d_now - d_ts).days
    except Exception:
        return "更早"
    if delta <= 0:
        return "今天"
    if delta == 1:
        return "昨天"
    if delta <= 7:
        return "7 天内"
    return "更早"


_GROUP_ORDER = ["今天", "昨天", "7 天内", "更早"]


class _MessageRow(QWidget):
    """一条消息。用户=右侧浅灰气泡；助手=左侧「头像+名称+模型标签+Markdown 正文」。"""

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._raw = ""
        self.setStyleSheet("background: transparent;")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if role == "user":
            self.browser = None
            self.bubble = QLabel("")
            self.bubble.setWordWrap(True)
            self.bubble.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self.bubble.setStyleSheet(
                f"QLabel {{ background: {theme.SUBTLE}; color: {theme.TEXT};"
                f" border-radius: 14px; padding: 10px 14px; font-size: 14px; }}")
            outer.addStretch(1)
            outer.addWidget(self.bubble)
        else:
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(7)

            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(8)
            avatar = QLabel()
            pm = _brand_pixmap(22)
            if pm is not None:
                avatar.setPixmap(pm)
            avatar.setFixedSize(22, 22)
            head.addWidget(avatar)
            name = QLabel("OpenHam AI")
            name.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;"
                " background: transparent;")
            head.addWidget(name)
            badge = QLabel(_model_label())
            badge.setStyleSheet(
                f"QLabel {{ color: {theme.INDIGO}; background: {theme.INDIGO_SOFT};"
                " border-radius: 6px; padding: 1px 7px; font-size: 11px; }}")
            head.addWidget(badge)
            head.addStretch(1)
            col.addLayout(head)

            self.browser = QTextBrowser()
            self.browser.setOpenExternalLinks(True)
            self.browser.setFrameShape(QFrame.Shape.NoFrame)
            self.browser.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setStyleSheet(
                "QTextBrowser { background: transparent; border: none;"
                " color: #1d1d1f; font-size: 14px; }")
            self.browser.document().setDefaultStyleSheet(
                "pre, code { background:#f3f3f5; font-family:Consolas,monospace; }"
                "a { color:#6e56cf; }")
            col.addWidget(self.browser)
            self.bubble = None
            outer.addLayout(col, 1)

    def set_text(self, text: str):
        self._raw = text
        if self.role == "user":
            self.bubble.setText(text)
        else:
            self.browser.setMarkdown(text)
            self._fit_height()

    def set_width(self, content_px: int):
        if self.role == "user":
            self.bubble.setMaximumWidth(max(120, int(content_px * 0.72)))
        else:
            self.browser.setFixedWidth(max(160, content_px))
            self._fit_height()

    def _fit_height(self):
        if self.role != "user" and self.browser is not None:
            doc = self.browser.document()
            doc.setTextWidth(self.browser.viewport().width()
                             or self.browser.width())
            h = int(doc.size().height()) + 6
            self.browser.setFixedHeight(max(24, h))


_brand_cache = {}


def _brand_pixmap(px: int):
    if px in _brand_cache:
        return _brand_cache[px]
    pm = None
    try:
        logo = os.path.join(_base_dir(), "logo.png")
        if os.path.exists(logo):
            src = QPixmap(logo)
            if not src.isNull():
                pm = src.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
    except Exception:
        pm = None
    if pm is None:
        pm = icons.qicon("ai").pixmap(QSize(px, px))
    _brand_cache[px] = pm
    return pm


def _model_label() -> str:
    try:
        m = app_config.get("ai_model") or "AI"
    except Exception:
        m = "AI"
    return m


class _ChatSignals(QObject):
    chunk = pyqtSignal(int, str)
    done = pyqtSignal(int)
    error = pyqtSignal(int, str)


class AIChatWindow(OpenHamWindowBase):
    """AI 对话主窗口（单例，由插件 setup 创建并复用）。"""

    def __init__(self):
        super().__init__(title="💬 AI 对话", min_w=900, min_h=580)
        self.resize(1040, 680)

        self.sessions = _load_sessions()
        self.cur_id = self.sessions[0]["id"] if self.sessions else None
        self._rows = []
        self._msgs = []          # 仅 _MessageRow（用于测宽）
        self._gen = 0
        self._streaming = False
        self._assistant_row = None
        self._assistant_text = ""
        self._filter = ""

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

        h.addWidget(self._build_rail())
        h.addWidget(self._build_sidebar())
        h.addWidget(self._build_chat(), 1)

        self.content_layout.addWidget(row, 1)

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setFixedWidth(60)
        rail.setStyleSheet(f"background: {theme.SUBTLE};"
                           f" border-right: 1px solid {theme.BORDER};")
        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 14, 0, 14)
        v.setSpacing(10)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        logo = QLabel()
        pm = _brand_pixmap(30)
        if pm is not None:
            logo.setPixmap(pm)
        logo.setFixedSize(30, 30)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)

        chat_btn = self._rail_btn("chat", "对话", active=True)
        v.addWidget(chat_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        add_btn = self._rail_btn("add", "新建会话")
        add_btn.clicked.connect(lambda: self._new_session())
        v.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        v.addStretch(1)
        return rail

    def _rail_btn(self, icon_name: str, tip: str, active: bool = False) -> QPushButton:
        b = QPushButton()
        b.setIcon(icons.qicon(icon_name, color=(theme.INDIGO if active else theme.TEXT2)))
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(40, 40)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        bg = theme.INDIGO_SOFT if active else "transparent"
        b.setStyleSheet(
            f"QPushButton {{ background: {bg}; border: none; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        return b

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setFixedWidth(244)
        side.setStyleSheet(f"background: {theme.CARD};"
                           f" border-right: 1px solid {theme.BORDER};")
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索会话…")
        self.search.addAction(icons.qicon("search", color=theme.TEXT3),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._on_search)
        v.addWidget(self.search)

        self.new_btn = QPushButton("  新建会话")
        self.new_btn.setIcon(icons.qicon("add", color=theme.INDIGO))
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.setFixedHeight(38)
        self.new_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.CARD}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 10px;"
            f" font-size: 13px; font-weight: 500; text-align: center; }}"
            f"QPushButton:hover {{ background: {theme.INDIGO_SOFT};"
            f" border-color: #d8d6fb; }}")
        self.new_btn.clicked.connect(lambda: self._new_session())
        v.addWidget(self.new_btn)

        recent = QLabel("最近会话")
        recent.setStyleSheet(f"color: {theme.TEXT3}; font-size: 12px;"
                             " font-weight: 600; background: transparent;")
        v.addWidget(recent)

        self.session_list = QListWidget()
        self.session_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._session_menu)
        self.session_list.itemClicked.connect(self._on_session_clicked)
        self.session_list.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ border-radius: 8px; padding: 8px 9px;"
            f" color: {theme.TEXT}; }}"
            f"QListWidget::item:hover {{ background: {theme.SUBTLE}; }}"
            f"QListWidget::item:selected {{ background: {theme.SELECT};"
            f" color: {theme.TEXT}; }}")
        v.addWidget(self.session_list, 1)
        return side

    def _build_chat(self) -> QWidget:
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
        self.msg_layout.setContentsMargins(28, 22, 28, 22)
        self.msg_layout.setSpacing(20)
        self.msg_layout.addStretch(1)
        self.scroll.setWidget(self.msg_host)
        rv.addWidget(self.scroll, 1)

        # 输入卡片
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(28, 6, 28, 18)
        wl.setSpacing(0)

        card = QFrame()
        card.setObjectName("inputCard")
        card.setStyleSheet(
            f"#inputCard {{ background: {theme.CARD};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 16px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 12, 10)
        cl.setSpacing(6)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("给 OpenHam AI 发消息……（Enter 发送，Shift+Enter 换行）")
        self.input.setFrameShape(QFrame.Shape.NoFrame)
        self.input.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none;"
            " font-size: 14px; }")
        self.input.setFixedHeight(58)
        self.input.installEventFilter(self)
        cl.addWidget(self.input)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        model_pill = QLabel("  " + _model_label())
        model_pill.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT2}; background: {theme.SUBTLE};"
            " border-radius: 9px; padding: 3px 10px; font-size: 12px; }}")
        bottom.addWidget(model_pill)
        bottom.addStretch(1)

        self.send_btn = QPushButton()
        self.send_btn.setObjectName("primary")
        self.send_btn.setIcon(icons.qicon("send", color="#ffffff"))
        self.send_btn.setIconSize(QSize(17, 17))
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedSize(38, 38)
        self.send_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; border: none;"
            f" border-radius: 19px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}"
            f"QPushButton:disabled {{ background: {theme.TEXT3}; }}")
        self.send_btn.clicked.connect(self._send)
        bottom.addWidget(self.send_btn)
        cl.addLayout(bottom)

        wl.addWidget(card)
        rv.addWidget(wrap)
        return right

    # ── 会话管理 ──────────────────────────────────────────────────────
    def _cur(self):
        for s in self.sessions:
            if s["id"] == self.cur_id:
                return s
        return None

    def _new_session(self, persist: bool = True):
        cur = self._cur()
        if cur is not None and not cur["messages"]:
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

    def _on_search(self, text: str):
        self._filter = (text or "").strip().lower()
        self._refresh_session_list()

    def _refresh_session_list(self):
        self.session_list.clear()
        groups = {g: [] for g in _GROUP_ORDER}
        for s in self.sessions:
            if self._filter and self._filter not in (s.get("title") or "").lower():
                continue
            groups[_time_group(s.get("created", 0))].append(s)

        for g in _GROUP_ORDER:
            items = groups[g]
            if not items:
                continue
            header = QListWidgetItem(g)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            f = header.font()
            f.setPointSize(max(7, f.pointSize() - 1))
            header.setFont(f)
            header.setForeground(QColor(theme.TEXT3))
            self.session_list.addItem(header)
            for s in items:
                it = QListWidgetItem(icons.qicon("chat"), s["title"] or "新对话")
                it.setData(Qt.ItemDataRole.UserRole, s["id"])
                self.session_list.addItem(it)
                if s["id"] == self.cur_id:
                    self.session_list.setCurrentItem(it)

    def _on_session_clicked(self, item: QListWidgetItem):
        sid = item.data(Qt.ItemDataRole.UserRole)
        if not sid or sid == self.cur_id:
            return
        self._gen += 1
        self._set_streaming(False)
        self.cur_id = sid
        self._load_current()

    def _session_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_del = menu.addAction(icons.qicon("delete"), "删除会话")
        if menu.exec(self.session_list.mapToGlobal(pos)) == act_del:
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
        self._msgs = []

    def _add_message(self, role: str, text: str) -> _MessageRow:
        msg = _MessageRow(role)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, msg)
        self._rows.append(msg)
        self._msgs.append(msg)
        msg.set_width(self._content_width())
        msg.set_text(text)
        return msg

    def _content_width(self) -> int:
        vw = self.scroll.viewport().width() or 700
        return max(200, vw - 56)

    def _load_current(self):
        self._clear_messages()
        cur = self._cur()
        if cur is None:
            return
        if not cur["messages"]:
            self._show_empty_hint()
        for m in cur["messages"]:
            self._add_message(m["role"], m["content"])
        self._scroll_to_bottom()

    def _show_empty_hint(self):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 60, 0, 0)
        bl.setSpacing(12)
        logo = QLabel()
        pm = _brand_pixmap(54)
        if pm is not None:
            logo.setPixmap(pm)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(logo)
        hint = QLabel("有什么可以帮你的？")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {theme.TEXT2}; font-size: 16px;"
                           " font-weight: 600; background: transparent;")
        bl.addWidget(hint)
        sub = QLabel("在下方输入开始对话")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {theme.TEXT3}; font-size: 13px;"
                          " background: transparent;")
        bl.addWidget(sub)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, box)
        self._rows.append(box)

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
        if not cur["messages"]:
            self._clear_messages()
        self.input.clear()

        cur["messages"].append({"role": "user", "content": text})
        self._add_message("user", text)
        self._assistant_text = ""
        self._assistant_row = self._add_message("assistant", "▍")
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
        if gen != self._gen or self._assistant_row is None:
            return
        self._assistant_text += piece
        self._assistant_row.set_text(self._assistant_text + " ▍")
        self._scroll_to_bottom()

    def _on_done(self, gen: int):
        if gen != self._gen:
            return
        if self._assistant_row is not None:
            self._assistant_row.set_text(self._assistant_text)
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
        if self._assistant_row is not None:
            self._assistant_row.set_text(self._assistant_text)
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
        if not on:
            self._assistant_row = None

    # ── 杂项 ──────────────────────────────────────────────────────────
    def _scroll_to_bottom(self):
        def go():
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(0, go)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False
                self._send()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self._content_width()
        for m in self._msgs:
            m.set_width(w)

    def open(self):
        """供插件调用：居中显示并聚焦输入框。"""
        self.show_window_centered()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
