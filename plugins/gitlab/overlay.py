from PyQt6.QtWidgets import (QWidget, QLineEdit, QLabel, QVBoxLayout,
                             QHBoxLayout, QApplication,
                             QGraphicsDropShadowEffect, QFrame,
                             QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem,
                             QPushButton, QHeaderView,
                             QScrollArea, QStackedWidget, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from PyQt6.QtGui import QColor
import ctypes

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
        self._view_layout.addStretch()
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
                self._view_layout.insertWidget(self._view_layout.count() - 1, lbl)
                self._view_widgets.append(lbl)
            if error:
                err = QLabel(f"  ⚠  {error}")
                err.setStyleSheet(
                    "color: #c05050; font-size: 13px; padding: 4px 6px;"
                    " background: transparent; border: none;"
                )
                self._view_layout.insertWidget(self._view_layout.count() - 1, err)
                self._view_widgets.append(err)
            elif name:
                tbl = self._make_table(repo_data.get("branches", []))
                self._view_layout.insertWidget(self._view_layout.count() - 1, tbl)
                self._view_widgets.append(tbl)
        self.adjustSize()
        if not self.isVisible():
            self.show()
            self.raise_()
        
    def _adjust_layout_items(self):
        self.adjustSize()
        if not self.isVisible():
            self.show()
            self.raise_()
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
        # 编辑页至少占视口高度的 80%（减去标题栏和底部Webhook栏）
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        title_h = self._title_bar.sizeHint().height()
        footer_h = 42
        self._edit_scroll.setMinimumHeight(max(200, int(screen_h * 0.80) - title_h - footer_h))
        self._edit_scroll.setMaximumHeight(16777215)
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




