import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QListWidgetItem,
                             QGraphicsDropShadowEffect, QScrollArea, QLineEdit, QDialog)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QCursor
import ctypes

from core.plugin_manager import (ALL_PLUGINS_META, get_plugin_config, 
                                 save_plugin_config, reload_plugins)
from utils.paths import _base_dir

_SHADOW = 20
_PM_CARD_W = 600
_PM_CARD_H = 700

def _win_force_foreground(hwnd: int):
    """强制获取焦点的系统级钩子"""
    try:
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
    except Exception:
        pass


class ToggleSwitch(QPushButton):
    """简易的滑动开关 UI"""
    def __init__(self, checked=True, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(checked)
        self.toggled.connect(self._update_style)
        self._update_style(self.isChecked())

    def _update_style(self, checked):
        if checked:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #c08c1e;
                    border-radius: 11px;
                }
            """)
            self.setText("ON")
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #3f3522;
                    border-radius: 11px;
                    color: #706550;
                }
            """)
            self.setText("OFF")
        f = self.font()
        f.setPixelSize(10)
        f.setBold(True)
        self.setFont(f)


class PluginItemWidget(QWidget):
    """插件列表每一行的渲染器"""
    changed = pyqtSignal()
    
    def __init__(self, plugin_id: str, meta: dict, conf: dict, parent=None):
        super().__init__(parent)
        self.plugin_id = plugin_id
        self._setup_ui(meta, conf)
        
    def _setup_ui(self, meta: dict, conf: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Top row: Title and Switch
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        
        raw_desc = meta.get("desc", "").strip()
        display_title = raw_desc if raw_desc else meta.get("func_name", "Unknown Plugin")
        title_lbl = QLabel(display_title)
        title_lbl.setStyleSheet("color: #d8cfb8; font-size: 15px; font-weight: bold;")
        
        display_sub = meta.get("module_name", meta.get("func_name", ""))
        desc_lbl = QLabel(display_sub)
        desc_lbl.setStyleSheet("color: #8a7040; font-size: 12px;")
        
        enabled = conf.get("enabled", True)
        self.toggle = ToggleSwitch(enabled)
        self.toggle.toggled.connect(lambda: self.changed.emit())
        
        top_row.addWidget(title_lbl)
        top_row.addWidget(desc_lbl, 1)
        top_row.addWidget(self.toggle)
        
        layout.addLayout(top_row)
        
        # Bottom row: Triggers
        bot_row = QHBoxLayout()
        alias_lbl = QLabel("触发命令:")
        alias_lbl.setStyleSheet("color: #a89f8a; font-size: 12px;")
        
        # Retrieve active triggers avoiding reference mutation during load.
        triggers = conf.get("triggers", meta.get("default_triggers", []))
        trigger_str = ", ".join(triggers)
        
        self.trigger_input = QLineEdit(trigger_str)
        self.trigger_input.setStyleSheet("""
            QLineEdit {
                background: #2a251a;
                border: 1px solid #4a3f2a;
                border-radius: 4px;
                color: #c08c1e;
                padding: 4px;
            }
            QLineEdit:focus {
                border: 1px solid #c08c1e;
            }
        """)
        self.trigger_input.editingFinished.connect(lambda: self.changed.emit())
        
        bot_row.addWidget(alias_lbl)
        bot_row.addWidget(self.trigger_input, 1)
        
        layout.addLayout(bot_row)
        
    def get_data(self):
        """返回此插件最新的 config 持久化字典"""
        raw_triggers = self.trigger_input.text().split(",")
        triggers = [t.strip() for t in raw_triggers if t.strip()]
        return {
            "enabled": self.toggle.isChecked(),
            "triggers": triggers
        }


class PluginManagerWindow(QWidget):
    """独立的插件管理器窗口"""
    closed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_PM_CARD_W + _SHADOW*2, _PM_CARD_H + _SHADOW*2)
        
        self.items = []
        self._build_ui()
        self._load_data()
        
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW, _SHADOW, _SHADOW, _SHADOW)
        
        self.card = QWidget()
        self.card.setStyleSheet("""
            #card {
                background-color: #1c1a14;
                border-radius: 12px;
                border: 1px solid rgba(192, 140, 30, 0.4);
            }
        """)
        self.card.setObjectName("card")
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(10)
        shadow.setColor(QColor(0, 0, 0, 200))
        self.card.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("插件管理器 Plugin Manager")
        title.setStyleSheet("color: #e8d89a; font-size: 18px; font-weight: bold;")
        
        self.btn_open_folder = QPushButton("📂 打开插件目录")
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.setStyleSheet("""
            QPushButton {
                background: rgba(192, 140, 30, 0.1);
                color: #c08c1e;
                border: 1px solid rgba(192, 140, 30, 0.3);
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton:hover { background: rgba(192, 140, 30, 0.2); }
        """)
        self.btn_open_folder.clicked.connect(self._open_plugins_folder)
        
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.btn_open_folder)
        layout.addLayout(header)
        
        # List
        self.list_widget = QListWidget()
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: rgba(42, 37, 26, 0.4);
                border-radius: 8px;
                margin-bottom: 8px;
            }
            QListWidget::item:hover {
                background: rgba(42, 37, 26, 0.8);
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
            }
            QScrollBar::handle:vertical {
                background: rgba(192, 140, 30, 0.3);
                border-radius: 3px;
                min-height: 20px;
            }
        """)
        layout.addWidget(self.list_widget)
        
        # Footer
        footer = QHBoxLayout()
        
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setFixedHeight(36)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background: #4a3f2a;
                color: #e8d89a;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover { background: #5a4b32; }
        """)
        self.btn_refresh.clicked.connect(self._save_and_reload)
        
        self.btn_save = QPushButton("保存")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setFixedHeight(36)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background: #c08c1e;
                color: #1c1a14;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #dca32a; }
        """)
        self.btn_save.clicked.connect(self._save_and_close)
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8a7040;
                border: 1px solid #4a3f2a;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.05); }
        """)
        btn_cancel.clicked.connect(self.hide_window)
        
        footer.addWidget(btn_cancel, 1)
        footer.addWidget(self.btn_refresh, 1)
        footer.addWidget(self.btn_save, 2)
        layout.addLayout(footer)
        
        outer.addWidget(self.card)

    def _load_data(self):
        conf = get_plugin_config()
        # Sort metadata by module + function to have consistent ordering
        plugins = sorted(ALL_PLUGINS_META.items(), key=lambda x: x[0])
        
        self.list_widget.clear()
        self.items = []
        
        for pid, meta in plugins:
            pconf = conf.get(pid, {})
            
            item = QListWidgetItem(self.list_widget)
            item.setSizeHint(QSize(list_widget_width:=self.list_widget.viewport().width() - 20, 110))
            
            widget = PluginItemWidget(pid, meta, pconf)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
            self.items.append(widget)

    def _save_data_silently(self):
        new_conf = get_plugin_config()
        for widget in self.items:
            new_conf[widget.plugin_id] = widget.get_data()
        save_plugin_config(new_conf)

    def _save_and_reload(self):
        self._save_data_silently()
        reload_plugins()
        self._load_data()

    def _save_and_close(self):
        self._save_data_silently()
        reload_plugins()
        self.hide_window()

    def _open_plugins_folder(self):
        path = os.path.join(_base_dir(), "plugins")
        os.makedirs(path, exist_ok=True)
        import subprocess
        subprocess.Popen(f'explorer "{path}"')

    def show_window(self):
        self._load_data()
        
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
        self.show()
        self.raise_()
        import threading
        # Call force foreground after a tiny delay
        threading.Timer(0.05, lambda: _win_force_foreground(int(self.winId()))).start()

    def hide_window(self):
        self.hide()
        self.closed.emit()
