import os
import ctypes
import ctypes.wintypes
from PyQt6.QtWidgets import (QWidget, QVBoxLayout,
                              QApplication, QHBoxLayout, QLabel, QPushButton, QSizeGrip)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from utils.window_effects import disable_native_window_effects

def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Windows SetWindowPos constants
_HWND_TOPMOST   = ctypes.wintypes.HWND(-1)
_HWND_NOTOPMOST = ctypes.wintypes.HWND(-2)
_SWP_NOMOVE     = 0x0002
_SWP_NOSIZE     = 0x0001
_SWP_NOACTIVATE = 0x0010

def _set_topmost_native(hwnd: int, topmost: bool):
    """直接调用 Win32 SetWindowPos 切换置顶，完全不重建窗口，零闪烁。"""
    try:
        after = _HWND_TOPMOST if topmost else _HWND_NOTOPMOST
        ctypes.windll.user32.SetWindowPos(
            hwnd, after, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
        )
    except Exception:
        pass


class OpenHamWindowBase(QWidget):
    """
    通用 OpenHam 弹窗父类。
    提供：黑金玻璃外壳、发散阴影、无边框拖拽、缩放、
    置顶（无闪烁 Win32 API）、任务栏图标及注入式子类标题按钮区。
    """

    def __init__(self, title: str = "", shadow_size: int = 0,
                 min_w: int = 600, min_h: int = 400):
        super().__init__()

        # Qt.WindowType.Window  → 在任务栏出现
        # FramelessWindowHint   → 去掉系统标题栏
        # WindowStaysOnTopHint  → 初始置顶（可通过 toggle_pin 切换）
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        # 必须保留：使卡片 border-radius 圆角区域真正透明（DWM 合成）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setObjectName("OpenHamWindowBase")
        self.setStyleSheet("#OpenHamWindowBase { background: transparent; }")

        self.setMinimumWidth(min_w)
        self.setMinimumHeight(min_h)
        

        # 任务栏标题 & 图标
        self.setWindowTitle(title)
        logo = os.path.join(_base_dir(), "logo.png")
        if os.path.exists(logo):
            self.setWindowIcon(QIcon(logo))

        self.shadow_size = 0
        self._native_effects_disabled = False
        self._drag_pos = None
        self.is_pinned = False   # 默认不置顶

        # ── 外层布局 ─────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 卡片 ──────────────────────────────────────────────────
        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setStyleSheet("""
            #card {
                background-color: #1e1c14;
                border-radius: 10px;
                border: 1px solid rgba(192, 140, 30, 0.45);
            }
        """)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)

        # ── 标题栏 ────────────────────────────────────────────────
        self.title_bar = QWidget()
        self.title_bar.setObjectName("baseTitleBar")
        self.title_bar.setStyleSheet("""
            #baseTitleBar {
                background-color: #272416;
                border-radius: 10px 10px 0 0;
                border-bottom: 1px solid rgba(192, 140, 30, 0.22);
            }
        """)
        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(16, 9, 12, 9)
        tb.setSpacing(10)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            "color: #c09030; font-size: 15px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        tb.addWidget(self.title_lbl)

        # 子类工具注入区
        self.header_tools_layout = QHBoxLayout()
        self.header_tools_layout.setSpacing(8)
        self.header_tools_layout.setContentsMargins(0, 0, 0, 0)
        tb.addLayout(self.header_tools_layout)

        tb.addStretch()

        # 固定按钮
        self.pin_btn = QPushButton("📍")
        self.pin_btn.setFixedSize(30, 30)
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin_btn.setToolTip("始终显示在最前 / 取消固定")
        self.pin_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #7a6a4a;
                font-size: 14px; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: rgba(192, 140, 30, 0.20); color: #fff; }
        """)
        self.pin_btn.clicked.connect(self.toggle_pin)
        tb.addWidget(self.pin_btn)

        # 关闭按钮
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #7a6a4a;
                font-size: 16px; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: rgba(180, 50, 30, 0.60); color: #fff; }
        """)
        self.close_btn.clicked.connect(self.hide_window)
        tb.addWidget(self.close_btn)

        self.card_layout.addWidget(self.title_bar)

        # ── 内容区（子类填充） ─────────────────────────────────────
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self.card_layout.addLayout(self.content_layout, 1)

        # ── 右下角缩放手柄 ────────────────────────────────────────
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(14, 14)
        self.size_grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(self.size_grip)
        self.card_layout.addLayout(grip_row)

        outer.addWidget(self.card)

    # ── 公共方法 ──────────────────────────────────────────────────

    def toggle_pin(self):
        """零闪烁切换置顶：直接用 Win32 SetWindowPos，不重建窗口。"""
        self.is_pinned = not self.is_pinned
        _set_topmost_native(int(self.winId()), self.is_pinned)
        self.pin_btn.setText("📌" if self.is_pinned else "📍")

    def hide_window(self):
        self.hide()

    def show_window_centered(self, base_width: int = 0, base_height: int = 0):
        screen = QApplication.primaryScreen().availableGeometry()
        x = (screen.width()  - self.width())  // 2
        y = max(50, (screen.height() - self.height()) // 2 - 50)
        self.move(x, y)
        self.show()
        self._apply_native_window_state()

    def _apply_native_window_state(self):
        hwnd = int(self.winId())
        _set_topmost_native(hwnd, self.is_pinned)
        if not self._native_effects_disabled:
            disable_native_window_effects(hwnd)
            self._native_effects_disabled = True

    # ── 拖拽 ──────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()
