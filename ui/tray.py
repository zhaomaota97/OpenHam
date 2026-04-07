import os
import subprocess
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush
from utils.paths import _base_dir

def _show_toast(title: str, message: str):
    """PowerShell balloon tip — Windows 10/11 最可靠的气泡通知方式。"""
    safe_t = title.replace('"', "'")
    safe_m = message.replace('"', "'")
    script = (
        'Add-Type -AssemblyName System.Windows.Forms; '
        '$n = New-Object System.Windows.Forms.NotifyIcon; '
        '$n.Icon = [System.Drawing.SystemIcons]::Information; '
        '$n.Visible = $true; '
        f'$n.ShowBalloonTip(8000,"{safe_t}","{safe_m}",'
        '[System.Windows.Forms.ToolTipIcon]::Info); '
        'Start-Sleep 9; $n.Dispose()'
    )
    subprocess.Popen(
        ['powershell', '-WindowStyle', 'Hidden', '-NoProfile', '-Command', script],
        creationflags=subprocess.CREATE_NO_WINDOW
    )

def _make_tray_icon() -> QIcon:
    logo_path = os.path.join(_base_dir(), "logo.png")
    if os.path.exists(logo_path):
        from PyQt6.QtCore import Qt
        pixmap = QPixmap(logo_path)
        # 平滑缩放消除硬截图产生的毛边现象
        pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return QIcon(pixmap)
    size = 64
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#c08020")))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawEllipse(4, 4, size - 8, size - 8)
    painter.end()
    return QIcon(px)
