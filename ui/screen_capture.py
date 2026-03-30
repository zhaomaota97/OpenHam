from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap

class ScreenCaptureOverlay(QWidget):
    capture_finished = pyqtSignal(QPixmap)
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._start_pos = None
        self._current_pos = None
        self._bg_pixmap = None
        
    def start_capture(self):
        screen = QApplication.primaryScreen()
        self._bg_pixmap = screen.grabWindow(0)
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        
    def paintEvent(self, event):
        if not self._bg_pixmap:
            return
            
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg_pixmap)
        
        overlay_color = QColor(0, 0, 0, 120)
        p.fillRect(self.rect(), overlay_color)
        
        if self._start_pos and self._current_pos:
            r = QRect(self._start_pos, self._current_pos).normalized()
            clear_pm = self._bg_pixmap.copy(r)
            p.drawPixmap(r.topLeft(), clear_pm)
            
            p.setPen(QPen(QColor(192, 140, 30), 2))
            p.drawRect(r)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_pos = event.pos()
            self._current_pos = self._start_pos
            self.update()
            
    def mouseMoveEvent(self, event):
        if self._start_pos:
            self._current_pos = event.pos()
            self.update()
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._start_pos and self._current_pos:
            r = QRect(self._start_pos, self._current_pos).normalized()
            if r.width() > 10 and r.height() > 10:
                pm = self._bg_pixmap.copy(r)
                self.hide()
                self._start_pos = None
                self._current_pos = None
                self.capture_finished.emit(pm)
            else:
                self.hide()
                self._start_pos = None
                self._current_pos = None
        elif event.button() == Qt.MouseButton.RightButton:
            self.hide()
            self._start_pos = None
            self._current_pos = None
            
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self._start_pos = None
            self._current_pos = None
