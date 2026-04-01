from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGraphicsDropShadowEffect, QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

class OpenHamWindowBase(QWidget):
    """
    通用 OpenHam 弹窗父类，封装了黑金玻璃半透明的外边框、发散阴影以及无边框底层逻辑。
    """
    def __init__(self, title: str = "", shadow_size: int = 10, min_w: int = 600, min_h: int = 400):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(min_w + shadow_size * 2)
        self.setMinimumHeight(min_h + shadow_size * 2)
        
        self.shadow_size = shadow_size
        self._drag_pos = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(shadow_size, shadow_size, shadow_size, shadow_size)
        outer.setSpacing(0)

        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setStyleSheet("""
            #card {
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
        self.card.setGraphicsEffect(shadow)

        self.content_layout = QVBoxLayout(self.card)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        outer.addWidget(self.card)

    def show_window_centered(self, base_width, base_height):
        screen = QApplication.primaryScreen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = max(50, (screen.height() - self.height()) // 2 - 50)
        self.move(x, y)
        self.show()

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
