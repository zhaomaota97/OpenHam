from PyQt6.QtWidgets import (QWidget, QLineEdit, QLabel, QVBoxLayout,
                             QHBoxLayout, QApplication,
                             QGraphicsDropShadowEffect, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QKeyEvent, QColor
import ctypes
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

class InputWindow(QWidget):
    # 提交信号
    submitted = pyqtSignal(str)

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

        outer.addWidget(self.card)

    def _on_text_changed(self, text: str):
        count = len(text)
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
        # 回车提交（不立刻清空，等 AI 回答后再清空）
        if event.key() == Qt.Key.Key_Return:
            text = self.input.text().strip()
            if text:
                # 记录历史（去重，新的放末尾）
                if not self._history or self._history[-1] != text:
                    self._history.append(text)
                self._history_idx = -1
                self.submitted.emit(text)
        # ↑ 键：向上翻历史
        elif event.key() == Qt.Key.Key_Up:
            if self._history:
                if self._history_idx == -1:
                    self._history_idx = len(self._history) - 1
                elif self._history_idx > 0:
                    self._history_idx -= 1
                self.input.setText(self._history[self._history_idx])
                self.input.end(False)  # 光标移到末尾
        # ↓ 键：向下翻历史
        elif event.key() == Qt.Key.Key_Down:
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
        self.ai_label.setStyleSheet("color: #8a7040; font-size: 13px;")
        self.ai_label.setText("正在思考")
        self.ai_label.show()
        self.adjustSize()
        self._dot_timer.start()

    def show_ai_result(self, text: str):
        """AI 回答完成（错误分支），展示结果并清空输入框。"""
        print(f"[UI] show_ai_result 被调用，内容: {text[:60]}...")
        self._dot_timer.stop()
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
        # 清空上次 AI 回答
        self._dot_timer.stop()
        self.ai_label.setText("")
        self.ai_label.hide()
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
        self.hide()
        self._hiding = False
