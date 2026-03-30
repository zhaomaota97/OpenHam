from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QFont
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


