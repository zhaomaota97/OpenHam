"""AI 对话插件窗口：Monica 风格，带「Bots」（每个 bot 有自己的 system prompt 与会话历史）。

布局（三栏）：
- 最左 Bots 栏：每个 bot 一个头像；点头像切换 bot，点「+」新建 bot（名称 + system prompt），
  右键可编辑/删除。每个 bot 各自维护一份会话历史。
- 会话侧栏：搜索框 + 新建会话 + 当前 bot 下按时间分组（今天/昨天/7 天内/更早）的会话列表。
- 消息区：用户=右侧浅灰气泡；助手=「bot 头像 + bot 名 + 模型标签 + 纯 Markdown 正文」。

其余：流式响应、携带上下文（含 bot 的 system prompt）、持久化；模型沿用全局 AI 配置。
入口：主程序输入框里以 `--` 开头即唤起本窗口（见 plugins/ai_chat.py），无需其它触发词。
"""
import os
import time
import uuid
import json
import datetime
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import (QColor, QPixmap, QPainter, QFont, QIcon, QBrush,
                         QTextCursor, QTextBlockFormat, QTextTable,
                         QTextTableFormat, QTextFrameFormat, QTextLength)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QScrollArea, QPlainTextEdit, QMenu,
    QLineEdit, QTextBrowser, QDialog, QDialogButtonBox,
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


def _norm_session(s: dict) -> dict:
    s.setdefault("id", uuid.uuid4().hex)
    s.setdefault("title", "新对话")
    s.setdefault("created", time.time())
    s.setdefault("messages", [])
    return s


def _make_bot(name: str, system: str, sessions=None) -> dict:
    return {"id": uuid.uuid4().hex, "name": name or "助手",
            "system": system or "", "created": time.time(),
            "sessions": [_norm_session(s) for s in (sessions or [])]}


def _load_store() -> dict:
    """返回 {"bots": [...], "current_bot": id}。兼容旧的「顶层 sessions」格式。"""
    p = _data_path()
    if not os.path.exists(p):
        return {"bots": [_make_bot("Hamster", "")], "current_bot": None}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"bots": [_make_bot("Hamster", "")], "current_bot": None}

    if "bots" not in data:   # 旧格式迁移：把原来的会话塞进默认 bot（Hamster）
        old = data.get("sessions", [])
        return {"bots": [_make_bot("Hamster", "", old)], "current_bot": None}

    bots = data.get("bots", [])
    for b in bots:
        b.setdefault("id", uuid.uuid4().hex)
        b.setdefault("name", "助手")
        b.setdefault("system", "")
        b.setdefault("created", time.time())
        b["sessions"] = [_norm_session(s) for s in b.get("sessions", [])]
    if not bots:
        bots = [_make_bot("Hamster", "")]
    elif bots[0]["name"] == "默认助手":   # 旧默认助手改名为 Hamster
        bots[0]["name"] = "Hamster"
    return {"bots": bots, "current_bot": data.get("current_bot")}


def _save_store(store: dict):
    try:
        with open(_data_path(), "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _time_group(ts: float) -> str:
    try:
        delta = (datetime.date.today()
                 - datetime.date.fromtimestamp(ts or time.time())).days
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
# 克制、低饱和的配色（避免刺眼的纯色），圆角方形头像
_AVA_PALETTE = ["#5b6b8c", "#4a7c6f", "#8c5b6b", "#6b5b8c",
                "#8c7a5b", "#4f7d8a", "#7a8c5b", "#9c6f4a"]
_ava_cache = {}
_SS = 3   # 头像超采样倍率：按物理像素绘制再标 DPR，保证高分屏清晰不糊


def _letter_avatar(name: str, px: int = 34) -> QPixmap:
    name = name.strip() or "?"
    ch = name[:1].upper()
    key = (name, px)
    if key in _ava_cache:
        return _ava_cache[key]
    color = _AVA_PALETTE[(sum(ord(c) for c in name)) % len(_AVA_PALETTE)]
    s = int(px * _SS)
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    r = s * 0.30
    p.drawRoundedRect(0, 0, s, s, r, r)
    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setPixelSize(int(s * 0.42))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, ch)
    p.end()
    pm.setDevicePixelRatio(_SS)
    _ava_cache[key] = pm
    return pm


def _model_label() -> str:
    try:
        return app_config.get("ai_model") or "AI"
    except Exception:
        return "AI"


class _BotDialog(QDialog):
    """新建 / 编辑 bot：名称 + system prompt。"""

    def __init__(self, parent=None, name="", system=""):
        super().__init__(parent)
        self.setWindowTitle("新建 Bot" if not name else "编辑 Bot")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)

        lay.addWidget(self._lbl("名称"))
        self.name_in = QLineEdit(name)
        self.name_in.setPlaceholderText("例如：翻译官、代码助手、营养师…")
        lay.addWidget(self.name_in)

        lay.addSpacing(4)
        lay.addWidget(self._lbl("System Prompt（人设 / 指令，可留空用默认）"))
        self.sys_in = QPlainTextEdit(system)
        self.sys_in.setPlaceholderText(
            "例如：你是一名专业英汉翻译，只输出译文，不加解释。")
        self.sys_in.setFixedHeight(140)
        lay.addWidget(self.sys_in)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _lbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600;")
        return l

    def values(self):
        return self.name_in.text().strip(), self.sys_in.toPlainText().strip()


class _MessageRow(QWidget):
    """一条消息。用户=右侧浅灰气泡；助手=左侧「头像+名称+模型标签+Markdown 正文」。"""

    def __init__(self, role: str, bot_name="Hamster", bot_avatar=None,
                 host=None, parent=None):
        super().__init__(parent)
        self.role = role
        self._raw = ""
        self.host = host
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
            self.actions = self._build_actions()
            rightw = QWidget()
            rightw.setStyleSheet("background: transparent;")
            rv = QVBoxLayout(rightw)
            rv.setContentsMargins(0, 0, 0, 0)
            rv.setSpacing(3)
            rv.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignRight)
            rv.addWidget(self.actions, 0, Qt.AlignmentFlag.AlignRight)
            outer.addStretch(1)
            outer.addWidget(rightw)
        else:
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(6)
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(8)
            avatar = QLabel()
            avatar.setPixmap(bot_avatar if bot_avatar is not None
                             else _letter_avatar(bot_name, 22))
            avatar.setFixedSize(22, 22)
            head.addWidget(avatar)
            name = QLabel(bot_name)
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
            self.actions = self._build_actions()
            col.addWidget(self.actions)
            self.bubble = None
            outer.addLayout(col, 1)

        self.actions.setVisible(False)   # hover 才显示

    def _build_actions(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: transparent;")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)

        def mkbtn(icon_name, tip):
            b = QPushButton()
            b.setIcon(icons.qicon(icon_name, color=theme.TEXT3))
            b.setIconSize(QSize(13, 13))
            b.setFixedSize(26, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; border-radius: 6px; }}"
                f"QPushButton:hover {{ background: {theme.SUBTLE}; }}")
            return b

        self.copy_btn = mkbtn("copy", "复制")
        if self.role == "assistant":
            self.copy_btn.clicked.connect(self._copy_menu)
            self.regen_btn = mkbtn("refresh", "重新生成")
            self.regen_btn.clicked.connect(
                lambda: self.host and self.host._regenerate(self))
            h.addWidget(self.copy_btn)
            h.addWidget(self.regen_btn)
            h.addStretch(1)
        else:
            self.copy_btn.clicked.connect(
                lambda: self.host and self.host._copy_plain(self))
            self.edit_btn = mkbtn("edit", "编辑")
            self.edit_btn.clicked.connect(
                lambda: self.host and self.host._edit_user(self))
            h.addWidget(self.copy_btn)
            h.addWidget(self.edit_btn)
        return bar

    def _copy_menu(self):
        if self.host is None:
            return
        menu = QMenu(self)
        a1 = menu.addAction("复制为 Markdown")
        a2 = menu.addAction("复制为纯文本")
        chosen = menu.exec(self.copy_btn.mapToGlobal(
            self.copy_btn.rect().bottomLeft()))
        if chosen == a1:
            self.host._copy_markdown(self)
        elif chosen == a2:
            self.host._copy_plain(self)

    def enterEvent(self, event):
        self.actions.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.actions.setVisible(False)
        super().leaveEvent(event)

    def set_text(self, text: str):
        self._raw = text
        if self.role == "user":
            self.bubble.setText(text)
        else:
            self.browser.setMarkdown(text)
            self._improve_typography()
            self._style_tables()
            self._fit_height()

    def _improve_typography(self):
        """放宽行距与段间距，让 Markdown 不再挤成一团。"""
        doc = self.browser.document()
        cur = QTextCursor(doc)
        cur.select(QTextCursor.SelectionType.Document)
        bf = QTextBlockFormat()
        bf.setLineHeight(165, 1)   # 1 = ProportionalHeight，约 1.65 倍行距
        bf.setTopMargin(2)
        bf.setBottomMargin(9)
        cur.mergeBlockFormat(bf)

    def _style_tables(self):
        """给 Markdown 表格补上边框/内边距/表头底色（Qt 默认渲染太朴素）。"""
        doc = self.browser.document()
        tables = []
        stack = list(doc.rootFrame().childFrames())
        while stack:
            f = stack.pop()
            if isinstance(f, QTextTable):
                tables.append(f)
            stack.extend(f.childFrames())
        for tbl in tables:
            fmt = QTextTableFormat()
            fmt.setBorder(1)
            fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            fmt.setBorderBrush(QBrush(QColor(theme.BORDER_IN)))
            fmt.setCellPadding(7)
            fmt.setCellSpacing(0)
            try:
                fmt.setBorderCollapse(True)
            except Exception:
                pass
            fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
            tbl.setFormat(fmt)
            # 表头行底色
            for c in range(tbl.columns()):
                cell = tbl.cellAt(0, c)
                cf = cell.format()
                cf.setBackground(QBrush(QColor(theme.SUBTLE)))
                cell.setFormat(cf)

    def set_width(self, content_px: int):
        if self.role == "user":
            self.bubble.setMaximumWidth(max(120, int(content_px * 0.72)))
        else:
            self.browser.setFixedWidth(max(160, content_px))
            self._fit_height()

    def _fit_height(self):
        if self.role != "user" and self.browser is not None:
            doc = self.browser.document()
            doc.setTextWidth(self.browser.viewport().width() or self.browser.width())
            self.browser.setFixedHeight(max(24, int(doc.size().height()) + 6))


class _ChatSignals(QObject):
    chunk = pyqtSignal(int, str)
    done = pyqtSignal(int)
    error = pyqtSignal(int, str)


class AIChatWindow(OpenHamWindowBase):
    """AI 对话主窗口（单例，由插件 setup 创建并复用）。"""

    def __init__(self):
        super().__init__(title="聊天", min_w=940, min_h=600)
        self.resize(1080, 700)

        self.store = _load_store()
        self.bots = self.store["bots"]
        self.cur_bot_id = self.store.get("current_bot") or self.bots[0]["id"]
        if not any(b["id"] == self.cur_bot_id for b in self.bots):
            self.cur_bot_id = self.bots[0]["id"]
        bot = self._cur_bot()
        self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None

        self._rows = []
        self._msgs = []
        self._gen = 0
        self._streaming = False
        self._assistant_row = None
        self._assistant_text = ""
        self._filter = ""

        self._sig = _ChatSignals()
        self._sig.chunk.connect(self._on_chunk)
        self._sig.done.connect(self._on_done)
        self._sig.error.connect(self._on_error)

        self._add_maximize_button()
        self._build_ui()
        self._add_sidebar_toggle()
        self.title_bar.installEventFilter(self)   # 双击标题栏最大化/还原
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    # ── 标题栏：最大化按钮 ────────────────────────────────────────────
    def _add_maximize_button(self):
        self.max_btn = QPushButton()
        self.max_btn.setIcon(icons.qicon("maximize", color=theme.TEXT2))
        self.max_btn.setFixedSize(28, 28)
        self.max_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.max_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.max_btn.setToolTip("最大化 / 还原")
        self.max_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        self.max_btn.clicked.connect(self._toggle_max)
        tb = self.title_bar.layout()
        tb.insertWidget(tb.indexOf(self.pin_btn), self.max_btn)

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
            self.max_btn.setIcon(icons.qicon("maximize", color=theme.TEXT2))
        else:
            self.showMaximized()
            self.max_btn.setIcon(icons.qicon("restore", color=theme.TEXT2))

    # ── 标题栏：折叠/展开会话面板 ─────────────────────────────────────
    def _add_sidebar_toggle(self):
        self.sidebar_btn = QPushButton()
        self.sidebar_btn.setIcon(icons.qicon("panel", color=theme.TEXT2))
        self.sidebar_btn.setFixedSize(28, 28)
        self.sidebar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar_btn.setToolTip("折叠 / 展开会话面板")
        self.sidebar_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        self.sidebar_btn.clicked.connect(self._toggle_sidebar)
        self.header_tools_layout.addWidget(self.sidebar_btn)

    def _toggle_sidebar(self):
        self._sidebar.setVisible(not self._sidebar.isVisible())
        QTimer.singleShot(0, lambda: [m.set_width(self._content_width()) for m in self._msgs])

    # ── 界面骨架 ──────────────────────────────────────────────────────
    def _build_ui(self):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_rail())
        self._sidebar = self._build_sidebar()
        h.addWidget(self._sidebar)
        h.addWidget(self._build_chat(), 1)
        self.content_layout.addWidget(row, 1)

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("botRail")
        rail.setFixedWidth(72)
        rail.setStyleSheet(
            f"#botRail {{ background: {theme.SUBTLE};"
            f" border-right: 1px solid {theme.BORDER}; }}")
        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 12, 0, 12)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # 默认 bot（Hamster）= 顶部 logo 头像，固定在最上方
        self.default_holder = QVBoxLayout()
        self.default_holder.setContentsMargins(0, 0, 0, 0)
        self.default_holder.setSpacing(0)
        dh = QWidget()
        dh.setStyleSheet("background: transparent;")
        dh.setLayout(self.default_holder)
        v.addWidget(dh, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(2)

        # 用户自建 bots 容器（可滚动）
        self.bot_col = QVBoxLayout()
        self.bot_col.setContentsMargins(0, 0, 0, 0)
        self.bot_col.setSpacing(8)
        self.bot_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host.setLayout(self.bot_col)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setStyleSheet("background: transparent;")
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(host)
        v.addWidget(sc, 1)

        add = QPushButton()
        add.setIcon(icons.qicon("add", color=theme.TEXT2))
        add.setIconSize(QSize(18, 18))
        add.setFixedSize(44, 44)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("新建 Bot")
        add.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px dashed {theme.BORDER_IN};"
            f" border-radius: 12px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        add.clicked.connect(self._create_bot)
        v.addWidget(add, 0, Qt.AlignmentFlag.AlignHCenter)
        return rail

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sideBar")
        side.setFixedWidth(244)
        side.setStyleSheet(
            f"#sideBar {{ background: {theme.CARD};"
            f" border-right: 1px solid {theme.BORDER}; }}")
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(10)

        self.bot_title = QLabel("")
        self.bot_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: 700;"
            " background: transparent;")
        v.addWidget(self.bot_title)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索会话")
        self.search.setFixedHeight(36)
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.qicon("search", color=theme.TEXT3),
                              QLineEdit.ActionPosition.LeadingPosition)
        # 等宽聚焦边框 + 固定高度，避免聚焦时被裁剪
        self.search.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 9px;"
            f" padding: 0 8px; font-size: 13px; }}"
            f"QLineEdit:focus {{ border: 1px solid {theme.ACCENT}; }}")
        self.search.textChanged.connect(self._on_search)
        v.addWidget(self.search)

        self.new_btn = QPushButton("  新建会话")
        self.new_btn.setIcon(icons.qicon("add", color=theme.INDIGO))
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.setFixedHeight(38)
        self.new_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.CARD}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 10px;"
            f" font-size: 13px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {theme.INDIGO_SOFT}; border-color: #d8d6fb; }}")
        self.new_btn.clicked.connect(lambda: self._new_session())
        v.addWidget(self.new_btn)

        self.session_list = QListWidget()
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._session_menu)
        self.session_list.itemClicked.connect(self._on_session_clicked)
        self.session_list.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ border-radius: 8px; padding: 8px 9px; color: {theme.TEXT}; }}"
            f"QListWidget::item:hover {{ background: {theme.SUBTLE}; }}"
            f"QListWidget::item:selected {{ background: {theme.SELECT}; color: {theme.TEXT}; }}")
        v.addWidget(self.session_list, 1)
        return side

    def _build_chat(self) -> QWidget:
        right = QWidget()
        right.setObjectName("chatArea")
        right.setStyleSheet(f"#chatArea {{ background: {theme.BG}; }}")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.msg_host = QWidget()
        self.msg_host.setStyleSheet("background: transparent;")
        self.msg_layout = QVBoxLayout(self.msg_host)
        self.msg_layout.setContentsMargins(28, 22, 28, 22)
        self.msg_layout.setSpacing(20)
        self.msg_layout.addStretch(1)
        self.scroll.setWidget(self.msg_host)
        rv.addWidget(self.scroll, 1)

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
        self.input.setPlaceholderText("发消息……（Enter 发送，Shift+Enter 换行）")
        self.input.setFrameShape(QFrame.Shape.NoFrame)
        self.input.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; font-size: 14px; }")
        self.input.setFixedHeight(58)
        self.input.installEventFilter(self)
        cl.addWidget(self.input)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        self.model_pill = QLabel("  " + _model_label())
        self.model_pill.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT2}; background: {theme.SUBTLE};"
            " border-radius: 9px; padding: 3px 10px; font-size: 12px; }}")
        bottom.addWidget(self.model_pill)
        bottom.addStretch(1)
        self.send_btn = QPushButton()
        self.send_btn.setIcon(icons.qicon("send", color="#ffffff"))
        self.send_btn.setIconSize(QSize(17, 17))
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedSize(38, 38)
        self.send_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; border: none; border-radius: 19px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}"
            f"QPushButton:disabled {{ background: {theme.TEXT3}; }}")
        self.send_btn.clicked.connect(self._send)
        bottom.addWidget(self.send_btn)
        cl.addLayout(bottom)
        wl.addWidget(card)
        rv.addWidget(wrap)
        return right

    # ── Bots ──────────────────────────────────────────────────────────
    def _cur_bot(self):
        for b in self.bots:
            if b["id"] == self.cur_bot_id:
                return b
        return self.bots[0]

    def _clear_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _bot_avatar(self, bot, px):
        """默认 bot（Hamster，bots[0]）用 logo 头像；其余用字母头像。"""
        if self.bots and bot["id"] == self.bots[0]["id"]:
            return _brand_pixmap(px)
        return _letter_avatar(bot["name"], px)

    def _make_bot_row(self, bot) -> QWidget:
        active = bot["id"] == self.cur_bot_id
        btn = QPushButton()
        btn.setIcon(QIcon(self._bot_avatar(bot, 40)))
        btn.setIconSize(QSize(40, 40))
        btn.setFixedSize(52, 52)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(bot["name"])
        # 选中=柔和浅底（无描边/无指示条），克制优雅
        btn.setStyleSheet(
            f"QPushButton {{ background: {theme.SELECT if active else 'transparent'};"
            f" border: none; border-radius: 15px; padding: 0; }}"
            f"QPushButton:hover {{ background: {theme.SELECT if active else theme.HOVER}; }}")
        bid = bot["id"]
        btn.clicked.connect(lambda _=False, b=bid: self._select_bot(b))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=bid, w=btn: self._bot_menu(b, w, pos))
        return btn

    def _refresh_bots(self):
        # 默认 bot（Hamster）固定最上
        self._clear_layout(self.default_holder)
        self.default_holder.addWidget(self._make_bot_row(self.bots[0]),
                                      0, Qt.AlignmentFlag.AlignHCenter)
        # 其余用户 bot
        self._clear_layout(self.bot_col)
        for b in self.bots[1:]:
            self.bot_col.addWidget(self._make_bot_row(b), 0, Qt.AlignmentFlag.AlignHCenter)
        self.bot_col.addStretch(1)

    def _select_bot(self, bot_id: str):
        if bot_id == self.cur_bot_id:
            return
        self._gen += 1
        self._set_streaming(False)
        self.cur_bot_id = bot_id
        self.store["current_bot"] = bot_id
        self._filter = ""
        if hasattr(self, "search"):
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        bot = self._cur_bot()
        self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    def _create_bot(self):
        dlg = _BotDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, system = dlg.values()
        if not name:
            name = "新 Bot"
        bot = _make_bot(name, system)
        self.bots.append(bot)
        self.cur_bot_id = bot["id"]
        self.store["current_bot"] = bot["id"]
        self.cur_id = None
        _save_store(self.store)
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    def _bot_menu(self, bot_id: str, anchor: QWidget, pos):
        menu = QMenu(self)
        act_edit = menu.addAction(icons.qicon("edit"), "编辑 Bot")
        act_del = menu.addAction(icons.qicon("delete"), "删除 Bot")
        is_def = bool(self.bots) and bot_id == self.bots[0]["id"]
        if is_def or len(self.bots) <= 1:   # 默认 Hamster 不可删
            act_del.setEnabled(False)
        chosen = menu.exec(anchor.mapToGlobal(pos))
        if chosen == act_edit:
            self._edit_bot(bot_id)
        elif chosen == act_del:
            self._delete_bot(bot_id)

    def _edit_bot(self, bot_id: str):
        bot = next((b for b in self.bots if b["id"] == bot_id), None)
        if not bot:
            return
        dlg = _BotDialog(self, bot["name"], bot["system"])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, system = dlg.values()
        bot["name"] = name or bot["name"]
        bot["system"] = system
        _save_store(self.store)
        self._refresh_bots()
        if bot_id == self.cur_bot_id:
            self.bot_title.setText(bot["name"])
            self._load_current()   # 助手头像/名称随之刷新

    def _delete_bot(self, bot_id: str):
        if len(self.bots) <= 1 or bot_id == self.bots[0]["id"]:   # 默认 Hamster 不可删
            return
        self.bots = [b for b in self.bots if b["id"] != bot_id]
        self.store["bots"] = self.bots
        if self.cur_bot_id == bot_id:
            self._gen += 1
            self._set_streaming(False)
            self.cur_bot_id = self.bots[0]["id"]
            self.store["current_bot"] = self.cur_bot_id
            bot = self._cur_bot()
            self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None
        _save_store(self.store)
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    # ── 会话管理（作用于当前 bot）────────────────────────────────────
    def _sessions(self):
        return self._cur_bot()["sessions"]

    def _cur(self):
        for s in self._sessions():
            if s["id"] == self.cur_id:
                return s
        return None

    def _new_session(self, persist: bool = True):
        cur = self._cur()
        if cur is not None and not cur["messages"]:
            self.input.setFocus()
            return
        s = _norm_session({"title": "新对话", "created": time.time(), "messages": []})
        self._sessions().insert(0, s)
        self.cur_id = s["id"]
        if persist:
            _save_store(self.store)
        self._refresh_session_list()
        self._load_current()
        self.input.setFocus()

    def _on_search(self, text: str):
        self._filter = (text or "").strip().lower()
        self._refresh_session_list()

    def _refresh_session_list(self):
        self.bot_title.setText(self._cur_bot()["name"])
        self.session_list.clear()
        groups = {g: [] for g in _GROUP_ORDER}
        for s in self._sessions():
            if self._filter and self._filter not in (s.get("title") or "").lower():
                continue
            groups[_time_group(s.get("created", 0))].append(s)
        for g in _GROUP_ORDER:
            if not groups[g]:
                continue
            header = QListWidgetItem(g)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            f = header.font()
            f.setPointSize(max(7, f.pointSize() - 1))
            header.setFont(f)
            header.setForeground(QColor(theme.TEXT3))
            self.session_list.addItem(header)
            for s in groups[g]:
                it = QListWidgetItem(s["title"] or "新对话")
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
        bot = self._cur_bot()
        bot["sessions"] = [s for s in bot["sessions"] if s["id"] != sid]
        if self.cur_id == sid:
            self._gen += 1
            self._set_streaming(False)
            self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None
        _save_store(self.store)
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
        bot = self._cur_bot()
        msg = _MessageRow(role, bot_name=bot["name"],
                          bot_avatar=self._bot_avatar(bot, 22), host=self)
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
        if cur is None or not cur["messages"]:
            self._show_empty_hint()
        if cur is not None:
            for m in cur["messages"]:
                self._add_message(m["role"], m["content"])
        self._scroll_to_bottom()

    def _show_empty_hint(self):
        bot = self._cur_bot()
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 60, 0, 0)
        bl.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(self._bot_avatar(bot, 56))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(logo)
        hint = QLabel(f"我是「{bot['name']}」，有什么可以帮你的？")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {theme.TEXT2}; font-size: 16px;"
                           " font-weight: 600; background: transparent;")
        bl.addWidget(hint)
        sub = QLabel("在下方输入开始对话")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {theme.TEXT3}; font-size: 13px; background: transparent;")
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
            s = _norm_session({"title": "新对话", "created": time.time(), "messages": []})
            self._sessions().insert(0, s)
            self.cur_id = s["id"]
            self._refresh_session_list()
            cur = self._cur()
        if not cur["messages"]:
            self._clear_messages()
        self.input.clear()

        cur["messages"].append({"role": "user", "content": text})
        self._add_message("user", text)
        self._maybe_title(cur, text)
        _save_store(self.store)
        self._run_completion()

    def _run_completion(self):
        """基于当前会话已有消息，流式生成一条新的助手回答（供发送/重新生成/编辑后复用）。"""
        cur = self._cur()
        if cur is None:
            return
        self._assistant_text = ""
        self._assistant_row = self._add_message("assistant", "▍")
        self._scroll_to_bottom()

        history = []
        sys_prompt = (self._cur_bot().get("system") or "").strip()
        if sys_prompt:
            history.append({"role": "system", "content": sys_prompt})
        history += [{"role": m["role"], "content": m["content"]}
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

    # ── 消息操作：复制 / 重新生成 / 编辑 ──────────────────────────────
    def _copy_markdown(self, row):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(row._raw or "")

    def _copy_plain(self, row):
        from PyQt6.QtWidgets import QApplication
        if row.role == "assistant" and row.browser is not None:
            QApplication.clipboard().setText(row.browser.toPlainText())
        else:
            QApplication.clipboard().setText(row._raw or "")

    def _regenerate(self, row):
        if self._streaming:
            return
        cur = self._cur()
        if cur is None:
            return
        try:
            i = self._msgs.index(row)
        except ValueError:
            return
        if i >= len(cur["messages"]) or cur["messages"][i]["role"] != "assistant":
            return
        self._gen += 1
        self._set_streaming(False)
        cur["messages"] = cur["messages"][:i]   # 去掉该回答及其后续
        _save_store(self.store)
        self._load_current()
        self._run_completion()

    def _edit_user(self, row):
        if self._streaming:
            return
        cur = self._cur()
        if cur is None:
            return
        try:
            i = self._msgs.index(row)
        except ValueError:
            return
        if i >= len(cur["messages"]) or cur["messages"][i]["role"] != "user":
            return
        from PyQt6.QtWidgets import QInputDialog
        old = cur["messages"][i]["content"]
        new, ok = QInputDialog.getMultiLineText(
            self, "编辑消息", "修改后将丢弃此条之后的对话，并重新生成回答：", old)
        if not ok:
            return
        new = new.strip()
        if not new:
            return
        self._gen += 1
        self._set_streaming(False)
        cur["messages"] = cur["messages"][:i]            # 丢弃此条及其后续
        cur["messages"].append({"role": "user", "content": new})
        if i == 0:                                       # 首条则更新会话标题
            cur["title"] = (new[:18] + "…") if len(new) > 18 else new
        _save_store(self.store)
        self._refresh_session_list()
        self._load_current()
        self._run_completion()

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
            cur["messages"].append({"role": "assistant", "content": self._assistant_text})
            _save_store(self.store)
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
            cur["messages"].append({"role": "assistant", "content": self._assistant_text})
            _save_store(self.store)
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
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False
                self._send()
                return True
        # 双击标题栏：最大化 / 还原
        if obj is self.title_bar and event.type() == QEvent.Type.MouseButtonDblClick:
            self._toggle_max()
            return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self._content_width()
        for m in self._msgs:
            m.set_width(w)

    # ── 外部入口 ──────────────────────────────────────────────────────
    def open(self):
        """供插件调用：无论之前在哪（最小化/被遮挡），都强制置顶到前台并聚焦。"""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        if not self.isVisible():
            self.show_window_centered()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self._force_foreground()
        self.input.setFocus()

    def _force_foreground(self):
        """Win32 AttachThreadInput 强制把本窗口提到最前（绕过 SetForegroundWindow 限制）。"""
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            fg = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg, None)
            cur_tid = kernel32.GetCurrentThreadId()
            attached = False
            if fg_tid and fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, True)
                attached = True
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        except Exception:
            pass

    def send_text(self, text: str, context: dict = None):
        """供 `--` 快捷命令调用：始终走默认 Hamster bot，自动发送。

        context={"q","a"} 时，新开一个会话并预置上一轮一次性问答作为上下文（携带历史）；
        否则复用空会话或新开一个空会话（不带历史）。
        """
        text = (text or "").strip()
        self.open()
        if not text:
            return
        self._gen += 1            # 取消可能在跑的上一条快捷流，避免回答落到新会话
        self._set_streaming(False)
        hb = self.bots[0]                       # 快捷对话固定 Hamster
        self.cur_bot_id = hb["id"]
        self.store["current_bot"] = hb["id"]
        if context and context.get("q") and context.get("a"):
            q = str(context["q"]).strip()
            s = _norm_session({
                "title": (q[:18] + "…") if len(q) > 18 else (q or "新对话"),
                "created": time.time(),
                "messages": [
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": str(context["a"]).strip()},
                ],
            })
            hb["sessions"].insert(0, s)
            self.cur_id = s["id"]
        else:
            empty = next((x for x in hb["sessions"] if not x["messages"]), None)
            if empty:
                self.cur_id = empty["id"]
            else:
                s = _norm_session({"title": "新对话", "created": time.time(), "messages": []})
                hb["sessions"].insert(0, s)
                self.cur_id = s["id"]
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()
        self.input.setPlainText(text)
        QTimer.singleShot(0, self._send)


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
                s = int(px * _SS)
                pm = src.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(_SS)
    except Exception:
        pm = None
    if pm is None:
        pm = icons.qicon("ai").pixmap(QSize(px, px))
    _brand_cache[px] = pm
    return pm
