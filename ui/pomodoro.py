from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QColor, QPainter, QFont
from ui import icons
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
        # 背景圆角矩形（浅色毛玻璃感）
        from PyQt6.QtGui import QPen
        p.setBrush(QColor(255, 255, 255, 240))
        p.setPen(QPen(QColor(0, 0, 0, 26), 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 13, 13)
        # 番茄图标 + 时间文字（图标替代原先的 🍅 emoji）
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        p.setFont(font)
        txt = icons.strip(self._text)
        pm = icons.qicon("tomato").pixmap(QSize(26, 26))
        icon_w = pm.width() if not pm.isNull() else 0
        gap = 8 if icon_w else 0
        tw = p.fontMetrics().horizontalAdvance(txt)
        x0 = (self.width() - (icon_w + gap + tw)) // 2
        if icon_w:
            p.drawPixmap(x0, (self.height() - pm.height()) // 2, pm)
        p.setPen(QColor("#1d1d1f"))
        p.drawText(QRect(x0 + icon_w + gap, 0, tw + 6, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
        p.end()


