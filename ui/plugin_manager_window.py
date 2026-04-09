import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QListWidgetItem,
                             QGraphicsDropShadowEffect, QScrollArea, QLineEdit, QDialog, QGridLayout)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QCursor
import ctypes

from core.plugin_manager import (ALL_PLUGINS_META, get_plugin_config, 
                                 save_plugin_config, reload_plugins)
from utils.paths import _base_dir

_SHADOW = 20
_PM_CARD_W = 960
_PM_CARD_H = 760

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

from PyQt6.QtCore import QTimer

def _check_conflict(trigger: str, exclude_plugin_id: str) -> str | None:
    t_strip = trigger.strip()
    if not t_strip: return None
    from core.script_engine import _sm_load_scripts
    for s in _sm_load_scripts():
        if s.get("trigger", "").strip() == t_strip:
            return s.get("description", "自定义脚本")
            
    # 从当前的 GUI 实例中抓取活体的、尚未保存的 Tags 配置
    from PyQt6.QtWidgets import QApplication
    pm_window = next((w for w in QApplication.topLevelWidgets() if type(w).__name__ == "PluginManagerWindow"), None)
    
    from core.plugin_manager import ALL_PLUGINS_META, get_plugin_config
    
    if pm_window:
        for widget in getattr(pm_window, "items", []):
            if widget.plugin_id == exclude_plugin_id:
                continue
            if getattr(widget, "trigger_input", None) and t_strip in widget.trigger_input.get_tags():
                meta = ALL_PLUGINS_META.get(widget.plugin_id, {})
                return meta.get("desc", widget.plugin_id)
            if getattr(widget, "action_inputs", None):
                for act_name, tag_input in widget.action_inputs.items():
                    if t_strip in tag_input.get_tags():
                        meta = ALL_PLUGINS_META.get(widget.plugin_id, {})
                        return meta.get("actions", {}).get(act_name, {}).get("desc", widget.plugin_id)
    else:
        # Fallback 保底读取硬盘缓存
        all_confs = get_plugin_config()
        for pid, meta in ALL_PLUGINS_META.items():
            if pid == exclude_plugin_id:
                continue
            conf = all_confs.get(pid, {})
            if conf.get("enabled", True):
                if not meta.get("actions"):
                    trs = conf.get("triggers", meta.get("default_triggers", []))
                    if t_strip in trs:
                        return meta.get("desc", pid)
                else:
                    conf_acts = conf.get("actions", {})
                    for act_name, act_meta in meta.get("actions", {}).items():
                        trs = conf_acts.get(act_name, {}).get("triggers", act_meta.get("trigger", []))
                        if t_strip in trs:
                            return act_meta.get("desc", pid)
    return None

class TagInputWidget(QScrollArea):
    tags_changed = pyqtSignal()
    
    def __init__(self, plugin_id: str, triggers: list[str], parent=None):
        super().__init__(parent)
        self.plugin_id = plugin_id
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: 1px solid #4a3f2a; border-radius: 4px; background: #2a251a; }")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFixedHeight(34)
        
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.layout = QHBoxLayout(self.container)
        self.layout.setContentsMargins(4, 2, 4, 2)
        self.layout.setSpacing(6)
        self.setWidget(self.container)
        
        self.tags = []
        for t in triggers:
            self._create_tag_widget(t)
            
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("敲回车新增...")
        self.input_box.setStyleSheet("background: transparent; color: #c08c1e; border: none; min-width: 140px;")
        self.input_box.returnPressed.connect(self._on_submit)
        
        self.layout.addWidget(self.input_box)
        self.layout.addStretch()

    def _create_tag_widget(self, text: str):
        if text in self.tags: return
        self.tags.append(text)
        
        tag_w = QWidget()
        tag_w.setStyleSheet("background: #503d15; border-radius: 4px;")
        t_layout = QHBoxLayout(tag_w)
        t_layout.setContentsMargins(6, 2, 4, 2)
        t_layout.setSpacing(4)
        
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #ebdbb2;")
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(14, 14)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("QPushButton { color: #ebdbb2; background: transparent; border: none; font-weight: bold; font-size: 10px; } QPushButton:hover { color: #fb4934; }")
        close_btn.clicked.connect(lambda: self._remove_tag(text, tag_w))
        
        t_layout.addWidget(lbl)
        t_layout.addWidget(close_btn)
        
        self.layout.insertWidget(self.layout.count() - 2, tag_w)
        
    def _remove_tag(self, text: str, widget: QWidget):
        if text in self.tags:
            self.tags.remove(text)
        widget.deleteLater()
        self.tags_changed.emit()
        
    def _on_submit(self):
        t = self.input_box.text().strip()
        if not t: return
        
        conflict_owner = _check_conflict(t, self.plugin_id)
        if conflict_owner:
            self.input_box.clear()
            self.setStyleSheet("QScrollArea { border: 1px solid #cc241d; border-radius: 4px; background: #2a251a; }")
            QTimer.singleShot(800, lambda: self.setStyleSheet("QScrollArea { border: 1px solid #4a3f2a; border-radius: 4px; background: #2a251a; }"))
            
            from PyQt6.QtWidgets import QToolTip
            # 在输入框的正下方弹出一个轻量级的跟随提示气泡
            pt = self.input_box.mapToGlobal(self.input_box.rect().bottomLeft())
            QToolTip.showText(pt, f"指令「{t}」已被【{conflict_owner}】占用", self.input_box)
            return
            
        self._create_tag_widget(t)
        self.input_box.clear()
        self.tags_changed.emit()
        
    def get_tags(self) -> list[str]:
        return self.tags


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
        
        # Bottom rows: Triggers or Actions
        if not meta.get("actions"):
            bot_row = QHBoxLayout()
            alias_lbl = QLabel("触发命令:")
            alias_lbl.setStyleSheet("color: #a89f8a; font-size: 12px;")
            
            triggers = conf.get("triggers")
            if triggers is None or (not triggers and meta.get("default_triggers")):
                triggers = meta.get("default_triggers", [])
            
            self.trigger_input = TagInputWidget(self.plugin_id, triggers)
            self.trigger_input.tags_changed.connect(lambda: self.changed.emit())
            
            bot_row.addWidget(alias_lbl)
            bot_row.addWidget(self.trigger_input, 1)
            layout.addLayout(bot_row)
            self.action_inputs = None
            
        else:
            self.trigger_input = None
            self.action_inputs = {}
            conf_actions = conf.get("actions", {})
            
            act_container = QVBoxLayout()
            act_container.setSpacing(0)
            act_container.setContentsMargins(0, 4, 0, 0)
            
            first = True
            for act_name, act_meta in meta.get("actions").items():
                if not first:
                    act_container.addSpacing(12)
                first = False    
                
                act_row = QHBoxLayout()
                act_row.setContentsMargins(0, 0, 0, 0)
                
                desc_text = act_meta.get("desc", act_name)
                lbl = QLabel(f"{desc_text}:")
                lbl.setStyleSheet("color: #a89f8a; font-size: 13px; min-width: 80px;")
                
                act_conf = conf_actions.get(act_name, {})
                triggers = act_conf.get("triggers")
                if triggers is None or (not triggers and act_meta.get("trigger")):
                    triggers = act_meta.get("trigger", [])
                
                tag_input = TagInputWidget(self.plugin_id, triggers)
                tag_input.tags_changed.connect(lambda: self.changed.emit())
                self.action_inputs[act_name] = tag_input
                
                act_row.addWidget(lbl)
                act_row.addWidget(tag_input, 1)
                
                act_container.addLayout(act_row)
                
            layout.addLayout(act_container)
        
    def get_data(self):
        """返回此插件最新的 config 持久化字典"""
        data = {"enabled": self.toggle.isChecked()}
        if self.trigger_input is not None:
            data["triggers"] = self.trigger_input.get_tags()
        if self.action_inputs:
            acts = {}
            for act_name, widget in self.action_inputs.items():
                acts[act_name] = {"triggers": widget.get_tags()}
            data["actions"] = acts
        return data


from ui.window_base import OpenHamWindowBase

class PluginManagerWindow(OpenHamWindowBase):
    """独立的插件管理器窗口"""
    closed = pyqtSignal()
    
    def __init__(self):
        super().__init__(title="🔌  插件管理", shadow_size=0, min_w=_PM_CARD_W, min_h=_PM_CARD_H)
        
        self.items = []
        self._build_ui()
        self._load_data()
        self.resize(_PM_CARD_W, _PM_CARD_H)
        self.setWindowTitle("插件管理")
        self.title_lbl.setText("插件管理")
        
    def _build_ui(self):
        self.btn_open_folder = QPushButton("📂 打开目录")
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
        self.header_tools_layout.addWidget(self.btn_open_folder)

        # Content Wrapper for List and Footer
        content_w = QWidget()
        content_w.setStyleSheet("background: transparent;")
        content_lay = QVBoxLayout(content_w)
        content_lay.setContentsMargins(20, 10, 20, 20)
        
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
        content_lay.addWidget(self.list_widget)
        
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
        content_lay.addLayout(footer)
        
        self.content_layout.addWidget(content_w)

    def _load_data(self):
        conf = get_plugin_config()
        # Sort metadata by module + function to have consistent ordering
        plugins = sorted(ALL_PLUGINS_META.items(), key=lambda x: x[0])
        
        self.list_widget.clear()
        self.items = []
        
        for pid, meta in plugins:
            pconf = conf.get(pid, {})
            
            widget = PluginItemWidget(pid, meta, pconf)
            
            # PyQt 中未显示的 QWidget 其 sizeHint 可能会失真或被引擎滞后计算
            # 强制要求 Layout 系统深度遍历并重算确切的物理占用高宽
            widget.layout().activate()
            exact_h = widget.layout().sizeHint().height()
            
            item = QListWidgetItem(self.list_widget)
            
            list_width = self.list_widget.viewport().width() - 20
            # 给予充足的基础高度 (含内外边距误差补偿)
            item.setSizeHint(QSize(list_width, max(110, exact_h + 16)))
            
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
        self._apply_native_window_state()
        self.raise_()
        import threading
        # Call force foreground after a tiny delay
        threading.Timer(0.05, lambda: _win_force_foreground(int(self.winId()))).start()

    def hide_window(self):
        self.hide()
        self.closed.emit()
