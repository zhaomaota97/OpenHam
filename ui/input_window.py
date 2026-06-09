from PyQt6.QtWidgets import (QWidget, QLineEdit, QLabel, QVBoxLayout,
                             QHBoxLayout, QApplication,
                             QFrame, QLayout,
                             QListWidget, QListWidgetItem, QFileIconProvider)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QFileInfo, QEvent
from PyQt6.QtGui import QKeyEvent, QPixmap
import ctypes
import os
from core.script_engine import evaluate_expr, preview
from utils.window_effects import disable_native_window_effects
from ui import icons
from ui import theme

MAX_LENGTH = 200  # AI 模式下允许输入更长的内容
_SHADOW    = 0           # 无阴影留边，窗口矩形 = 卡片本身
_CARD_W    = 640         # 卡片宽度
_WIN_W     = _CARD_W


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



class InputWindow(QWidget):
    # 提交信号
    submitted = pyqtSignal(str)
    # 文件搜索信号
    search_requested = pyqtSignal(str)
    # 应用搜索信号
    app_search_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._hiding = False
        self._native_effects_disabled = False
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

        # 应用搜索防抖计时器
        self._app_timer = QTimer(self)
        self._app_timer.setSingleShot(True)
        self._app_timer.setInterval(150)
        self._app_timer.timeout.connect(self._emit_app_search)
        self._app_query = ""
        self._app_icon_cache: dict = {}
        self._icon_provider = QFileIconProvider()

        # 启动预热(Pre-warm)解决第一次输入卡顿
        QTimer.singleShot(100, self._pre_warm_caches)
        self._just_shown = False

    def _pre_warm_caches(self):
        """预计算特殊图标的宽幅以触发 Qt 的 Windows 字体回退引擎，同时预加载脚本缓存。"""
        try:
            self.count_label.fontMetrics().horizontalAdvance("↩ ⇥ 📶 🍅 ⚡ 🖥 🐍 🔷 📄 🗑 ✎ ℹ️")
            from core.script_engine import _sm_load_scripts
            _sm_load_scripts()
        except:
            pass

    def _on_focus_window_changed(self, focus_window):
        """焦点切换到本窗口之外时隐藏"""
        if getattr(self, "_just_shown", False):
            return
        if self.isVisible() and not self._hiding:
            if focus_window is None or focus_window != self.windowHandle():
                self.hide_window()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        # 必须保留：使卡片 border-radius 圆角区域真正透明（DWM 合成）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setFixedWidth(_WIN_W)
        
        

    def _build_ui(self):
        # 外层无留边，窗口矩形 = 卡片本身
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # 让窗口高度始终自动贴合内容（结果区出现时撑高，消失后自动缩回）
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        # ── 卡片 ──────────────────────────────────────────
        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setFixedWidth(_CARD_W)
        self.card.setStyleSheet(f"""
            #card {{
                background-color: {theme.CARD};
                border-radius: {theme.R_CARD}px;
                border: 1px solid {theme.BORDER};
            }}
            QLineEdit {{
                background: transparent;
                color: {theme.TEXT};
                border: none;
                font-size: 20px;
                selection-background-color: {theme.ACCENT};
                selection-color: #ffffff;
            }}
            QLabel {{
                background: transparent;
                color: {theme.TEXT2};
                font-size: 12px;
            }}
            QTextEdit {{
                background: transparent;
                border: none;
                color: {theme.TEXT};
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: #c7c7cc;
                border-radius: 3px;
                min-height: 20px;
            }}
        """)

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
        # 拦截 ←/→：应用启动器模式下用于左右切换卡片（否则会被 QLineEdit 用于移动光标）
        self.input.installEventFilter(self)
        input_row.addWidget(self.input)
        card_layout.addLayout(input_row)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            f"background: {theme.BORDER}; "
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
        self.file_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
                padding: 2px 0;
            }}
            QListWidget::item {{
                color: {theme.TEXT};
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background: {theme.ACCENT_SOFT};
            }}
            QListWidget::item:hover:!selected {{
                background: {theme.SUBTLE};
            }}
        """)
        self.file_list.hide()
        self.file_list.itemDoubleClicked.connect(
            lambda item: self._open_file_at_row(self.file_list.row(item))
        )
        card_layout.addWidget(self.file_list)

        # 应用启动器：横排卡片（默认隐藏）
        self.app_list = QListWidget()
        self.app_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.app_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.app_list.setFlow(QListWidget.Flow.LeftToRight)
        self.app_list.setWrapping(False)
        self.app_list.setMovement(QListWidget.Movement.Static)
        self.app_list.setUniformItemSizes(True)
        self.app_list.setIconSize(QSize(36, 36))
        self.app_list.setSpacing(2)
        self.app_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.app_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.app_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
                padding: 2px 0;
            }}
            QListWidget::item {{
                color: {theme.TEXT};
                border-radius: 8px;
                padding: 4px 0;
            }}
            QListWidget::item:selected {{
                background: {theme.ACCENT_SOFT};
                color: {theme.TEXT};
            }}
            QListWidget::item:hover:!selected {{
                background: {theme.SUBTLE};
            }}
            QScrollBar:horizontal {{
                border: none;
                background: transparent;
                height: 5px;
            }}
            QScrollBar::handle:horizontal {{
                background: #c7c7cc;
                border-radius: 2px;
                min-width: 24px;
            }}
        """)
        self.app_list.hide()
        self.app_list.itemDoubleClicked.connect(
            lambda item: self._launch_app_at_row(self.app_list.row(item))
        )
        card_layout.addWidget(self.app_list)

        from PyQt6.QtWidgets import QTextEdit
        self.ai_label = QTextEdit()
        self.ai_label.setReadOnly(True)
        self.ai_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ai_label.setFrameShape(QFrame.Shape.NoFrame)
        self.ai_label.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.ai_label.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ai_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; line-height: 1.6;")
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

    def _sync_ai_zone(self, show: bool = True):
        """同步布局并决定是否展示"""
        if not show:
            self.ai_label.hide()
            return
            
        doc = self.ai_label.document()
        doc.setTextWidth(580)
        h = int(doc.size().height())
        target = min(h + 16, 450)
        
        self.ai_label.setFixedHeight(target)
        self.ai_label.show()

    def _on_text_changed(self, text: str):
        count = len(text)
        stripped = text.lstrip()

        # ――― 文件搜索模式：以 "找 " 开头 ―――――――――――――――――――――――――――――――――――――
        if stripped.startswith("找 "):
            query = stripped[2:].strip()
            self._eval_timer.stop()
            self._dot_timer.stop()
            self._app_timer.stop()
            self.clear_app_results()
            self.ai_label.setText("")
            self._sync_ai_zone(show=False)
            self.clear_qr()
            self.count_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 12px;")
            self.count_label.setText(icons.richify("≡ 文件搜索"))
            self.result_label.setText("")
            if query:
                self._search_query = query
                self.result_label.setText("搜索中…")
                self.result_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
                self._search_timer.start()
            else:
                self._search_timer.stop()
                self.clear_file_results()
            self._refit()
            return

        # ─── 非文件搜索模式：清除文件列表和二维码 ─────────────────────
        if self.file_list.isVisible() or self.qr_label.isVisible():
            self._search_timer.stop()
            self.clear_file_results()
            self.clear_qr()

        # 接近上限变红提示
        if count >= MAX_LENGTH * 0.9:
            self.count_label.setStyleSheet(f"color: {theme.DANGER}; font-size: 12px;")
        else:
            self.count_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        # 指令预览立即响应（无需计算，直接字典查找）
        cmd_preview = preview(text)
        self._auto_complete_target = None
        
        if cmd_preview is not None:
            cmd_preview = icons.strip(cmd_preview)
            fm = self.count_label.fontMetrics()
            elided = fm.elidedText(cmd_preview, Qt.TextElideMode.ElideRight, 500)
            self.count_label.setText(elided)
            self.count_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 12px;")
            self.result_label.setText("")
            self._eval_timer.stop()
            self._app_timer.stop()
            self.clear_app_results()
        else:
            from core.script_engine import get_autocomplete
            ac = get_autocomplete(text)
            if ac:
                target, desc = ac
                self._auto_complete_target = target
                raw_txt = f"按 Tab 补全: {target}  ({desc})" if desc else f"按 Tab 补全: {target}"
                fm = self.count_label.fontMetrics()
                self.count_label.setText(icons.img("tab") + " "
                                         + fm.elidedText(raw_txt, Qt.TextElideMode.ElideRight, 500))
                self.count_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
            else:
                if text.strip():
                    fm = self.count_label.fontMetrics()
                    self.count_label.setText(icons.img("enter") + " "
                                             + fm.elidedText("询问 AI", Qt.TextElideMode.ElideRight, 500))
                    self.count_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 13px;")
                else:
                    self.count_label.setText(f"{count} / {MAX_LENGTH}")
            self.result_label.setText("")
            if text.strip():
                self._eval_timer.start()
                # 应用模糊匹配（短 token，避免对长句/中文提问做无谓搜索）
                q = text.strip()
                if len(q) <= 30 and "\n" not in q:
                    self._app_query = q
                    self._app_timer.start()
                else:
                    self._app_timer.stop()
                    self.clear_app_results()
            else:
                self._eval_timer.stop()
                self._app_timer.stop()
                self.clear_app_results()

    def _refit(self):
        """重新贴合窗口尺寸。配合主布局的 SetFixedSize 约束，
        撑高与缩回都生效（隐藏子控件后需 activate() 才会缩小，
        单纯 adjustSize() 在缩小方向无效）。"""
        lay = self.layout()
        if lay is not None:
            # invalidate() 强制作废缓存尺寸：hide() 的布局失效是异步排队的，
            # 紧接着同步 activate() 会沿用旧尺寸导致缩不回去。
            lay.invalidate()
            lay.activate()

    def _run_evaluate(self):
        """防抖结束后执行表达式求值。"""
        text = self.input.text()
        expr_result = evaluate_expr(text)
        if expr_result is not None:
            self.result_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 12px;")
            self.result_label.setText(expr_result)
        else:
            self.result_label.setText("")

    def eventFilter(self, obj, event):
        # 应用启动器模式下，用 ←/→ 在卡片间移动（拦截 QLineEdit 的光标移动）
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if self.app_list.isVisible() and self.app_list.count() > 0:
                key = event.key()
                if key == Qt.Key.Key_Left:
                    self._move_app_selection(-1)
                    return True
                if key == Qt.Key.Key_Right:
                    self._move_app_selection(1)
                    return True
        return super().eventFilter(obj, event)

    def _move_app_selection(self, delta: int):
        row = self.app_list.currentRow()
        new_row = max(0, min(self.app_list.count() - 1, row + delta))
        self.app_list.setCurrentRow(new_row)
        item = self.app_list.currentItem()
        if item:
            self.app_list.scrollToItem(item)

    def keyPressEvent(self, event: QKeyEvent):
        file_mode = self.file_list.isVisible() and self.file_list.count() > 0
        app_mode = self.app_list.isVisible() and self.app_list.count() > 0

        # 补全功能
        if event.key() == Qt.Key.Key_Tab:
            if getattr(self, "_auto_complete_target", None):
                self.input.setText(self._auto_complete_target)
                self._auto_complete_target = None
                # 跳到末尾方便接着回车或修改
                self.input.setCursorPosition(len(self.input.text()))
            return

        # 回车提交（不立刻清空，等 AI 回答后再清空）
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            # 应用启动器：Enter 启动选中应用；Shift+Enter 改为问 AI
            if app_mode and not shift:
                row = self.app_list.currentRow()
                self._launch_app_at_row(row if row >= 0 else 0)
                return
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
        current = self.ai_label.toPlainText()
        # 移除动画占位
        for frame in ("正在思考", "正在思考 ·", "正在思考 · ·", "正在思考 · · ·"):
            if current == frame:
                current = ""
                break
        if current.endswith("▌"):
            current = current[:-1]
        self.ai_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; line-height: 1.6;")
        self.ai_label.setText(current + text + "▌")
        self._sync_ai_zone()
        self._refit()
        if not self.isVisible():
            print("[UI] 窗口不可见，重新 show_window")
            self.show_window()

    def finish_ai_stream(self):
        """流式结束：停止动画，移除 ▌ 光标，清空输入框。"""
        self._dot_timer.stop()
        current = self.ai_label.toPlainText()
        if current.endswith("▌"):
            self.ai_label.setText(current[:-1])
        self._refit()
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
        self.clear_app_results()
        self.ai_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 13px;")
        self.ai_label.setText("正在思考")
        self._sync_ai_zone()
        self._refit()
        self._dot_timer.start()

    def show_ai_result(self, text: str):
        """AI 回答完成（错误分支），展示结果并清空输入框。"""
        print(f"[UI] show_ai_result 被调用，内容: {text[:60]}...")
        self._dot_timer.stop()
        self.clear_qr()
        self.clear_app_results()
        color = theme.DANGER if text.startswith("❌") else theme.TEXT
        self.ai_label.setStyleSheet(
            f"color: {color}; font-size: 13px; line-height: 1.6;"
        )
        self.ai_label.setText(icons.richify(text))
        self._sync_ai_zone()
        self._refit()
        self.input.clear()
        if not self.isVisible():
            print("[UI] 窗口不可见，重新 show_window")
            self.show_window()

    def show_result(self, result: str):
        """预设指令执行结果：✅ 金绿色，❌ 红色，显示于右侧，同时清空输入框和 AI 区域。"""
        if result.startswith("✅"):
            color = theme.SUCCESS
        else:
            color = theme.DANGER
        self.count_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.count_label.setText(icons.richify(result))
        self.result_label.setText("")
        self.input.clear()
        # 清空上次 AI 回答和 QR
        self._dot_timer.stop()
        self.ai_label.setText("")
        self._sync_ai_zone(show=False)
        self.clear_qr()
        self.clear_app_results()
        self._refit()

    def show_window(self):
        # 居中显示
        screen = self.screen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = screen.height() // 3
        self.move(x, y)
        self._just_shown = True
        self.show()
        if not self._native_effects_disabled:
            disable_native_window_effects(int(self.winId()))
            self._native_effects_disabled = True
        self.raise_()
        # 延迟激活，确保窗口完全渲染后再抢夺焦点（解决 Windows 下 Tool 窗口无法获得输入的问题）
        QTimer.singleShot(50, self._force_focus)
        QTimer.singleShot(500, self._clear_just_shown)

    def _clear_just_shown(self):
        self._just_shown = False

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
        self.clear_app_results()
        self.ai_label.setStyleSheet(
            f"color: {theme.TEXT}; font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; line-height: 1.8;"
        )
        rich = icons.richify(text)
        if "<img" in rich:        # 转成富文本后换行会塌缩，需显式 <br>
            rich = rich.replace("\n", "<br>")
        self.ai_label.setText(rich)
        self._sync_ai_zone()
        self.input.clear()
        self._refit()

    def show_qr(self, png_bytes: bytes):
        """展示二维码图片（清除其他结果区域）。"""
        self._dot_timer.stop()
        self.ai_label.setText("")
        self._sync_ai_zone(show=False)
        self.clear_file_results()
        self.clear_app_results()
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
        self.count_label.setStyleSheet(f"color: {theme.SUCCESS}; font-size: 12px;")
        self.result_label.setText("")
        self._refit()

    def clear_qr(self):
        """TODO: 隐藏并清除二维码图片。"""
        self.qr_label.clear()
        self.qr_label.hide()

    def _emit_search(self):
        self.search_requested.emit(self._search_query)

    def show_file_results(self, results: list):
        self.file_list.clear()
        if not results:
            self.result_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
            self.result_label.setText("未找到文件")
            self.file_list.hide()
        else:
            self.result_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
            self.result_label.setText(icons.richify(f"找到 {len(results)} 个  ↵打开  Ctrl+↵打开文件夹"))
            for r in results:
                self._add_file_item(r['name'], r['path'], r['dir'])
            item_h = 48
            max_visible = 5
            total_h = len(results) * item_h + 4
            self.file_list.setFixedHeight(min(total_h, max_visible * item_h + 4))
            self.file_list.setCurrentRow(0)
            self.file_list.show()
        self._refit()

    def clear_file_results(self):
        self.file_list.clear()
        self.file_list.hide()
        self._refit()

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
        name_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        dir_lbl = QLabel(directory)
        dir_lbl.setStyleSheet(f"color: {theme.TEXT2}; font-size: 10px; background: transparent;")
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

    # ─── 应用启动器相关 ───────────────────────────────────────────────────

    def _emit_app_search(self):
        self.app_search_requested.emit(self._app_query)

    def _app_icon(self, path: str):
        """提取并缓存应用图标（QFileIconProvider 解析快捷方式的真实图标）。"""
        icon = self._app_icon_cache.get(path)
        if icon is None:
            try:
                icon = self._icon_provider.icon(QFileInfo(path))
            except Exception:
                icon = None
            self._app_icon_cache[path] = icon
        return icon

    def show_app_results(self, results: list):
        """展示横排应用卡片。results: [{'name', 'path'}]。"""
        self.app_list.clear()
        if not results:
            self.app_list.hide()
            self._refit()
            return
        for r in results:
            item = QListWidgetItem(r["name"])
            item.setData(Qt.ItemDataRole.UserRole, r["path"])
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            item.setToolTip(r["name"])
            icon = self._app_icon(r["path"])
            if icon is not None:
                item.setIcon(icon)
            item.setSizeHint(QSize(96, 76))
            self.app_list.addItem(item)
        self.app_list.setFixedHeight(92)
        self.app_list.setCurrentRow(0)
        self.app_list.show()
        # 提示并入右侧原有提示位（不再占用左侧独立说明行），沿用蓝灰提示色
        self.count_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 13px;")
        _hint = "← → 选择   ↵ 启动   ⇧↵ 问 AI"
        _hint = _hint.replace("←", icons.img("back")).replace("→", icons.img("forward"))
        self.count_label.setText(icons.richify(_hint))
        self._refit()

    def clear_app_results(self):
        if self.app_list.count() or self.app_list.isVisible():
            self.app_list.clear()
            self.app_list.hide()
            self._refit()

    def _launch_app_at_row(self, row: int):
        if row < 0 or row >= self.app_list.count():
            return
        item = self.app_list.item(row)
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and os.path.exists(path):
                try:
                    os.startfile(path)
                except Exception as e:
                    print(f"[应用启动] 失败: {e}")
                self.hide_window()
