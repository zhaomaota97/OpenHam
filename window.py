from PyQt6.QtWidgets import (QWidget, QLineEdit, QLabel, QVBoxLayout,
                             QHBoxLayout, QApplication,
                             QGraphicsDropShadowEffect, QFrame,
                             QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem,
                             QPushButton, QHeaderView,
                             QScrollArea, QCheckBox, QStackedWidget,
                             QGridLayout, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QEvent
from PyQt6.QtGui import QKeyEvent, QColor, QPainter, QFont, QPixmap
import ctypes
import os
from executor import evaluate_expr, preview

MAX_LENGTH = 200  # AI 模式下允许输入更长的内容
_SHADOW    = 24          # 阴影溢出留边
_CARD_W    = 640         # 卡片宽度
_WIN_W     = _CARD_W + _SHADOW * 2


def _win_force_foreground(hwnd: int):
    """
    Windows 专用：通过 AttachThreadInput 绕过系统限制，
    强制将指定窗口提到前台并赋予键盘焦点。
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()
    attached = False
    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, True)
        attached = True
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if attached:
        user32.AttachThreadInput(cur_tid, fg_tid, False)


class PomodoroOverlay(QWidget):
    """屏幕右下角半透明、展击穿透的番茄钟倒计时层。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(160, 52)
        self._text = ""
        self._reposition()

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 24,
                  screen.bottom() - self.height() - 24)

    def update_text(self, text: str):
        self._text = text
        self.update()

    def paintEvent(self, event):
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 背景圆角矩形
        p.setBrush(QColor(20, 18, 12, 185))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 10, 10)
        # 文字
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("#e8d89a"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


_GL_SHADOW = 10
_GL_CARD_W = 740


class _BranchMultiSelect(QWidget):
    """
    Ant Design 风格分支多选器。
    选中项显示为可删除标签；点击控件或箭头展开/收起下拉列表；支持实时搜索过滤。
    """
    selection_changed = pyqtSignal()

    _CSS_BOX = ("QWidget#msBox{background:#1a1810;"
                "border:1px solid rgba(192,140,30,0.30);border-radius:6px;}")
    _CSS_BOX_FOCUS = ("QWidget#msBox{background:#1a1810;"
                      "border:1px solid rgba(192,140,30,0.70);border-radius:6px;}")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all: list = []
        self._sel: set = set()
        self._open = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._build()

    # ── construction ──────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # selector box（展示 tags + 搜索输入）
        self._box = QWidget()
        self._box.setObjectName("msBox")
        self._box.setStyleSheet(self._CSS_BOX)
        self._box.setMinimumHeight(38)
        self._box.setCursor(Qt.CursorShape.IBeamCursor)
        bar = QHBoxLayout(self._box)
        bar.setContentsMargins(8, 4, 6, 4)
        bar.setSpacing(4)

        self._tags_w = QWidget()
        self._tags_w.setStyleSheet("background:transparent;")
        self._tags_layout = QHBoxLayout(self._tags_w)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        bar.addWidget(self._tags_w, 1)

        self._input = QLineEdit()
        self._input.setPlaceholderText("搜索并选择分支…")
        self._input.setStyleSheet(
            "QLineEdit{background:transparent;border:none;"
            "color:#ede5d0;font-size:13px;min-width:60px;}"
        )
        self._input.setFixedHeight(26)
        self._input.textChanged.connect(self._on_input)
        self._input.installEventFilter(self)
        # 输入框紧跟在标签之后，最后放 stretch
        self._tags_layout.addWidget(self._input)
        self._tags_layout.addStretch()

        arrow = QPushButton("▾")
        arrow.setFixedSize(20, 20)
        arrow.setFlat(True)
        arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        arrow.setStyleSheet(
            "QPushButton{color:#8a7040;background:transparent;border:none;font-size:12px;}"
        )
        arrow.clicked.connect(lambda: self._set_open(not self._open))
        bar.addWidget(arrow)
        root.addWidget(self._box)

        # 下拉列表
        self._dropdown = QFrame()
        self._dropdown.setObjectName("msDropdown")
        self._dropdown.setStyleSheet(
            "QFrame#msDropdown{background:#1c1a14;"
            "border:1px solid rgba(192,140,30,0.28);"
            "border-top:none;border-radius:0 0 6px 6px;}"
        )
        ddl = QVBoxLayout(self._dropdown)
        ddl.setContentsMargins(0, 0, 0, 0)
        ddl.setSpacing(0)
        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget{background:transparent;border:none;
                color:#d8cfb8;font-size:13px;outline:none;}
            QListWidget::item{padding:6px 14px;}
            QListWidget::item:hover{background:rgba(192,140,30,0.12);}
        """)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._list.itemClicked.connect(self._toggle_item)
        ddl.addWidget(self._list)
        self._dropdown.hide()
        root.addWidget(self._dropdown)

    # ── public API ────────────────────────────────────────────────────────

    def set_options(self, options: list, pre_selected: set | None = None):
        self._all = list(options)
        self._sel = (set(pre_selected) & set(options)) if pre_selected else set()
        self._input.clear()
        self._refresh_list(self._all)
        self._refresh_tags()
        self._set_open(True)

    def get_selected(self) -> set:
        return set(self._sel)

    def clear(self):
        self._all = []
        self._sel = set()
        self._set_open(False)
        self._input.clear()
        self._list.clear()
        self._refresh_tags()

    # ── internals ─────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.MouseButtonPress:
            self._set_open(True)
        return False

    def _set_open(self, val: bool):
        self._open = val
        self._dropdown.setVisible(val)
        self._box.setStyleSheet(self._CSS_BOX_FOCUS if val else self._CSS_BOX)
        # 展开时竖向 Expanding 撑满剩余空间，收起时恢复 Preferred
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding if val else QSizePolicy.Policy.Preferred,
        )
        if val:
            self._input.setFocus()

    def _on_input(self, text: str):
        if not self._open:
            self._set_open(True)
        q = text.strip().lower()
        self._refresh_list([b for b in self._all if q in b.lower()] if q else self._all)

    def _toggle_item(self, item):
        b = item.data(Qt.ItemDataRole.UserRole)
        if b in self._sel:
            self._sel.discard(b)
        else:
            self._sel.add(b)
        self._redraw_item(item)
        self._refresh_tags()
        self.selection_changed.emit()

    def _refresh_list(self, options: list):
        self._list.clear()
        for b in options:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, b)
            it.setText(("✓  " if b in self._sel else "    ") + b)
            it.setForeground(QColor("#c09030" if b in self._sel else "#d8cfb8"))
            self._list.addItem(it)

    def _redraw_item(self, item):
        b = item.data(Qt.ItemDataRole.UserRole)
        item.setText(("✓  " if b in self._sel else "    ") + b)
        item.setForeground(QColor("#c09030" if b in self._sel else "#d8cfb8"))

    def _refresh_tags(self):
        # 保留末尾两项：_input（count-2）+ stretch（count-1）
        while self._tags_layout.count() > 2:
            it = self._tags_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, b in enumerate(sorted(self._sel)):
            self._tags_layout.insertWidget(i, self._make_tag(b))
        self._input.setPlaceholderText("" if self._sel else "搜索并选择分支…")

    def _make_tag(self, branch: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            "QWidget{background:rgba(192,140,30,0.18);"
            "border:1px solid rgba(192,140,30,0.38);border-radius:3px;}"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(5, 1, 2, 1)
        h.setSpacing(1)
        lbl = QLabel(branch)
        lbl.setStyleSheet("color:#c09030;font-size:11px;background:transparent;border:none;")
        h.addWidget(lbl)
        x = QPushButton("×")
        x.setFixedSize(14, 14)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        x.setFlat(True)
        x.setStyleSheet(
            "QPushButton{color:#7a6a4a;background:transparent;border:none;"
            "font-size:12px;padding:0;} QPushButton:hover{color:#ff9050;}"
        )
        x.clicked.connect(lambda checked, b=branch: self._remove_tag(b))
        h.addWidget(x)
        return w

    def _remove_tag(self, branch: str):
        self._sel.discard(branch)
        self._refresh_tags()
        q = self._input.text().strip().lower()
        self._refresh_list([b for b in self._all if q in b.lower()] if q else self._all)
        self.selection_changed.emit()


class _AdaptiveStack(QStackedWidget):
    """sizeHint 跟随当前页变化，使父窗口能自适应高度。"""
    def sizeHint(self):
        cur = self.currentWidget()
        return cur.sizeHint() if cur else super().sizeHint()

    def minimumSizeHint(self):
        cur = self.currentWidget()
        return cur.minimumSizeHint() if cur else super().minimumSizeHint()


class GitLabOverlay(QWidget):
    """
    右上角浮层：查看关注仓库最新提交（视图模式）+ 管理关注列表（编辑模式）。
    可拖拽、可关闭、30秒 ETag 轮询自动刷新。
    """

    # ── 供 main.py 连接的信号 ────────────────────────────────────────────
    refresh_requested      = pyqtSignal()            # 手动刷新
    edit_mode_opened       = pyqtSignal()            # 切换到编辑模式（触发填充列表）
    branch_fetch_requested = pyqtSignal(str)         # 请求获取分支列表：url
    repo_add_requested     = pyqtSignal(str, str, list)  # url, name, branches
    repo_remove_requested  = pyqtSignal(str)         # url
    webhook_toggle         = pyqtSignal(bool)        # enabled

    _COL_BRANCH = 80
    _COL_SHA    = 90
    _COL_DATE   = 105
    _COL_AUTHOR = 140
    _ROW_H      = 34
    _HDR_H      = 36

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(_GL_CARD_W + _GL_SHADOW * 2)
        self._view_widgets: list = []
        self._drag_pos = None
        self._has_been_shown = False
        self._pending_url: str = ""
        self._pending_current_branches: list = []
        self._build_ui()
        self._reposition()

    # ── UI 构建 ──────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_GL_SHADOW, _GL_SHADOW, _GL_SHADOW, _GL_SHADOW)
        outer.setSpacing(0)

        self._card = QWidget()
        self._card.setObjectName("glCard")
        self._card.setStyleSheet("""
            #glCard {
                background-color: #1e1c14;
                border-radius: 10px;
                border: 1px solid rgba(192, 140, 30, 0.32);
            }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setXOffset(0)
        shadow.setYOffset(10)
        shadow.setColor(QColor(0, 0, 0, 210))
        self._card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._build_title_bar())
        card_layout.addWidget(self._build_stack())
        outer.addWidget(self._card)

    def _build_title_bar(self) -> QWidget:
        self._title_bar = QWidget()
        self._title_bar.setObjectName("glTitleBar")
        self._title_bar.setStyleSheet("""
            #glTitleBar {
                background-color: #272416;
                border-radius: 10px 10px 0 0;
                border-bottom: 1px solid rgba(192, 140, 30, 0.22);
            }
        """)
        self._title_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        tb = QHBoxLayout(self._title_bar)
        tb.setContentsMargins(16, 9, 12, 9)
        tb.setSpacing(0)

        self._title_label = QLabel("📦  仓库最新提交")
        self._title_label.setStyleSheet(
            "color: #c09030; font-size: 15px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        tb.addWidget(self._title_label)
        tb.addSpacing(4)

        # 刷新按钮紧跟标题（视图模式显示）
        self._refresh_btn = self._icon_btn("↻", "#8a7a5a", "刷新")
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        tb.addWidget(self._refresh_btn)
        tb.addStretch()

        # 视图模式专属
        self._edit_btn = self._icon_btn("⚙", "#8a7a5a", "管理关注仓库")
        self._edit_btn.clicked.connect(self.switch_to_edit)

        # 编辑模式专属
        self._done_btn = self._icon_btn("←", "#5a9a5a", "完成，返回查看")
        self._done_btn.hide()
        self._done_btn.clicked.connect(self.switch_to_view)

        # 始终显示
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #7a6a4a;
                font-size: 16px; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: rgba(180, 50, 30, 0.60); color: #fff; }
        """)
        close_btn.clicked.connect(self.hide)

        for btn in (self._edit_btn, self._done_btn, close_btn):
            tb.addWidget(btn)
            tb.addSpacing(2)
        return self._title_bar

    def _build_stack(self) -> _AdaptiveStack:
        self._stack = _AdaptiveStack()
        self._stack.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._build_view_page())   # index 0
        self._stack.addWidget(self._build_edit_page())   # index 1
        return self._stack

    def _build_view_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        self._view_layout = QVBoxLayout(page)
        self._view_layout.setContentsMargins(14, 12, 14, 14)
        self._view_layout.setSpacing(10)
        self._loading_label = QLabel("  正在获取提交信息…")
        self._loading_label.setStyleSheet(
            "color: #8a7040; font-size: 14px; padding: 12px 4px;"
            " background: transparent; border: none;"
        )
        self._view_layout.addWidget(self._loading_label)
        return page

    def _build_edit_page(self) -> QWidget:
        """编辑页：整体可滚动，Webhook 固定在底部。"""
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 可滚动主体 ─────────────────────────────────────────────────
        self._edit_scroll = QScrollArea()
        self._edit_scroll.setWidgetResizable(True)
        self._edit_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._edit_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
            QScrollBar::handle:vertical {
                background: rgba(192, 140, 30, 0.28); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        ep = QVBoxLayout(content)
        ep.setContentsMargins(14, 12, 14, 14)
        ep.setSpacing(10)

        # ── 当前关注列表（直接展开，无内嵌滚动）──────────────────────
        ep.addWidget(self._section_lbl("当前关注仓库"))
        self._repos_container = QWidget()
        self._repos_container.setStyleSheet("background: transparent;")
        self._repos_layout = QVBoxLayout(self._repos_container)
        self._repos_layout.setContentsMargins(0, 2, 0, 2)
        self._repos_layout.setSpacing(5)
        self._repos_layout.addStretch()
        ep.addWidget(self._repos_container)

        ep.addWidget(self._sep_line())

        # ── 添加 / 编辑仓库分支 ────────────────────────────────────────
        ep.addWidget(self._section_lbl("添加 / 编辑仓库分支"))
        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("粘贴 GitLab 仓库 URL…")
        self._url_input.setStyleSheet("""
            QLineEdit {
                background: #1a1810; color: #ede5d0;
                border: 1px solid rgba(192, 140, 30, 0.28);
                border-radius: 5px; font-size: 13px; padding: 5px 10px;
            }
            QLineEdit:focus { border-color: rgba(192, 140, 30, 0.65); }
        """)
        self._url_input.returnPressed.connect(self._on_fetch_clicked)
        url_row.addWidget(self._url_input)

        self._fetch_btn = QPushButton("获取分支")
        self._fetch_btn.setFixedWidth(82)
        self._fetch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fetch_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fetch_btn.setStyleSheet("""
            QPushButton {
                background: rgba(192, 140, 30, 0.16); color: #c09030;
                font-size: 12px; border: 1px solid rgba(192, 140, 30, 0.33);
                border-radius: 5px; padding: 5px;
            }
            QPushButton:hover { background: rgba(192, 140, 30, 0.28); }
            QPushButton:disabled { color: #5a4020; border-color: rgba(192,140,30,0.12); }
        """)
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        url_row.addWidget(self._fetch_btn)
        ep.addLayout(url_row)

        # ── Ant Design 风格分支多选 ────────────────────────────────────
        self._branch_select = _BranchMultiSelect()
        self._branch_select.selection_changed.connect(
            lambda: self._add_btn.setEnabled(bool(self._branch_select.get_selected()))
        )
        self._branch_select.hide()
        ep.addWidget(self._branch_select)

        self._fetch_status = QLabel("")
        self._fetch_status.setStyleSheet(
            "color: #c05050; font-size: 12px; background: transparent; border: none; padding: 2px;"
        )
        self._fetch_status.hide()
        ep.addWidget(self._fetch_status)

        self._add_btn = QPushButton("✚  添加到关注列表")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet("""
            QPushButton {
                background: rgba(70, 140, 70, 0.18); color: #50a850;
                font-size: 13px; border: 1px solid rgba(70, 140, 70, 0.35);
                border-radius: 5px; padding: 6px;
            }
            QPushButton:hover:enabled { background: rgba(70, 140, 70, 0.30); }
            QPushButton:disabled { color: #3a5a3a; border-color: rgba(70,140,70,0.12); }
        """)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._add_btn.hide()
        ep.addWidget(self._add_btn)
        ep.addStretch()

        self._edit_scroll.setWidget(content)
        outer.addWidget(self._edit_scroll, 1)

        # ── Webhook 底部固定栏 ─────────────────────────────────────────
        footer = QWidget()
        footer.setStyleSheet("""
            QWidget {
                background: rgba(26, 24, 12, 0.90);
                border-top: 1px solid rgba(192, 140, 30, 0.14);
            }
        """)
        wh_row = QHBoxLayout(footer)
        wh_row.setContentsMargins(14, 6, 14, 8)
        wh_row.setSpacing(8)
        wh_lbl = QLabel("Webhook:")
        wh_lbl.setStyleSheet("color: #5a6858; font-size: 11px; background: transparent; border: none;")
        self._wh_btn = QPushButton("● OFF")
        self._wh_btn.setFixedWidth(62)
        self._wh_btn.setCheckable(True)
        self._wh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._wh_btn.setStyleSheet(self._toggle_ss(False))
        self._wh_btn.clicked.connect(self._on_webhook_toggle)
        self._wh_info = QLabel("开启后将地址填入 GitLab → Settings → Webhooks")
        self._wh_info.setStyleSheet(
            "color: #4a6060; font-size: 10px; background: transparent; border: none;"
        )
        self._wh_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        wh_row.addWidget(wh_lbl)
        wh_row.addWidget(self._wh_btn)
        wh_row.addWidget(self._wh_info, 1)
        outer.addWidget(footer)
        return page

    # ── 小工具 ────────────────────────────────────────────────────────────

    def _icon_btn(self, text: str, color: str, tip: str = "") -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(30, 30)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tip:
            btn.setToolTip(tip)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                border-radius: 5px; font-size: 18px; color: {color};
            }}
            QPushButton:hover {{ background: rgba(192, 140, 30, 0.22); }}
        """)
        return btn

    @staticmethod
    def _section_lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #7a6a40; font-size: 11px; font-weight: bold; "
            "background: transparent; border: none; padding: 1px 0;"
        )
        return lbl

    @staticmethod
    def _sep_line() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            "background: rgba(192, 140, 30, 0.10); max-height: 1px; border: none; margin: 2px 0;"
        )
        return sep

    @staticmethod
    def _toggle_ss(on: bool) -> str:
        if on:
            return ("QPushButton { background: rgba(50,140,80,0.25); color: #50c870; "
                    "border: 1px solid rgba(50,140,80,0.50); border-radius: 5px; "
                    "font-size: 11px; font-weight: bold; padding: 4px; }")
        return ("QPushButton { background: rgba(80,60,40,0.25); color: #7a6a4a; "
                "border: 1px solid rgba(80,60,40,0.40); border-radius: 5px; "
                "font-size: 11px; padding: 4px; }")

    # ── 视图模式 ──────────────────────────────────────────────────────────

    def show_loading(self):
        """显示加载中，弹出浮层（首次弹出时定位右上角，之后保留用户拖拽位置）。"""
        self._title_label.setText("📦  仓库最新提交  ·  获取中…")
        self._loading_label.show()
        self.adjustSize()
        if not self._has_been_shown:
            self._reposition()
        self.show()
        self.raise_()

    def update_data(self, repos: list):
        """用结构化数据刷新视图表格。"""
        self._clear_view()
        self._loading_label.hide()
        self._title_label.setText("📦  仓库最新提交")
        for repo_data in repos:
            # 引导信息（无仓库时的友好提示，不用红色）
            if repo_data.get("info"):
                guide = QLabel(f"  {repo_data['info']}")
                guide.setStyleSheet(
                    "color: #6a7a5a; font-size: 13px; padding: 20px 6px;"
                    " background: transparent; border: none;"
                )
                self._view_layout.addWidget(guide)
                self._view_widgets.append(guide)
                continue
            name  = repo_data.get("repo", "")
            error = repo_data.get("error")
            if name:
                lbl = QLabel(f"  {name}")
                lbl.setStyleSheet(
                    "color: #c09030; font-size: 14px; font-weight: bold; "
                    "padding: 2px; background: transparent; border: none;"
                )
                self._view_layout.addWidget(lbl)
                self._view_widgets.append(lbl)
            if error:
                err = QLabel(f"  ⚠  {error}")
                err.setStyleSheet(
                    "color: #c05050; font-size: 13px; padding: 4px 6px;"
                    " background: transparent; border: none;"
                )
                self._view_layout.addWidget(err)
                self._view_widgets.append(err)
            elif name:
                tbl = self._make_table(repo_data.get("branches", []))
                self._view_layout.addWidget(tbl)
                self._view_widgets.append(tbl)
        self.adjustSize()
        if not self.isVisible():
            self.show()
            self.raise_()

    def _clear_view(self):
        for w in self._view_widgets:
            self._view_layout.removeWidget(w)
            w.deleteLater()
        self._view_widgets.clear()

    def _make_table(self, branches: list) -> QTableWidget:
        HEADERS = ["分支", "Hash", "日期", "作者", "提交信息"]
        tbl = QTableWidget(len(branches), len(HEADERS))
        tbl.setHorizontalHeaderLabels(HEADERS)
        tbl.verticalHeader().hide()
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tbl.setAlternatingRowColors(True)
        tbl.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tbl.setStyleSheet("""
            QTableWidget {
                background-color: #1c1a14; alternate-background-color: #222016;
                color: #d8cfb8; font-size: 14px;
                border: 1px solid rgba(192, 140, 30, 0.20);
                border-radius: 6px; gridline-color: rgba(192, 140, 30, 0.12);
            }
            QHeaderView::section {
                background-color: #272416; color: #c09030;
                font-size: 13px; font-weight: bold; border: none;
                border-right: 1px solid rgba(192, 140, 30, 0.15);
                border-bottom: 1px solid rgba(192, 140, 30, 0.25);
                padding: 5px 10px;
            }
        """)
        hdr = tbl.horizontalHeader()
        tbl.setColumnWidth(0, self._COL_BRANCH)
        tbl.setColumnWidth(1, self._COL_SHA)
        tbl.setColumnWidth(2, self._COL_DATE)
        tbl.setColumnWidth(3, self._COL_AUTHOR)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for row, bd in enumerate(branches):
            tbl.setRowHeight(row, self._ROW_H)
            bi = QTableWidgetItem(bd.get("branch", ""))
            bi.setForeground(QColor("#c09030"))
            bi.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(row, 0, bi)
            if bd.get("error"):
                ei = QTableWidgetItem(f"⚠  {bd['error']}")
                ei.setForeground(QColor("#c05050"))
                tbl.setItem(row, 1, ei)
                tbl.setSpan(row, 1, 1, 4)
            else:
                for col, key in enumerate(["sha", "date", "author", "message"], start=1):
                    item = QTableWidgetItem(bd.get(key, ""))
                    align = Qt.AlignmentFlag.AlignCenter if col < 3 else Qt.AlignmentFlag.AlignLeft
                    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                    tbl.setItem(row, col, item)
        tbl.setFixedHeight(self._HDR_H + len(branches) * self._ROW_H + 2)
        return tbl

    # ── 编辑模式 ──────────────────────────────────────────────────────────

    def switch_to_edit(self):
        self._title_label.setText("✏️  管理关注仓库")
        self._edit_btn.hide()
        self._refresh_btn.hide()
        self._done_btn.show()
        # 编辑页至少占视口高度的 80%（减去标题栏和底部Webhook栏）
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        title_h = self._title_bar.sizeHint().height()
        footer_h = 42
        self._edit_scroll.setMinimumHeight(max(200, int(screen_h * 0.80) - title_h - footer_h))
        self._stack.setCurrentIndex(1)
        self.adjustSize()
        self.edit_mode_opened.emit()

    def switch_to_view(self):
        self._title_label.setText("📦  仓库最新提交")
        self._done_btn.hide()
        self._edit_btn.show()
        self._refresh_btn.show()
        self._edit_scroll.setMinimumHeight(0)
        self._stack.setCurrentIndex(0)
        self.adjustSize()
        self.refresh_requested.emit()

    def load_edit_repos(self, repos: list, webhook_enabled: bool, webhook_url: str):
        """刷新编辑页的仓库列表和 Webhook 状态。"""
        # 清空旧行（保留末尾 stretch）
        while self._repos_layout.count() > 1:
            item = self._repos_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if repos:
            for repo in repos:
                self._repos_layout.insertWidget(
                    self._repos_layout.count() - 1, self._make_repo_row(repo)
                )
        else:
            empty = QLabel("  暂无关注仓库")
            empty.setStyleSheet(
                "color: #6a5a3a; font-size: 13px; background: transparent; border: none; padding: 6px;"
            )
            self._repos_layout.insertWidget(0, empty)
        # Webhook
        self._wh_btn.setChecked(webhook_enabled)
        self._wh_btn.setText("● ON" if webhook_enabled else "● OFF")
        self._wh_btn.setStyleSheet(self._toggle_ss(webhook_enabled))
        self._wh_info.setText(
            f"已启用，将此地址填入 GitLab → Settings → Webhooks：\n{webhook_url}"
            if webhook_enabled else
            "开启后在 GitLab 仓库 Settings → Webhooks 填入地址"
        )
        self.adjustSize()

    def _make_repo_row(self, repo: dict) -> QWidget:
        url      = repo.get("url", "")
        name     = repo.get("name", url.rsplit("/", 1)[-1])
        branches = list(repo.get("branches", []))
        row = QWidget()
        row.setStyleSheet("""
            QWidget {
                background: rgba(30, 28, 20, 0.70);
                border: 1px solid rgba(192, 140, 30, 0.14);
                border-radius: 5px;
            }
        """)
        vbox = QVBoxLayout(row)
        vbox.setContentsMargins(10, 6, 6, 6)
        vbox.setSpacing(4)

        # -- 第一行: 仓库名 + 编辑按鈕 + 删除按鈕 --
        top = QHBoxLayout()
        top.setSpacing(4)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            "color: #d8cfb8; font-size: 13px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        top.addWidget(name_lbl)
        top.addStretch()

        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(22, 22)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        edit_btn.setToolTip("编辑关注分支")
        edit_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #6a7a8a;
                font-size: 13px; border: none; border-radius: 3px; }
            QPushButton:hover { background: rgba(88, 130, 160, 0.35); color: #aac8e0; }
        """)
        edit_btn.clicked.connect(
            lambda checked, u=url, b=list(branches): self._start_edit_repo(u, b)
        )
        top.addWidget(edit_btn)

        del_repo_btn = QPushButton("×")
        del_repo_btn.setFixedSize(22, 22)
        del_repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_repo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        del_repo_btn.setToolTip("移除该仓库")
        del_repo_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #6a4040;
                font-size: 16px; border: none; border-radius: 3px; }
            QPushButton:hover { background: rgba(180, 50, 30, 0.50); color: #fff; }
        """)
        del_repo_btn.clicked.connect(lambda checked, u=url: self.repo_remove_requested.emit(u))
        top.addWidget(del_repo_btn)
        vbox.addLayout(top)

        # -- 第二行: 可删除的分支标签 --
        if branches:
            tags_row = QHBoxLayout()
            tags_row.setSpacing(5)
            tags_row.setContentsMargins(0, 0, 0, 0)
            for b in branches:
                tags_row.addWidget(self._make_branch_tag(b, url, name, branches))
            tags_row.addStretch()
            vbox.addLayout(tags_row)
        return row

    def _make_branch_tag(self, branch: str, url: str, repo_name: str, all_branches: list) -> QWidget:
        """单个可删除的分支标签 widget。"""
        w = QWidget()
        w.setStyleSheet(
            "QWidget { background: rgba(88,130,150,0.14); "
            "border: 1px solid rgba(88,130,150,0.28); border-radius: 3px; }"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(5, 1, 2, 1)
        h.setSpacing(1)
        lbl = QLabel(branch)
        lbl.setStyleSheet("color: #88aab8; font-size: 11px; background: transparent; border: none;")
        h.addWidget(lbl)
        x_btn = QPushButton("×")
        x_btn.setFixedSize(14, 14)
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        x_btn.setFlat(True)
        x_btn.setStyleSheet("""
            QPushButton { color: #7a6a5a; background: transparent;
                font-size: 12px; border: none; padding: 0; }
            QPushButton:hover { color: #ff7070; }
        """)
        x_btn.clicked.connect(
            lambda checked, removed=branch: self.repo_add_requested.emit(
                url, repo_name, [b for b in all_branches if b != removed]
            )
        )
        h.addWidget(x_btn)
        return w

    def show_branch_choices(self, url: str, result):
        """result 为分支名列表或错误字符串，在获取完成后由 main.py 调用。"""
        self._fetch_btn.setText("获取分支")
        self._fetch_btn.setEnabled(True)

        if isinstance(result, str):
            self._fetch_status.setText(f"❌  {result}")
            self._fetch_status.show()
            self._branch_select.clear()
            self._add_btn.hide()
            self.adjustSize()
            return

        self._fetch_status.hide()
        self._branch_select.set_options(list(result), set(self._pending_current_branches))
        self._branch_select.show()
        self._add_btn.show()
        self._add_btn.setText(
            "✔  更新关注分支" if self._pending_current_branches else "✚  添加到关注列表"
        )
        self._add_btn.setEnabled(bool(self._branch_select.get_selected()))
        self.adjustSize()

    def _start_edit_repo(self, url: str, current_branches: list):
        """点击已有仓库的 ✎ 按钮，进入编辑分支流程。"""
        self._pending_url = url
        self._pending_current_branches = list(current_branches)
        self._url_input.setText(url)
        self._fetch_btn.setText("获取中…")
        self._fetch_btn.setEnabled(False)
        self._fetch_status.hide()
        self._branch_select.clear()
        self._add_btn.hide()
        self.branch_fetch_requested.emit(url)

    def _on_fetch_clicked(self):
        url = self._url_input.text().strip()
        if not url:
            return
        self._pending_url = url
        self._pending_current_branches = []
        self._fetch_btn.setText("获取中…")
        self._fetch_btn.setEnabled(False)
        self._fetch_status.hide()
        self._branch_select.clear()
        self._add_btn.hide()
        self.branch_fetch_requested.emit(url)

    def _on_add_clicked(self):
        if not self._pending_url:
            return
        name = self._pending_url.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        branches = list(self._branch_select.get_selected())
        if not branches:
            return
        self.repo_add_requested.emit(self._pending_url, name, branches)
        self._url_input.clear()
        self._branch_select.clear()
        self._branch_select.hide()
        self._add_btn.hide()
        self._add_btn.setText("✚  添加到关注列表")
        self._fetch_status.hide()
        self._pending_url = ""
        self._pending_current_branches = []

    def _on_webhook_toggle(self, checked: bool):
        self._wh_btn.setText("● ON" if checked else "● OFF")
        self._wh_btn.setStyleSheet(self._toggle_ss(checked))
        self.webhook_toggle.emit(checked)

    # ── 定位 & 拖拽 ───────────────────────────────────────────────────────

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 16, screen.top() + 16)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.pos().y() <= _GL_SHADOW + self._title_bar.height():
                self._drag_pos = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._has_been_shown = True




class InputWindow(QWidget):
    # 提交信号
    submitted = pyqtSignal(str)
    # 文件搜索信号
    search_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._hiding = False
        self._history: list[str] = []   # 提交历史，用于 ↑ 键回调
        self._history_idx = -1          # -1 = 当前未浏览历史
        self._build_ui()
        self._setup_window()
        # 当系统焦点切换到其他窗口时自动隐藏
        QApplication.instance().focusWindowChanged.connect(self._on_focus_window_changed)
        # 防抖计时器：输入停止 80ms 后再做表达式计算
        self._eval_timer = QTimer(self)
        self._eval_timer.setSingleShot(True)
        self._eval_timer.setInterval(80)
        self._eval_timer.timeout.connect(self._run_evaluate)
        # 思考动画计时器
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(380)
        self._dot_timer.timeout.connect(self._tick_thinking)
        self._dot_frame = 0
        # 文件搜索防抖计时器
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._emit_search)
        self._search_query = ""

    def _on_focus_window_changed(self, focus_window):
        """焦点切换到本窗口之外时隐藏"""
        if self.isVisible() and not self._hiding:
            if focus_window is None or focus_window != self.windowHandle():
                self.hide_window()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        # 透明背景，让投影可以渲染到窗口边界之外
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_WIN_W)

    def _build_ui(self):
        # 外层留出阴影空间
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW, _SHADOW, _SHADOW, _SHADOW)
        outer.setSpacing(0)

        # ── 卡片 ──────────────────────────────────────────
        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setStyleSheet("""
            #card {
                background-color: #1c1a14;
                border-radius: 12px;
                border: 1px solid rgba(192, 140, 30, 0.22);
            }
            QLineEdit {
                background: transparent;
                color: #ede5d0;
                border: none;
                font-size: 20px;
                selection-background-color: #5a4010;
            }
            QLabel {
                background: transparent;
                color: #6a5a3a;
                font-size: 12px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setXOffset(0)
        shadow.setYOffset(12)
        shadow.setColor(QColor(8, 5, 0, 220))
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 14, 20, 12)
        card_layout.setSpacing(0)

        # 输入行
        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.input = QLineEdit()
        self.input.setPlaceholderText("输入指令或表达式…")
        self.input.setMaxLength(MAX_LENGTH)
        self.input.setFixedHeight(46)
        self.input.textChanged.connect(self._on_text_changed)
        input_row.addWidget(self.input)
        card_layout.addLayout(input_row)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            "background: rgba(192, 140, 30, 0.15); "
            "max-height: 1px; border: none; margin: 0;"
        )
        card_layout.addSpacing(10)
        card_layout.addWidget(sep)
        card_layout.addSpacing(7)

        # 底部提示行
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(0)
        self.result_label = QLabel("")
        self.result_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.count_label = QLabel(f"0 / {MAX_LENGTH}")
        self.count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        bottom_row.addWidget(self.result_label)
        bottom_row.addWidget(self.count_label)
        card_layout.addLayout(bottom_row)

        # 文件搜索结果列表（默认隐藏）
        self.file_list = QListWidget()
        self.file_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.file_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.file_list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
                padding: 2px 0;
            }
            QListWidget::item {
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background: rgba(192, 140, 30, 0.20);
            }
            QListWidget::item:hover:!selected {
                background: rgba(192, 140, 30, 0.09);
            }
        """)
        self.file_list.hide()
        self.file_list.itemDoubleClicked.connect(
            lambda item: self._open_file_at_row(self.file_list.row(item))
        )
        card_layout.addWidget(self.file_list)

        # AI 回答区（默认隐藏，有内容时自动展开）
        self.ai_label = QLabel("")
        self.ai_label.setWordWrap(True)
        self.ai_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.ai_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.ai_label.setStyleSheet(
            "color: #d8cfb8; font-size: 13px; line-height: 1.6;"
        )
        self.ai_label.hide()
        card_layout.addSpacing(6)
        card_layout.addWidget(self.ai_label)

        # QR 二维码图片（默认隐藏）
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("background: transparent; padding: 8px 0;")
        self.qr_label.hide()
        card_layout.addWidget(self.qr_label)

        outer.addWidget(self.card)

    def _on_text_changed(self, text: str):
        count = len(text)
        stripped = text.lstrip()

        # ――― 文件搜索模式：以 "找 " 开头 ―――――――――――――――――――――――――――――――――――――
        if stripped.startswith("找 "):
            query = stripped[2:].strip()
            self._eval_timer.stop()
            self._dot_timer.stop()
            self.ai_label.setText("")
            self.ai_label.hide()
            self.clear_qr()
            self.count_label.setStyleSheet("color: #c09030; font-size: 12px;")
            self.count_label.setText("≡ 文件搜索")
            self.result_label.setText("")
            if query:
                self._search_query = query
                self.result_label.setText("搜索中…")
                self.result_label.setStyleSheet("color: #6a5a3a; font-size: 12px;")
                self._search_timer.start()
            else:
                self._search_timer.stop()
                self.clear_file_results()
            self.adjustSize()
            return

        # ─── 非文件搜索模式：清除文件列表和二维码 ─────────────────────
        if self.file_list.isVisible() or self.qr_label.isVisible():
            self._search_timer.stop()
            self.clear_file_results()
            self.clear_qr()

        # 接近上限变红提示
        if count >= MAX_LENGTH * 0.9:
            self.count_label.setStyleSheet("color: #c05050; font-size: 12px;")
        else:
            self.count_label.setStyleSheet("color: #6a5a3a; font-size: 12px;")
        # 指令预览立即响应（无需计算，直接字典查找）
        cmd_preview = preview(text)
        if cmd_preview is not None:
            self.count_label.setText(cmd_preview)
            self.count_label.setStyleSheet("color: #c09030; font-size: 12px;")
            self.result_label.setText("")
            self._eval_timer.stop()
        else:
            self.count_label.setText(f"{count} / {MAX_LENGTH}")
            self.result_label.setText("")
            if text.strip():
                self._eval_timer.start()
            else:
                self._eval_timer.stop()

    def _run_evaluate(self):
        """防抖结束后执行表达式求值。"""
        text = self.input.text()
        expr_result = evaluate_expr(text)
        if expr_result is not None:
            self.result_label.setStyleSheet("color: #c09030; font-size: 12px;")
            self.result_label.setText(expr_result)
        else:
            self.result_label.setText("")

    def keyPressEvent(self, event: QKeyEvent):
        file_mode = self.file_list.isVisible() and self.file_list.count() > 0
        # 回车提交（不立刻清空，等 AI 回答后再清空）
        if event.key() == Qt.Key.Key_Return:
            if file_mode:
                row = self.file_list.currentRow()
                if row < 0:
                    row = 0
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._open_folder_at_row(row)
                else:
                    self._open_file_at_row(row)
                return
            text = self.input.text().strip()
            if text:
                # 记录历史（去重，新的放末尾）
                if not self._history or self._history[-1] != text:
                    self._history.append(text)
                self._history_idx = -1
                self.submitted.emit(text)
        # ↑ 键：文件列表导航 / 历史
        elif event.key() == Qt.Key.Key_Up:
            if file_mode:
                row = self.file_list.currentRow()
                self.file_list.setCurrentRow(max(0, row - 1))
                return
            if self._history:
                if self._history_idx == -1:
                    self._history_idx = len(self._history) - 1
                elif self._history_idx > 0:
                    self._history_idx -= 1
                self.input.setText(self._history[self._history_idx])
                self.input.end(False)  # 光标移到末尾
        # ↓ 键：文件列表导航 / 历史
        elif event.key() == Qt.Key.Key_Down:
            if file_mode:
                row = self.file_list.currentRow()
                self.file_list.setCurrentRow(min(self.file_list.count() - 1, row + 1))
                return
            if self._history_idx != -1:
                if self._history_idx < len(self._history) - 1:
                    self._history_idx += 1
                    self.input.setText(self._history[self._history_idx])
                    self.input.end(False)
                else:
                    self._history_idx = -1
                    self.input.clear()
        # ESC关闭
        elif event.key() == Qt.Key.Key_Escape:
            self.hide_window()

    def append_ai_chunk(self, text: str):
        """流式追加 AI 文本片段。首个片段停止动画并替换占位文本，末尾保持 ▌ 光标。"""
        self._dot_timer.stop()
        current = self.ai_label.text()
        # 移除动画占位
        for frame in ("正在思考", "正在思考 ·", "正在思考 · ·", "正在思考 · · ·"):
            if current == frame:
                current = ""
                break
        if current.endswith("▌"):
            current = current[:-1]
        self.ai_label.setStyleSheet("color: #d8cfb8; font-size: 13px; line-height: 1.6;")
        self.ai_label.setText(current + text + "▌")
        self.ai_label.show()
        self.adjustSize()
        if not self.isVisible():
            print("[UI] 窗口不可见，重新 show_window")
            self.show_window()

    def finish_ai_stream(self):
        """流式结束：停止动画，移除 ▌ 光标，清空输入框。"""
        self._dot_timer.stop()
        current = self.ai_label.text()
        if current.endswith("▌"):
            self.ai_label.setText(current[:-1])
        self.adjustSize()
        self.input.clear()

    def _tick_thinking(self):
        """动画帧切换：正在思考 → · → · · → · · ·"""
        frames = ["正在思考", "正在思考 ·", "正在思考 · ·", "正在思考 · · ·"]
        self._dot_frame = (self._dot_frame + 1) % len(frames)
        self.ai_label.setText(frames[self._dot_frame])

    def show_thinking(self):
        """显示思考动画（清空旧回答并启动帧计时器）。"""
        print("[UI] show_thinking 被调用")
        self._dot_frame = 0
        self.clear_qr()
        self.ai_label.setStyleSheet("color: #8a7040; font-size: 13px;")
        self.ai_label.setText("正在思考")
        self.ai_label.show()
        self.adjustSize()
        self._dot_timer.start()

    def show_ai_result(self, text: str):
        """AI 回答完成（错误分支），展示结果并清空输入框。"""
        print(f"[UI] show_ai_result 被调用，内容: {text[:60]}...")
        self._dot_timer.stop()
        self.clear_qr()
        color = "#c05050" if text.startswith("❌") else "#d8cfb8"
        self.ai_label.setStyleSheet(
            f"color: {color}; font-size: 13px; line-height: 1.6;"
        )
        self.ai_label.setText(text)
        self.ai_label.show()
        self.adjustSize()
        self.input.clear()
        if not self.isVisible():
            print("[UI] 窗口不可见，重新 show_window")
            self.show_window()

    def show_result(self, result: str):
        """预设指令执行结果：✅ 金绿色，❌ 红色，显示于右侧，同时清空输入框和 AI 区域。"""
        if result.startswith("✅"):
            color = "#7ab86a"
        else:
            color = "#c05050"
        self.count_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.count_label.setText(result)
        self.result_label.setText("")
        self.input.clear()
        # 清空上次 AI 回答和 QR
        self._dot_timer.stop()
        self.ai_label.setText("")
        self.ai_label.hide()
        self.clear_qr()
        self.adjustSize()

    def show_window(self):
        # 居中显示
        screen = self.screen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = screen.height() // 3
        self.move(x, y)
        self.show()
        self.raise_()
        # 延迟激活，确保窗口完全渲染后再抢夺焦点（解决 Windows 下 Tool 窗口无法获得输入的问题）
        QTimer.singleShot(50, self._force_focus)

    def _force_focus(self):
        hwnd = int(self.winId())
        _win_force_foreground(hwnd)
        self.input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def hide_window(self):
        self._hiding = True
        self._search_timer.stop()
        self.hide()
        self._hiding = False

    # ─── 文件搜索相关 ─────────────────────────────────────────────────────

    def show_info(self, text: str):
        """用等宽字体展示系统信息类多行文本。"""
        self._dot_timer.stop()
        self.clear_qr()
        self.clear_file_results()
        self.ai_label.setStyleSheet(
            "color: #c8c0a8; font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; line-height: 1.8;"
        )
        self.ai_label.setText(text)
        self.ai_label.show()
        self.input.clear()
        self.adjustSize()

    def show_qr(self, png_bytes: bytes):
        """展示二维码图片（清除其他结果区域）。"""
        self._dot_timer.stop()
        self.ai_label.setText("")
        self.ai_label.hide()
        self.clear_file_results()
        px = QPixmap()
        px.loadFromData(png_bytes)
        size = 210
        self.qr_label.setPixmap(
            px.scaled(size, size,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
        )
        self.input.clear()   # 先清空输入框，避免触发 _on_text_changed 时 qr_label 已可见
        self.qr_label.show()
        self.count_label.setText("手机扫码  ESC 关闭")
        self.count_label.setStyleSheet("color: #7ab86a; font-size: 12px;")
        self.result_label.setText("")
        self.adjustSize()

    def clear_qr(self):
        """TODO: 隐藏并清除二维码图片。"""
        self.qr_label.clear()
        self.qr_label.hide()

    def _emit_search(self):
        self.search_requested.emit(self._search_query)

    def show_file_results(self, results: list):
        self.file_list.clear()
        if not results:
            self.result_label.setStyleSheet("color: #6a5a3a; font-size: 12px;")
            self.result_label.setText("未找到文件")
            self.file_list.hide()
        else:
            self.result_label.setStyleSheet("color: #6a5a3a; font-size: 12px;")
            self.result_label.setText(f"找到 {len(results)} 个  ↵打开  Ctrl+↵打开文件夹")
            for r in results:
                self._add_file_item(r['name'], r['path'], r['dir'])
            item_h = 48
            max_visible = 5
            total_h = len(results) * item_h + 4
            self.file_list.setFixedHeight(min(total_h, max_visible * item_h + 4))
            self.file_list.setCurrentRow(0)
            self.file_list.show()
        self.adjustSize()

    def clear_file_results(self):
        self.file_list.clear()
        self.file_list.hide()
        self.adjustSize()

    def _add_file_item(self, name: str, path: str, directory: str):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setSizeHint(QSize(_CARD_W - 40, 48))

        w = QWidget()
        w.setStyleSheet("background: transparent;")
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(6, 5, 6, 5)
        vl.setSpacing(1)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color: #ede5d0; font-size: 13px; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        dir_lbl = QLabel(directory)
        dir_lbl.setStyleSheet("color: #5a4a2a; font-size: 10px; background: transparent;")
        dir_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        vl.addWidget(name_lbl)
        vl.addWidget(dir_lbl)

        self.file_list.addItem(item)
        self.file_list.setItemWidget(item, w)

    def _open_file_at_row(self, row: int):
        if row < 0 or row >= self.file_list.count():
            return
        item = self.file_list.item(row)
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and os.path.exists(path):
                os.startfile(path)
                self.hide_window()

    def _open_folder_at_row(self, row: int):
        if row < 0 or row >= self.file_list.count():
            return
        item = self.file_list.item(row)
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and os.path.exists(path):
                os.startfile(os.path.dirname(path))
                self.hide_window()
