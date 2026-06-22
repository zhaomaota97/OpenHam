import os
import ctypes
import ctypes.wintypes
from PyQt6.QtWidgets import (QWidget, QVBoxLayout,
                              QApplication, QHBoxLayout, QLabel, QPushButton, QSizeGrip)
from PyQt6.QtCore import Qt, QObject, QEvent
from PyQt6.QtGui import QIcon
from utils.window_effects import disable_native_window_effects
from ui import icons
from ui import theme


class _TitleBarDblClick(QObject):
    """只负责「双击标题栏 → 最大化/还原」。用独立过滤器对象而非把窗口自身装成过滤器——
    后者会让事件经过子类重写的 eventFilter，而那在基类构造期(子类控件尚未建好)就被触发，
    导致 AttributeError 把整个程序拖崩(v1.0.57 的回归)。独立对象彻底隔离这条路径。"""

    def __init__(self, win):
        super().__init__(win)
        self._win = win

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self._win.toggle_max()
            return True
        return False


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
        self.card.setStyleSheet(f"""
            #card {{
                background-color: {theme.CARD};
                border-radius: {theme.R_CARD}px;
                border: 1px solid {theme.BORDER};
            }}
        """)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)

        # ── 标题栏 ────────────────────────────────────────────────
        self.title_bar = QWidget()
        self.title_bar.setObjectName("baseTitleBar")
        self.title_bar.setStyleSheet(f"""
            #baseTitleBar {{
                background-color: {theme.CARD};
                border-radius: {theme.R_CARD}px {theme.R_CARD}px 0 0;
                border-bottom: 1px solid {theme.BORDER};
            }}
        """)
        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(16, 9, 12, 9)
        tb.setSpacing(10)

        self.title_lbl = QLabel(icons.richify(title))
        self.title_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;"
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
        self.pin_btn = QPushButton()
        self.pin_btn.setIcon(icons.qicon("pin", color=theme.TEXT2))
        self.pin_btn.setFixedSize(28, 28)
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin_btn.setToolTip("始终显示在最前 / 取消固定")
        self.pin_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 7px;
            }}
            QPushButton:hover {{ background: {theme.HOVER}; }}
        """)
        self.pin_btn.clicked.connect(self.toggle_pin)
        tb.addWidget(self.pin_btn)

        _tool_qss = (f"QPushButton {{ background: transparent; border: none;"
                     f" border-radius: 7px; }}"
                     f"QPushButton:hover {{ background: {theme.HOVER}; }}")

        # 最小化按钮
        self.min_btn = QPushButton()
        self.min_btn.setIcon(icons.qicon("minimize", color=theme.TEXT2))
        self.min_btn.setFixedSize(28, 28)
        self.min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.min_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.min_btn.setToolTip("最小化")
        self.min_btn.setStyleSheet(_tool_qss)
        self.min_btn.clicked.connect(self.showMinimized)
        tb.addWidget(self.min_btn)

        # 最大化 / 还原按钮
        self.max_btn = QPushButton()
        self.max_btn.setIcon(icons.qicon("maximize", color=theme.TEXT2))
        self.max_btn.setFixedSize(28, 28)
        self.max_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.max_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.max_btn.setToolTip("最大化 / 还原")
        self.max_btn.setStyleSheet(_tool_qss)
        self.max_btn.clicked.connect(self.toggle_max)
        tb.addWidget(self.max_btn)

        # 关闭按钮
        self.close_btn = QPushButton()
        self.close_btn.setIcon(icons.qicon("close", color=theme.TEXT2))
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 7px;
            }}
            QPushButton:hover {{ background: rgba(255,59,48,0.12); }}
        """)
        self.close_btn.clicked.connect(self.hide_window)
        tb.addWidget(self.close_btn)

        self.card_layout.addWidget(self.title_bar)
        # 双击标题栏：最大化 / 还原（所有继承本基类的窗口统一具备）。
        # 用独立过滤器对象，绝不经过子类的 eventFilter（见 _TitleBarDblClick 注释）。
        self._title_dbl_filter = _TitleBarDblClick(self)
        self.title_bar.installEventFilter(self._title_dbl_filter)

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
        self.pin_btn.setIcon(icons.qicon("pinned" if self.is_pinned else "pin",
                                         color=theme.ACCENT if self.is_pinned else theme.TEXT2))

    def toggle_max(self):
        """最大化 / 还原（无边框窗口同样适用）。"""
        if self.isMaximized():
            self.showNormal()
            self.max_btn.setIcon(icons.qicon("maximize", color=theme.TEXT2))
        else:
            self.showMaximized()
            self.max_btn.setIcon(icons.qicon("restore", color=theme.TEXT2))

    def flash_taskbar(self, count: int = 6):
        """收到新消息时像微信一样闪烁任务栏图标提醒；窗口已在前台则不闪。"""
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
            fg = user32.GetForegroundWindow()
            if fg is not None and int(fg) == hwnd and self.isActiveWindow():
                return
            class _FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.wintypes.HWND),
                            ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                            ("dwTimeout", ctypes.c_uint)]
            FLASHW_TRAY, FLASHW_TIMERNOFG = 0x2, 0xC   # 闪任务栏，直到窗口被切到前台
            info = _FLASHWINFO(ctypes.sizeof(_FLASHWINFO), ctypes.wintypes.HWND(hwnd),
                               FLASHW_TRAY | FLASHW_TIMERNOFG, count, 0)
            user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass

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
