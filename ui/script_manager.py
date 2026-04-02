from PyQt6.QtWidgets import (QWidget, QLineEdit, QLabel, QVBoxLayout,
                             QHBoxLayout, QApplication,
                             QGraphicsDropShadowEffect, QListWidget,
                             QListWidgetItem, QPushButton)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QColor
import ctypes

MAX_LENGTH = 200  # AI 模式下允许输入更长的内容
_SHADOW    = 24          # 阴影溢出留边
_CARD_W    = 640         # 卡片宽度
_WIN_W     = _CARD_W + _SHADOW * 2

_SM_SHADOW = 10
_SM_CARD_W = 960

from PyQt6.QtWidgets import QStackedWidget

class _AdaptiveStack(QStackedWidget):
    """sizeHint 跟随当前页变化，使父窗口能自适应高度。"""
    def sizeHint(self):
        cur = self.currentWidget()
        return cur.sizeHint() if cur else super().sizeHint()

    def minimumSizeHint(self):
        cur = self.currentWidget()
        return cur.minimumSizeHint() if cur else super().minimumSizeHint()
import os as _os
import json as _json
import uuid as _uuid
import subprocess as _subprocess
import threading as _threading

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



def _sm_data_path() -> str:
    base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    d = _os.path.join(base, "script_manager")
    _os.makedirs(d, exist_ok=True)
    return _os.path.join(d, "scripts.json")


def _sm_load() -> list:
    p = _sm_data_path()
    if not _os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        return _json.load(f).get("scripts", [])


def _sm_save(scripts: list):
    p = _sm_data_path()
    with open(p, "w", encoding="utf-8") as f:
        _json.dump({"scripts": scripts}, f, ensure_ascii=False, indent=2)


def _sm_workspace_path() -> str:
    base = _os.path.dirname(_os.path.abspath(__file__))
    d = _os.path.join(base, "script_manager", "workspace")
    _os.makedirs(d, exist_ok=True)
    return d


from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt6.QtCore import QRegularExpression

class ScriptHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        self.current_type = "shell"
        self.fmt_keyword = QTextCharFormat()
        self.fmt_keyword.setForeground(QColor("#c678dd"))
        self.fmt_string = QTextCharFormat()
        self.fmt_string.setForeground(QColor("#98c379"))
        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor("#5c6370"))
        self.fmt_builtin = QTextCharFormat()
        self.fmt_builtin.setForeground(QColor("#e5c07b"))
        self._build_rules()

    def set_type(self, stype: str):
        self.current_type = stype
        self._build_rules()
        self.rehighlight()

    def _build_rules(self):
        self.rules = []
        # strings
        self.rules.append((QRegularExpression(r'".*?(?<!\\)"'), self.fmt_string))
        self.rules.append((QRegularExpression(r"'.*?(?<!\\)'"), self.fmt_string))
        
        if self.current_type == "python":
            keywords = ["def", "class", "import", "from", "return", "if", "else", "elif", "for", "while", "in", "is", "not", "and", "or", "try", "except", "finally", "with", "as", "pass", "break", "continue", "yield", "await", "async", "True", "False", "None"]
            builtins = ["print", "len", "range", "str", "int", "list", "dict", "set", "tuple", "open", "type"]
            kw_pattern = r"\b(" + "|".join(keywords) + r")\b"
            bi_pattern = r"\b(" + "|".join(builtins) + r")\b"
            self.rules.append((QRegularExpression(kw_pattern), self.fmt_keyword))
            self.rules.append((QRegularExpression(bi_pattern), self.fmt_builtin))
            self.rules.append((QRegularExpression(r"#[^\n]*"), self.fmt_comment))
            
        elif self.current_type in ("shell", "powershell", "batch"):
            keywords = ["if", "else", "for", "in", "do", "done", "echo", "cd", "set", "export", "git", "npm", "node", "xcopy", "cp", "mv", "rm", "python", "pnpm", "yarn", "pip", "Copy-Item", "Set-Location"]
            kw_pattern = r"\b(" + "|".join(keywords) + r")\b"
            self.rules.append((QRegularExpression(kw_pattern), self.fmt_keyword))
            if self.current_type == "batch":
                self.rules.append((QRegularExpression(r"(?i)\brem\b[^\n]*"), self.fmt_comment))
                self.rules.append((QRegularExpression(r"::[^\n]*"), self.fmt_comment))
                self.rules.append((QRegularExpression(r"@[^\n]*"), self.fmt_keyword))
            else:
                self.rules.append((QRegularExpression(r"#[^\n]*"), self.fmt_comment))

    def highlightBlock(self, text: str):
        for pattern, format in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)


class ScriptEditor(QTextEdit):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
        elif event.key() == Qt.Key.Key_Backtab:
            pass  # 简易实现：先略过 Shift+Tab
        else:
            super().keyPressEvent(event)


from PyQt6.QtWidgets import QDialog

class ThemeConfirmDialog(QDialog):
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(340, 180)
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        
        card = QWidget()
        card.setStyleSheet("""
            QWidget {
                background-color: #1c1a14;
                border-radius: 12px;
                border: 1px solid rgba(192, 140, 30, 0.3);
            }
            QLabel { border: none; background: transparent; }
        """)
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 180))
        card.setGraphicsEffect(shadow)
        
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(20, 20, 20, 16)
        vbox.setSpacing(14)
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #e8d89a; font-size: 15px; font-weight: bold;")
        vbox.addWidget(title_lbl)
        
        text_lbl = QLabel(text)
        text_lbl.setWordWrap(True)
        text_lbl.setStyleSheet("color: #c0b89a; font-size: 13px;")
        vbox.addWidget(text_lbl)
        vbox.addStretch()
        
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        
        cancel_b = QPushButton("取消")
        cancel_b.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_b.setFixedSize(64, 30)
        cancel_b.setStyleSheet("""
            QPushButton { background: transparent; color: #8a7a5a;
                border: 1px solid rgba(138,122,90,0.3); border-radius: 6px; font-size: 12px; }
            QPushButton:hover { background: rgba(138,122,90,0.1); color: #c0b89a; }
        """)
        cancel_b.clicked.connect(self.reject)
        
        ok_b = QPushButton("确认删除")
        ok_b.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_b.setFixedSize(76, 30)
        ok_b.setStyleSheet("""
            QPushButton { background: rgba(200,60,60,0.15); color: #e66;
                border: 1px solid rgba(170,68,68,0.3); border-radius: 6px; font-size: 12px; }
            QPushButton:hover { background: rgba(200,60,60,0.3); border-color: rgba(238,102,102,0.4); }
        """)
        ok_b.clicked.connect(self.accept)
        
        btn_row.addWidget(cancel_b)
        btn_row.addWidget(ok_b)
        vbox.addLayout(btn_row)
        outer.addWidget(card)


from PyQt6.QtWidgets import QStackedWidget, QSplitter, QTabWidget

class _RunTabWidget(QWidget):
    """单个脚本运行任务的独立日志面板，嵌入 QTabWidget 的某个 Tab 中。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_cancelled = False
        self.proc = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_edit.setStyleSheet("""
            QTextEdit {
                background: #141210; border: 1px solid rgba(192,140,30,0.18);
                border-radius: 6px; color: #c0b89a;
                font-family: Consolas, 'Courier New', monospace; font-size: 13px;
                outline: none; padding: 8px 10px;
            }
            QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
            QScrollBar::handle:vertical {
                background: rgba(192,140,30,0.25); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        layout.addWidget(self.log_edit, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.status_lbl = QLabel("▶  执行中…")
        self.status_lbl.setStyleSheet(
            "color: #c09030; font-size: 13px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        bottom.addWidget(self.status_lbl, 1)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stop_btn.setStyleSheet("""
            QPushButton { background: rgba(200,60,60,0.15); color: #e66;
                border: 1px solid rgba(170,68,68,0.3); border-radius: 4px;
                font-size: 12px; padding: 4px 10px; }
            QPushButton:hover { background: rgba(200,60,60,0.3); border-color: rgba(238,102,102,0.4); }
        """)
        self.stop_btn.clicked.connect(self.cancel)
        bottom.addWidget(self.stop_btn)
        layout.addLayout(bottom)

    def cancel(self):
        self.is_cancelled = True
        self.stop_btn.hide()
        if self.proc:
            try: self.proc.terminate()
            except Exception: pass

    def set_done(self, success: bool):
        self.stop_btn.hide()
        if success:
            self.status_lbl.setText("✅  执行成功")
            self.status_lbl.setStyleSheet(
                "color: #50c870; font-size: 13px; font-weight: bold; "
                "background: transparent; border: none;"
            )
        else:
            self.status_lbl.setText("❌  执行失败")
            self.status_lbl.setStyleSheet(
                "color: #c05050; font-size: 13px; font-weight: bold; "
                "background: transparent; border: none;"
            )

    def append_line(self, text: str, color: str = "#c0b89a"):
        from PyQt6.QtGui import QTextCursor
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_edit.setTextCursor(cursor)
        parsed = ScriptManagerOverlay._parse_ansi(text, color).replace('\n', '<br>')
        self.log_edit.insertHtml(parsed + '<br>')
        self.log_edit.ensureCursorVisible()

from ui.window_base import OpenHamWindowBase

class ScriptManagerOverlay(OpenHamWindowBase):
    """
    原生脚本管理浮层：
      左侧面板  → 脚本列表 / 编辑（始终可见）
      右侧面板  → 多标签运行日志，每个脚本独立一个 Tab
    """

    triggers_changed = pyqtSignal()
    run_requested = pyqtSignal(str)
    # 跨线程日志信号：(run_tab 引用, 文本, 颜色)
    log_appended = pyqtSignal(object, str, str)
    run_finished = pyqtSignal(object, bool)

    def __init__(self):
        super().__init__(title="⚡  脚本配置", shadow_size=_SM_SHADOW, min_w=_SM_CARD_W, min_h=600)
        self._drag_pos = None
        self._has_been_shown = False
        self._current_id: str | None = None
        self._run_timer = QTimer(self)    # kept for compatibility
        self._run_timer.setInterval(300)
        self._run_timer.timeout.connect(self._poll_log)

        self.log_appended.connect(self._do_append_log)
        self.run_finished.connect(self._do_set_log_done)

        self._build_ui()
        self.resize(_SM_CARD_W + _SM_SHADOW * 2, 760)
        self.show_window_centered(_SM_CARD_W, 760)
        self.hide()

    # ── UI 构建 ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._new_btn = self._icon_btn("＋", "#8a7a5a", "新建脚本")
        self._new_btn.clicked.connect(self._go_new)
        self.header_tools_layout.addWidget(self._new_btn)

        # ── 左右分栏 ────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: rgba(192,140,30,0.18); width: 2px;
            }
        """)
        splitter.setHandleWidth(2)
        splitter.setChildrenCollapsible(False)

        # 左侧：脚本列表 / 编辑页 (始终可见)
        self._left_stack = QStackedWidget()
        self._left_stack.setStyleSheet("background: transparent;")
        self._left_stack.setMinimumWidth(300)
        self._left_stack.addWidget(self._build_list_page())  # 0 = 列表
        self._left_stack.addWidget(self._build_edit_page())  # 1 = 编辑
        splitter.addWidget(self._left_stack)

        # 右侧：多任务日志标签页
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none; background: transparent;
            }
            QTabBar::tab {
                background: rgba(30,28,20,0.7);
                color: #8a7a5a; border: 1px solid rgba(192,140,30,0.18);
                border-bottom: none; border-radius: 5px 5px 0 0;
                padding: 5px 12px; font-size: 12px; min-width: 80px;
            }
            QTabBar::tab:selected {
                background: #272416; color: #c09030;
                border-color: rgba(192,140,30,0.45);
            }
            QTabBar::tab:hover:!selected { background: rgba(50,44,28,0.9); }
            QTabBar::close-button {
                image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238a7a5a' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><line x1='18' y1='6' x2='6' y2='18'></line><line x1='6' y1='6' x2='18' y2='18'></line></svg>");
                subcontrol-position: right; margin-right: 4px;
                width: 14px; height: 14px;
            }
            QTabBar::close-button:hover {
                image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23e66' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><line x1='18' y1='6' x2='6' y2='18'></line><line x1='6' y1='6' x2='18' y2='18'></line></svg>");
            }
        """)
        self._tab_widget.tabCloseRequested.connect(self._close_run_tab)
        self._tab_widget.setMinimumWidth(350)

        # 欢迎占位页
        self._welcome_tab = self._make_welcome_tab()
        self._tab_widget.addTab(self._welcome_tab, " 运行日志 ")
        self._tab_widget.tabBar().setTabButton(0, self._tab_widget.tabBar().ButtonPosition.RightSide, None)
        splitter.addWidget(self._tab_widget)

        splitter.setSizes([450, 510])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.content_layout.addWidget(splitter, 1)

        self.content_layout.addWidget(splitter, 1)

    def _make_welcome_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel("点击左侧脚本的  ▶ 运行  按钮\n即可在此查看实时执行日志\n\n可同时运行多个脚本，各自独立显示")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "color: #3a3020; font-size: 14px; line-height: 2; "
            "background: transparent; border: none;"
        )
        lay.addWidget(lbl)
        return w

    def _create_run_tab(self, name: str) -> "_RunTabWidget":
        """新建一个运行日志 Tab 并切换到它。"""
        # 若欢迎页还在，替换掉
        if self._welcome_tab is not None:
            idx = self._tab_widget.indexOf(self._welcome_tab)
            if idx >= 0:
                self._tab_widget.removeTab(idx)
            self._welcome_tab = None

        tab = _RunTabWidget(self)
        short_name = name[:18] + "…" if len(name) > 18 else name
        idx = self._tab_widget.addTab(tab, f"⏳ {short_name}")
        self._tab_widget.setCurrentIndex(idx)
        return tab

    def _close_run_tab(self, idx: int):
        """关闭某个运行 Tab，同时 terminate 对应进程。"""
        tab = self._tab_widget.widget(idx)
        if isinstance(tab, _RunTabWidget):
            tab.cancel()
        self._tab_widget.removeTab(idx)
        # 若所有运行 Tab 都关了，恢复欢迎页
        if self._tab_widget.count() == 0:
            self._welcome_tab = self._make_welcome_tab()
            self._tab_widget.addTab(self._welcome_tab, " 运行日志 ")
            self._tab_widget.tabBar().setTabButton(
                0, self._tab_widget.tabBar().ButtonPosition.RightSide, None
            )


    # ── 列表页 ─────────────────────────────────────────────────────────────

    # ── 列表页 ─────────────────────────────────────────────────────────────

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(14, 10, 14, 14)
        vbox.setSpacing(6)

        self._list_widget = QListWidget()
        self._list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list_widget.setStyleSheet("""
            QListWidget {
                background: transparent; border: none; outline: none;
            }
            QListWidget::item { border-radius: 6px; padding: 0; }
            QListWidget::item:selected { background: rgba(192,140,30,0.16); }
            QListWidget::item:hover:!selected { background: rgba(192,140,30,0.08); }
        """)
        self._list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget.setStyleSheet(self._list_widget.styleSheet() + """
            QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
            QScrollBar::handle:vertical {
                background: rgba(192,140,30,0.28); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        # 允许列表随窗口拉伸，不锁死高度，超出时自然启用滚动条
        from PyQt6.QtWidgets import QSizePolicy
        self._list_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._list_widget.setMinimumHeight(200)
        self._list_widget.itemClicked.connect(
            lambda item: self._go_edit(item.data(Qt.ItemDataRole.UserRole))
        )
        vbox.addWidget(self._list_widget)

        self._list_empty = QLabel("  暂无脚本，点击 ＋ 新建")
        self._list_empty.setStyleSheet(
            "color: #5a4a2a; font-size: 13px; padding: 20px 6px; "
            "background: transparent; border: none;"
        )
        self._list_empty.hide()
        vbox.addWidget(self._list_empty)
        return page

    # ── 编辑页 ─────────────────────────────────────────────────────────────

    def _build_edit_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(14, 12, 14, 14)
        vbox.setSpacing(10)

        # 顶部导航行
        header = QHBoxLayout()
        self._back_btn = self._icon_btn("←", "#5a9a5a", "返回列表")
        self._back_btn.clicked.connect(self._go_list)
        header.addWidget(self._back_btn)
        header.addStretch()
        vbox.addLayout(header)

        # 基本信息
        vbox.addWidget(self._section_lbl("基本信息（触发词与功能说明）"))
        self._trigger_input = QLineEdit()
        self._trigger_input.setPlaceholderText("触发词必填，如: open playground")
        self._trigger_input.setStyleSheet(self._input_ss())
        self._trigger_input.setFixedHeight(34)
        self._trigger_input.setMaxLength(60)
        vbox.addWidget(self._trigger_input)
        
        self._desc_input = QTextEdit()
        self._desc_input.setPlaceholderText("说明备注选填，支持多行，如：用于自动打包合并代码等...\n在此处详细记录任何需要回想的上下文或步骤。")
        self._desc_input.setStyleSheet(self._input_ss() + " QTextEdit { padding-top: 4px; }")
        self._desc_input.setFixedHeight(64) # 高度适中，够填两三行
        self._desc_input.setAcceptRichText(False)
        vbox.addWidget(self._desc_input)

        # 脚本类型选择器
        vbox.addWidget(self._section_lbl("脚本类型"))
        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        self._type_btns: dict[str, QPushButton] = {}
        _TYPES = [
            ("shell",      "🖥  Shell 逐行"),
            ("python",     "🐍  Python"),
            ("powershell", "🔷  PowerShell"),
            ("batch",      "📄  批处理 (.bat)"),
        ]
        for tid, tlabel in _TYPES:
            btn = QPushButton(tlabel)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(self._type_btn_ss(False))
            btn.clicked.connect(lambda _, t=tid: self._set_script_type(t))
            self._type_btns[tid] = btn
            type_row.addWidget(btn)
        type_row.addStretch()
        vbox.addLayout(type_row)

        # 脚本内容
        self._script_type_lbl = self._section_lbl("脚本内容  （每行一条命令，顺序执行，出错即停止）")
        vbox.addWidget(self._script_type_lbl)
        self._script_edit = ScriptEditor()
        self._highlighter = ScriptHighlighter(self._script_edit.document())
        self._script_edit.setStyleSheet("""
            QTextEdit {
                background: #1a1810; color: #ede5d0;
                border: 1px solid rgba(192,140,30,0.28);
                border-radius: 6px; font-size: 13px;
                font-family: Consolas, 'Courier New', monospace;
                padding: 8px 10px;
            }
            QTextEdit:focus { border-color: rgba(192,140,30,0.65); }
            QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
            QScrollBar::handle:vertical {
                background: rgba(192,140,30,0.28); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._script_edit.setMinimumHeight(260)
        self._script_edit.setMaximumHeight(500)
        vbox.addWidget(self._script_edit)
        self._set_script_type("shell")  # 默认

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._save_btn = QPushButton("💾  保存")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._save_btn.setStyleSheet(self._action_btn_ss("#c09030", "rgba(192,140,30,0.18)", "rgba(192,140,30,0.33)"))
        self._save_btn.clicked.connect(self._save_script)
        btn_row.addWidget(self._save_btn)

        self._run_btn = QPushButton("▶  运行")
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._run_btn.setStyleSheet(self._action_btn_ss("#50c870", "rgba(50,140,80,0.18)", "rgba(50,140,80,0.35)"))
        self._run_btn.clicked.connect(self._run_current)
        btn_row.addWidget(self._run_btn)

        btn_row.addStretch()
        vbox.addLayout(btn_row)

        # 状态提示
        self._edit_status = QLabel("")
        self._edit_status.setStyleSheet(
            "color: #7ab86a; font-size: 12px; background: transparent; border: none;"
        )
        vbox.addWidget(self._edit_status)
        vbox.addStretch()
        return page

    # ── 日志页 ─────────────────────────────────────────────────────────────

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(14, 10, 14, 14)
        vbox.setSpacing(8)

        status_row = QHBoxLayout()
        self._log_status_lbl = QLabel("▶  执行中…")
        self._log_status_lbl.setStyleSheet(
            "color: #c09030; font-size: 13px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        status_row.addWidget(self._log_status_lbl)
        
        status_row.addStretch()
        
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stop_btn.setStyleSheet("""
            QPushButton { background: rgba(200,60,60,0.15); color: #e66;
                border: 1px solid rgba(170,68,68,0.3); border-radius: 4px; font-size: 12px; padding: 4px 10px; }
            QPushButton:hover { background: rgba(200,60,60,0.3); border-color: rgba(238,102,102,0.4); }
        """)
        self._stop_btn.clicked.connect(self._cancel_run)
        self._stop_btn.hide()
        status_row.addWidget(self._stop_btn)
        vbox.addLayout(status_row)

        self._log_list = QTextEdit()
        self._log_list.setReadOnly(True)
        self._log_list.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._log_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._log_list.setStyleSheet("""
            QTextEdit {
                background: #141210; border: 1px solid rgba(192,140,30,0.18);
                border-radius: 6px; color: #c0b89a;
                font-family: Consolas, 'Courier New', monospace; font-size: 13px;
                outline: none; padding: 8px 10px;
            }
            QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
            QScrollBar::handle:vertical {
                background: rgba(192,140,30,0.25); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._log_list.setMinimumHeight(400)
        self._log_list.setMaximumHeight(680)
        vbox.addWidget(self._log_list)
        return page

    # ── 页面切换 ───────────────────────────────────────────────────────────

    def _go_list(self):
        self._stop_run_timer()
        self.title_lbl.setText("⚡  脚本配置")
        self._new_btn.show()
        self._back_btn.hide()
        self._left_stack.setCurrentIndex(0)
        self._reload_list()

    def _go_new(self):
        self._current_id = None
        self.title_lbl.setText("⚡  新建脚本")
        self._new_btn.hide()
        self._back_btn.show()
        self._trigger_input.clear()
        self._desc_input.clear()
        self._script_edit.clear()
        self._edit_status.setText("")
        self._set_script_type("shell")
        self._left_stack.setCurrentIndex(1)
        self._trigger_input.setFocus()

    def _go_edit(self, sid: str):
        scripts = _sm_load()
        s = next((x for x in scripts if x.get("id") == sid), None)
        if not s:
            return
        self._current_id = sid
        self.title_lbl.setText("⚡  编辑脚本")
        self._new_btn.hide()
        self._back_btn.show()
        self._trigger_input.setText(s.get("trigger", ""))
        self._desc_input.setPlainText(s.get("description", ""))
        self._script_edit.setPlainText(s.get("commands", ""))
        self._set_script_type(s.get("script_type", "shell"))
        self._edit_status.setText("")
        self._left_stack.setCurrentIndex(1)
        self._trigger_input.setFocus()


    # ── 数据操作 ───────────────────────────────────────────────────────────

    def _reload_list(self):
        self._list_widget.clear()
        scripts = _sm_load()
        if not scripts:
            self._list_empty.show()
            self._list_widget.hide()
        else:
            self._list_empty.hide()
            self._list_widget.show()
            for s in scripts:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, s.get("id"))
                item.setSizeHint(QSize(_SM_CARD_W - 28, 64))
                self._list_widget.addItem(item)
                self._list_widget.setItemWidget(item, self._make_script_row(s))
    def _make_script_row(self, s: dict) -> QWidget:
        row = QWidget()
        row.setStyleSheet("""
            QWidget {
                background: rgba(30,28,20,0.70);
                border: 1px solid rgba(192,140,30,0.14);
                border-radius: 6px;
            }
        """)
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 8, 8)
        h.setSpacing(8)

        info = QVBoxLayout()
        info.setSpacing(4)
        trigger = s.get("trigger", "").strip()
        desc = s.get("description", "").strip()
        stype   = s.get("script_type", "shell")
        _TYPE_LABEL = {
            "shell": "🖥 Shell", "python": "🐍 Py",
            "powershell": "🔷 PS", "batch": "📄 Bat",
        }
        type_tag = _TYPE_LABEL.get(stype, stype)
        
        name_lbl = QLabel(f"{trigger if trigger else '(未设置触发命令)'}  "
                          f"<span style='font-size:10px;color:#5a7060;'>{type_tag}</span>")
        name_lbl.setTextFormat(Qt.TextFormat.RichText)
        name_lbl.setStyleSheet(
            "color: #ede5d0; font-size: 13px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        info.addWidget(name_lbl)
        
        if desc:
            desc_str = desc.strip().replace("\n", "  ")
            # Enforce single line truncation using ellipsis
            if len(desc_str) > 65:
                desc_str = desc_str[:62] + "..."
            desc_lbl = QLabel(desc_str)
            desc_lbl.setStyleSheet("color: #8a7a5a; font-size: 12px; font-weight: normal; background: transparent; border: none;")
            desc_lbl.setFixedHeight(18)
            info.addWidget(desc_lbl)
        
        # 移除了代码预览，仅显示名称和说明，保持卡片清爽
        h.addLayout(info, 1)

        # 运行按钮
        run_b = QPushButton("▶ 运行")
        run_b.setFixedHeight(28)
        run_b.setCursor(Qt.CursorShape.PointingHandCursor)
        run_b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        run_b.setStyleSheet("""
            QPushButton { background: rgba(50,140,80,0.18); color: #50a850;
                border: 1px solid rgba(50,140,80,0.30); border-radius: 4px; font-size: 13px; padding: 0 10px; }
            QPushButton:hover { background: rgba(50,140,80,0.35); }
        """)
        run_b.clicked.connect(lambda _, sid=s.get("id"): self._run_by_id(sid))
        h.addWidget(run_b)

        # 编辑按钮
        edit_b = QPushButton("✎ 编辑")
        edit_b.setFixedHeight(28)
        edit_b.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        edit_b.setStyleSheet("""
            QPushButton { background: transparent; color: #6a7a8a;
                border: 1px solid rgba(106,122,138,0.2); border-radius: 4px; font-size: 13px; padding: 0 10px; }
            QPushButton:hover { background: rgba(88,130,160,0.20); color: #aac8e0; border-color: rgba(170,200,224,0.3); }
        """)
        edit_b.clicked.connect(lambda _, sid=s.get("id"): self._go_edit(sid))
        h.addWidget(edit_b)

        # 删除按钮
        del_b = QPushButton("🗑 删除")
        del_b.setFixedHeight(28)
        del_b.setCursor(Qt.CursorShape.PointingHandCursor)
        del_b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        del_b.setStyleSheet("""
            QPushButton { background: transparent; color: #a44;
                border: 1px solid rgba(170,68,68,0.2); border-radius: 4px; font-size: 13px; padding: 0 10px; }
            QPushButton:hover { background: rgba(200,60,60,0.2); color: #e66; border-color: rgba(238,102,102,0.3); }
        """)
        def _confirm_delete():
            dlg = ThemeConfirmDialog(self, "确认删除",
                f"确定要永久删除脚本「{s.get('trigger', '未命名')}」吗？")
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._current_id = s.get("id")
                self._delete_script()
        del_b.clicked.connect(_confirm_delete)
        h.addWidget(del_b)
        return row

    def _run_by_id(self, sid: str, silent: bool = False):
        scripts = _sm_load()
        s = next((x for x in scripts if x.get("id") == sid), None)
        if not s:
            return
        trigger = s.get("trigger", sid)
        if not silent:
            run_tab = self._create_run_tab(trigger)
            if not self.isVisible():
                if not self._has_been_shown:
                    self._reposition()
                self.show()
                self.raise_()
        else:
            run_tab = _RunTabWidget()  # silent: create but don't add to tab widget
        self._start_run(s, run_tab)

    def _run_current(self):
        """从编辑页运行当前脚本（先保存）。"""
        self._save_script()
        if not self._current_id:
            return
        self._run_by_id(self._current_id)

    def _save_script(self):
        trigger = self._trigger_input.text().strip()
        desc = getattr(self, "_desc_input", QTextEdit()).toPlainText().strip()
        commands = self._script_edit.toPlainText().strip()
        stype = getattr(self, "_current_script_type", "shell")
        if not trigger:
            self._show_edit_status("❌  请填写触发命令", error=True)
            return
        scripts = _sm_load()
        if self._current_id:
            for s in scripts:
                if s.get("id") == self._current_id:
                    s["trigger"] = trigger
                    s["description"] = desc
                    s["commands"] = commands
                    s["script_type"] = stype
                    break
        else:
            scripts.append({
                "id": str(_uuid.uuid4()),
                "trigger": trigger,
                "description": desc,
                "commands": commands,
                "script_type": stype,
            })
            self._current_id = scripts[-1]["id"]
        _sm_save(scripts)
        self._show_edit_status("✅  已保存")
        self.triggers_changed.emit()

    def _delete_script(self):
        if not self._current_id:
            return
        scripts = [s for s in _sm_load() if s.get("id") != self._current_id]
        _sm_save(scripts)
        self.triggers_changed.emit()
        self._go_list()

    def _start_run(self, s: dict, run_tab: _RunTabWidget):
        self._stop_run_timer()

        content = s.get("commands", "").strip()
        stype   = s.get("script_type", "shell")
        sid     = s.get("id", str(_uuid.uuid4()))

        # 利用闭包捕获 run_tab，让每个任务拥有独立的日志/状态
        def _log(text, color="#c0b89a"):
            self.log_appended.emit(run_tab, text, color)
        def _done(success):
            self.run_finished.emit(run_tab, success)

        if not content:
            _log("(没有内容)", "#c05050")
            _done(False)
            return

        if stype == "shell":
            commands = [c.strip() for c in content.splitlines() if c.strip()]

            def _worker_shell():
                total = len(commands)
                for i, cmd in enumerate(commands, 1):
                    if run_tab.is_cancelled:
                        break
                    _log(f"⏳ [{i}/{total}]  {cmd}", "#c09030")
                    try:
                        run_tab.proc = _subprocess.Popen(
                            cmd, shell=True,
                            stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT
                        )
                        for line_bytes in run_tab.proc.stdout:
                            try:
                                line = line_bytes.decode("utf-8")
                            except UnicodeDecodeError:
                                line = line_bytes.decode("gbk", errors="replace")
                            _log(line.rstrip())
                            if run_tab.is_cancelled:
                                break
                        run_tab.proc.wait()
                        if run_tab.is_cancelled:
                            _log(f"⚠️ 已中止。完成 {i-1} / {total} 步", "#e66")
                            _done(False)
                            return
                        if run_tab.proc.returncode != 0:
                            _log(f"❌ 步骤 {i} 失败（退出码 {run_tab.proc.returncode}）", "#c05050")
                            _log(f"ℹ️  已完成 {i-1} / {total} 步", "#8a9a7a")
                            _done(False)
                            return
                        _log(f"✅ 步骤 {i} 完成", "#50c870")
                    except Exception as e:
                        _log(f"❌ 步骤 {i} 异常：{e}", "#c05050")
                        _done(False)
                        return
                _log(f"\n🎉 全部 {total} 步执行完毕！", "#50c870")
                _done(True)

            t = _threading.Thread(target=_worker_shell, daemon=True)
            t.start()

        else:
            import sys as _sys
            _EXT   = {"python": ".py", "powershell": ".ps1", "batch": ".bat"}
            _CMD   = {
                "python":     [_sys.executable],
                "powershell": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"],
                "batch":      [],
            }
            ext  = _EXT.get(stype, ".txt")
            cmds = _CMD.get(stype, [])

            def _worker_file(body=content, extension=ext, run_cmd=cmds, typ=stype, script_id=sid):
                try:
                    wd = _sm_workspace_path()
                    tmp_path = _os.path.join(wd, f"script_{script_id}{extension}")
                    with open(tmp_path, "w", encoding="utf-8") as tf:
                        tf.write(body)
                except Exception as e:
                    _log(f"❌ 写脚本文件失败：{e}", "#c05050")
                    _done(False)
                    return

                _log(f"▶  工作区目录：{wd}", "#8a9a7a")
                _log(f"▶  本地源文件：{tmp_path}", "#8a9a7a")

                if typ == "batch":
                    full_cmd = tmp_path
                    use_shell = True
                else:
                    full_cmd = run_cmd + [tmp_path]
                    use_shell = False

                env = _os.environ.copy()
                if typ == "python":
                    env["PYTHONIOENCODING"] = "utf-8"
                    env["PYTHONUTF8"] = "1"

                try:
                    run_tab.proc = _subprocess.Popen(
                        full_cmd, shell=use_shell,
                        stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                        env=env, cwd=wd
                    )
                    for line_bytes in run_tab.proc.stdout:
                        try:
                            line = line_bytes.decode("utf-8")
                        except UnicodeDecodeError:
                            line = line_bytes.decode("gbk", errors="replace")
                        _log(line.rstrip())
                        if run_tab.is_cancelled:
                            break
                    run_tab.proc.wait()
                    if run_tab.is_cancelled:
                        _log("⚠️ 已手动终止运行", "#e66")
                        _done(False)
                        return
                    if run_tab.proc.returncode != 0:
                        _log(f"❌ 执行失败（退出码 {run_tab.proc.returncode}）", "#c05050")
                        _done(False)
                    else:
                        _log("\n🎉 执行完毕！", "#50c870")
                        _done(True)
                except Exception as e:
                    _log(f"❌ 运行异常：{e}", "#c05050")
                    _done(False)

            t = _threading.Thread(target=_worker_file, daemon=True)
            t.start()

    @staticmethod
    def _parse_ansi(text: str, default_fg: str) -> str:
        import html, re
        # 定制化 ANSI 颜色板：抛弃刺眼的终端标准色，改为贴合 OpenHam 主题的暖暗金/复古色系
        C = {
            "30":"#1a1810", "31":"#c05050", "32":"#50c870", "33":"#c09030", 
            "34":"#5882a0", "35":"#a07090", "36":"#509080", "37":"#ede5d0",
            "90":"#7a6a5a", "91":"#d06060", "92":"#7ab86a", "93":"#e0b040", 
            "94":"#aac8e0", "95":"#c080b0", "96":"#70b090", "97":"#ffffff"
        }
        B = {
            "40":"#141210", "41":"#4a2a2a", "42":"#2a4a3a", "43":"#5a4a2a", 
            "44":"#2a3a4a", "45":"#4a3a4a", "46":"#2a4a4a", "47":"#3a3830"
        }
        tokens = re.split(r'\x1b\[([0-9;]*)m', text)
        fg, bg, wt = default_fg, "", "normal"
        out = []
        if tokens[0]: 
            out.append(f'<span style="white-space: pre-wrap; color: {fg};">{html.escape(tokens[0])}</span>')
        for i in range(1, len(tokens), 2):
            for code in tokens[i].split(';'):
                if not code or code == "0": fg, bg, wt = default_fg, "", "normal"
                elif code == "1": wt = "bold"
                elif code in C: fg = C[code]
                elif code in B: bg = B[code]
            if tokens[i+1]:
                h = html.escape(tokens[i+1])
                s = f"white-space: pre-wrap; color: {fg}; font-weight: {wt};"
                if bg: s += f" background-color: {bg};"
                out.append(f'<span style="{s}">{h}</span>')
        return "".join(out)

    def _do_append_log(self, run_tab: _RunTabWidget, text: str, color: str):
        if run_tab and isinstance(run_tab, _RunTabWidget):
            run_tab.append_line(text, color)

    def _set_log_done(self, run_tab: _RunTabWidget, success: bool):
        self.run_finished.emit(run_tab, success)

    def _do_set_log_done(self, run_tab: _RunTabWidget, success: bool):
        if not (run_tab and isinstance(run_tab, _RunTabWidget)):
            return
        run_tab.set_done(success)
        # 更新 Tab 标题 emoji
        idx = self._tab_widget.indexOf(run_tab)
        if idx >= 0:
            old = self._tab_widget.tabText(idx)
            # 剥离旧 emoji 前缀
            name = old
            for prefix in ("⏳ ", "✅ ", "❌ "):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            self._tab_widget.setTabText(idx, ("✅ " if success else "❌ ") + name)

    def _stop_run_timer(self):
        if self._run_timer.isActive():
            self._run_timer.stop()

    def _poll_log(self):
        pass   # 日志已改为线程+singleShot，此处保留备用

    # ── 公开方法 ───────────────────────────────────────────────────────────

    def open(self):
        """弹出浮层并刷新列表。"""
        self._go_list()
        if not self._has_been_shown:
            self._reposition()
        self.show()
        self.raise_()

    def run_trigger(self, trigger: str, silent: bool = False) -> bool:
        """
        按触发命令运行脚本。命中返回 True。
        如果 silent=False，同时弹出日志页；否则后台静默执行。
        供 executor.py 调用（通过 main.py 转发）。
        """
        scripts = _sm_load()
        for s in scripts:
            if s.get("trigger", "").strip() == trigger.strip():
                self._run_by_id(s["id"], silent=silent)
                return True
        return False

    # ── 小工具 ─────────────────────────────────────────────────────────────

    def _show_edit_status(self, msg: str, error: bool = False):
        self._edit_status.setText(msg)
        self._edit_status.setStyleSheet(
            f"color: {'#c05050' if error else '#7ab86a'}; "
            "font-size: 12px; background: transparent; border: none;"
        )
        QTimer.singleShot(2500, lambda: self._edit_status.setText(""))

    @staticmethod
    def _icon_btn(text: str, color: str, tip: str = "") -> QPushButton:
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
    def _input_ss() -> str:
        return """
            QLineEdit, QTextEdit {
                background: #1a1810; color: #ede5d0;
                border: 1px solid rgba(192,140,30,0.28);
                border-radius: 6px; font-size: 13px; padding: 6px 10px;
            }
            QLineEdit:focus, QTextEdit:focus { border-color: rgba(192,140,30,0.65); }
        """

    @staticmethod
    def _action_btn_ss(color: str, bg: str, border: str) -> str:
        return f"""
            QPushButton {{
                background: {bg}; color: {color};
                font-size: 13px; border: 1px solid {border};
                border-radius: 5px; padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {border}; }}
        """

    @staticmethod
    def _type_btn_ss(active: bool) -> str:
        if active:
            return (
                "QPushButton { background: rgba(192,140,30,0.22); color: #c09030; "
                "border: 1px solid rgba(192,140,30,0.55); border-radius: 5px; "
                "font-size: 12px; padding: 4px 10px; }"
            )
        return (
            "QPushButton { background: rgba(30,28,20,0.60); color: #5a4a2a; "
            "border: 1px solid rgba(192,140,30,0.18); border-radius: 5px; "
            "font-size: 12px; padding: 4px 10px; }"
            "QPushButton:hover { color: #9a8040; border-color: rgba(192,140,30,0.35); }"
        )

    _PLACEHOLDERS = {
        "shell": (
            "git -C C:\\ProjectA checkout test\n"
            "git -C C:\\ProjectA pull\n"
            "cd /d C:\\ProjectA && npm run build\n"
            "xcopy /E /Y C:\\ProjectA\\dist C:\\ProjectB\\h5\\"
        ),
        "python": (
            "import os, shutil\n\n"
            "src = r'C:\\ProjectA\\dist'\n"
            "dst = r'C:\\ProjectB\\h5'\n"
            "shutil.copytree(src, dst, dirs_exist_ok=True)\n"
            "print('Done!')"
        ),
        "powershell": (
            "Set-Location C:\\ProjectA\n"
            "git checkout test\n"
            "git pull\n"
            "npm run build\n"
            "Copy-Item -Recurse -Force .\\dist\\* C:\\ProjectB\\h5\\"
        ),
        "batch": (
            "cd /d C:\\ProjectA\r\n"
            "git checkout test\r\n"
            "git pull\r\n"
            "npm run build\r\n"
            "xcopy /E /Y dist C:\\ProjectB\\h5\\"
        ),
    }

    _TYPE_HINT = {
        "shell":      "脚本内容  （每行一条命令，顺序执行，出错即停止）",
        "python":     "脚本内容  （完整 Python 脚本，整体执行）",
        "powershell": "脚本内容  （完整 PowerShell 脚本，整体执行）",
        "batch":      "脚本内容  （完整批处理脚本，整体执行）",
    }

    def _set_script_type(self, stype: str):
        self._current_script_type = stype
        self._highlighter.set_type(stype)
        for tid, btn in self._type_btns.items():
            btn.setStyleSheet(self._type_btn_ss(tid == stype))
            btn.setChecked(tid == stype)
        hint = self._TYPE_HINT.get(stype, "脚本内容")
        self._script_type_lbl.setText(hint)
        # 若编辑框为空则自动填充占位示例
        if not self._script_edit.toPlainText().strip():
            self._script_edit.setPlaceholderText(self._PLACEHOLDERS.get(stype, ""))

    # ── 定位 & 拖拽 ────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._has_been_shown = True

    # ── 定位 & 拖拽 ────────────────────────────────────────────────────────

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        # 居中偏上
        x = (screen.width() - self.width()) // 2
        y = screen.height() // 5
        self.move(x, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.pos().y() <= _SM_SHADOW + self.title_bar.height():
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


