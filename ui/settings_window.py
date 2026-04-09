import json
import os
import re
import subprocess
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.window_base import OpenHamWindowBase
from utils.paths import _base_dir


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _parse_requirement_line(line: str) -> tuple[str | None, str | None]:
    raw = line.strip()
    if not raw or raw.startswith("#") or raw.startswith("-"):
        return None, None

    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", raw)
    if not match:
        return None, None
    return match.group(1), raw


def _hotkey_key_name(key: int) -> str | None:
    special = {
        Qt.Key.Key_Space: "space",
        Qt.Key.Key_Tab: "tab",
        Qt.Key.Key_Return: "enter",
        Qt.Key.Key_Enter: "enter",
        Qt.Key.Key_Escape: "esc",
        Qt.Key.Key_Backspace: "backspace",
        Qt.Key.Key_Delete: "delete",
        Qt.Key.Key_Insert: "insert",
        Qt.Key.Key_Home: "home",
        Qt.Key.Key_End: "end",
        Qt.Key.Key_PageUp: "pageup",
        Qt.Key.Key_PageDown: "pagedown",
        Qt.Key.Key_Left: "left",
        Qt.Key.Key_Right: "right",
        Qt.Key.Key_Up: "up",
        Qt.Key.Key_Down: "down",
    }
    if key in special:
        return special[key]
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        return f"f{key - Qt.Key.Key_F1 + 1}"
    text = chr(key) if 32 <= key <= 126 else ""
    if text and text.isalnum():
        return text.lower()
    return None


def _format_hotkey_from_event(event) -> str | None:
    key = event.key()
    if key in (
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
    ):
        return None

    parts = []
    mods = event.modifiers()
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("win")

    key_name = _hotkey_key_name(key)
    if not key_name:
        return None
    parts.append(key_name)
    return "+".join(parts)


def _hotkey_to_display(value: str) -> str:
    cleaned = value.replace("<", "").replace(">", "").strip()
    if not cleaned:
        return ""
    parts = []
    for part in cleaned.split("+"):
        token = part.strip().lower()
        if not token:
            continue
        if token == "ctrl":
            parts.append("Ctrl")
        elif token == "alt":
            parts.append("Alt")
        elif token == "shift":
            parts.append("Shift")
        elif token == "win":
            parts.append("Win")
        elif token == "space":
            parts.append("Space")
        elif token == "enter":
            parts.append("Enter")
        elif token.startswith("f") and token[1:].isdigit():
            parts.append(token.upper())
        else:
            parts.append(token.upper() if len(token) == 1 else token.capitalize())
    return "+".join(parts)


def _hotkey_to_storage(value: str) -> str:
    cleaned = value.replace("<", "").replace(">", "").strip().lower()
    if not cleaned:
        return ""
    wrapped = []
    for part in cleaned.split("+"):
        token = part.strip()
        if token in {"ctrl", "alt", "shift", "space"}:
            wrapped.append(f"<{token}>")
        elif token == "win":
            wrapped.append("<win>")
        else:
            wrapped.append(token)
    return "+".join(wrapped)


class HotkeyCaptureEdit(QLineEdit):
    hotkey_changed = pyqtSignal(str)
    capture_started = pyqtSignal()
    capture_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._capture_mode = False
        self._display_value = ""
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)

    def set_hotkey_text(self, value: str):
        self._display_value = value.strip()
        if not self._capture_mode:
            self.setText(self._display_value)

    def set_capture_mode(self, enabled: bool, restore_text: bool = True):
        if self._capture_mode == enabled:
            if not enabled and restore_text:
                self.setText(self._display_value)
            return

        self._capture_mode = enabled
        if enabled:
            self.setText("")
            self.setPlaceholderText("按下快捷键")
            self.capture_started.emit()
            self.setFocus()
        else:
            self.setPlaceholderText("" if self._display_value else "点击设置快捷键")
            if restore_text:
                self.setText(self._display_value)
            self.capture_finished.emit()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.set_capture_mode(True)

    def focusOutEvent(self, event):
        self.set_capture_mode(False)
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if not self._capture_mode:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Escape:
            self.set_capture_mode(False)
            event.accept()
            return

        hotkey = _format_hotkey_from_event(event)
        if hotkey:
            self._display_value = hotkey
            self.setText(hotkey)
            self.hotkey_changed.emit(hotkey)
            self.set_capture_mode(False, restore_text=False)
        event.accept()


class SettingsWindow(OpenHamWindowBase):
    dependency_log = pyqtSignal(str)
    dependency_state_ready = pyqtSignal(object)
    dependency_action_done = pyqtSignal(bool, str)

    def __init__(self, config: dict):
        super().__init__(title="设置", shadow_size=0, min_w=860, min_h=680)
        self._config = config
        self._dep_busy = False
        self._pending_dependency_change = None
        self._default_hotkey = "<alt>+<space>"
        self._captured_hotkey = config.get("hotkey", self._default_hotkey)
        self._project_dir = _base_dir()
        self._python_exe = os.path.join(self._project_dir, "runtime", "python.exe")
        self._get_pip_py = os.path.join(self._project_dir, "runtime", "get-pip.py")
        self._requirements_path = os.path.join(self._project_dir, "requirements.txt")

        self.resize(860, 680)
        self.setWindowTitle("设置")
        self.title_lbl.setText("设置")

        self.dependency_log.connect(self._append_dependency_log)
        self.dependency_state_ready.connect(self._apply_dependency_state)
        self.dependency_action_done.connect(self._finish_dependency_action)

        self._build_ui()
        self._load_general_settings()
        self.refresh_dependency_state()

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet("background: transparent;")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(20, 12, 20, 20)
        root_layout.setSpacing(14)

        body = QHBoxLayout()
        body.setSpacing(20)

        nav = QWidget()
        nav.setFixedWidth(150)
        nav.setStyleSheet(
            """
            QWidget {
                background: rgba(24, 22, 17, 0.68);
                border-right: 1px solid rgba(192, 140, 30, 0.12);
            }
            """
        )
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 8, 0, 8)
        nav_layout.setSpacing(8)

        self.nav_buttons = []
        for index, title in enumerate(("常规", "依赖管理")):
            btn = QPushButton(title)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(56)
            btn.clicked.connect(lambda checked=False, idx=index: self._set_page(idx))
            nav_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        nav_layout.addStretch()
        body.addWidget(nav)

        content_wrap = QWidget()
        content_wrap.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content_wrap)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.page_stack = QStackedWidget()
        self.page_stack.setStyleSheet("background: transparent; border: none;")
        self.page_stack.addWidget(self._build_general_tab())
        self.page_stack.addWidget(self._build_dependency_tab())
        content_layout.addWidget(self.page_stack, 1)
        body.addWidget(content_wrap, 1)

        root_layout.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8a9a7a; font-size: 12px;")
        footer.addWidget(self.status_label, 1)

        cancel_btn = QPushButton("关闭")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setFixedHeight(38)
        cancel_btn.setStyleSheet(self._secondary_button_style())
        cancel_btn.clicked.connect(self.hide_window)
        footer.addWidget(cancel_btn)

        save_btn = QPushButton("保存设置")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setFixedHeight(38)
        save_btn.setStyleSheet(self._primary_button_style())
        save_btn.clicked.connect(self._save_general_settings)
        footer.addWidget(save_btn)

        root_layout.addLayout(footer)
        self.content_layout.addWidget(root)
        self._set_page(0)

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 0, 0, 0)
        reset_row.addStretch()
        self.reset_hotkey_btn = QPushButton("重置快捷键")
        self.reset_hotkey_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_hotkey_btn.setStyleSheet(self._secondary_button_style())
        self.reset_hotkey_btn.clicked.connect(self._reset_hotkey_to_default)
        reset_row.addWidget(self.reset_hotkey_btn)
        layout.addLayout(reset_row)

        form_box = QGroupBox("基础配置")
        form_box.setStyleSheet(self._group_box_style())
        form_layout = QFormLayout(form_box)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(14)

        hotkey_row = QWidget()
        hotkey_row_layout = QHBoxLayout(hotkey_row)
        hotkey_row_layout.setContentsMargins(0, 0, 0, 0)
        hotkey_row_layout.setSpacing(10)

        self.hotkey_input = HotkeyCaptureEdit()
        self.hotkey_input.setStyleSheet(self._input_style())
        self.hotkey_input.hotkey_changed.connect(self._on_hotkey_captured)
        self.hotkey_input.capture_started.connect(self._on_hotkey_capture_started)
        self.hotkey_input.capture_finished.connect(self._on_hotkey_capture_finished)
        hotkey_row_layout.addWidget(self.hotkey_input, 1)

        self.hotkey_reset_btn = QPushButton("重置")
        self.hotkey_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hotkey_reset_btn.setStyleSheet(self._secondary_button_style())
        self.hotkey_reset_btn.clicked.connect(self._reset_hotkey_to_default)
        hotkey_row_layout.addWidget(self.hotkey_reset_btn)

        form_layout.addRow(self._form_label("全局热键"), hotkey_row)

        self.search_roots_input = QPlainTextEdit()
        self.search_roots_input.setPlaceholderText("每行一个目录，用于文件搜索")
        self.search_roots_input.setFixedHeight(120)
        self.search_roots_input.setStyleSheet(self._editor_style())
        form_layout.addRow(self._form_label("搜索目录"), self.search_roots_input)

        hint = QLabel("全局热键修改后需要重启 OpenHam 才会完全生效。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a9a7a; font-size: 12px;")
        form_layout.addRow(QLabel(""), hint)

        layout.addWidget(form_box)
        layout.addStretch()
        return tab

    def _build_dependency_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        env_box = QGroupBox("项目环境")
        env_box.setStyleSheet(self._group_box_style())
        env_layout = QFormLayout(env_box)
        env_layout.setHorizontalSpacing(16)
        env_layout.setVerticalSpacing(12)

        self.python_path_label = self._value_label(self._python_exe)
        self.requirements_path_label = self._value_label(self._requirements_path)
        self.pip_status_label = self._value_label("检查中...")

        env_layout.addRow(self._form_label("Python"), self.python_path_label)
        env_layout.addRow(self._form_label("Requirements"), self.requirements_path_label)
        env_layout.addRow(self._form_label("Pip 状态"), self.pip_status_label)
        layout.addWidget(env_box)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(10)

        self.dependency_filter = QLineEdit()
        self.dependency_filter.setPlaceholderText("筛选依赖")
        self.dependency_filter.setStyleSheet(self._input_style())
        self.dependency_filter.textChanged.connect(self._filter_dependency_rows)
        tools_row.addWidget(self.dependency_filter, 1)

        self.refresh_deps_btn = QPushButton("刷新")
        self.refresh_deps_btn.setStyleSheet(self._secondary_button_style())
        self.refresh_deps_btn.clicked.connect(self.refresh_dependency_state)
        tools_row.addWidget(self.refresh_deps_btn)

        self.sync_requirements_btn = QPushButton("同步 requirements.txt")
        self.sync_requirements_btn.setStyleSheet(self._primary_button_style())
        self.sync_requirements_btn.clicked.connect(self._sync_requirements)
        tools_row.addWidget(self.sync_requirements_btn)

        self.add_dependency_btn = QPushButton("安装依赖...")
        self.add_dependency_btn.setStyleSheet(self._secondary_button_style())
        self.add_dependency_btn.clicked.connect(self._install_dependency_prompt)
        tools_row.addWidget(self.add_dependency_btn)

        self.remove_dependency_btn = QPushButton("卸载选中")
        self.remove_dependency_btn.setStyleSheet(self._secondary_button_style())
        self.remove_dependency_btn.clicked.connect(self._remove_selected_dependencies)
        tools_row.addWidget(self.remove_dependency_btn)

        layout.addLayout(tools_row)

        self.dependency_summary_label = QLabel("正在读取依赖状态...")
        self.dependency_summary_label.setStyleSheet("color: #8a9a7a; font-size: 12px;")
        layout.addWidget(self.dependency_summary_label)

        self.dependency_table = QTableWidget(0, 4)
        self.dependency_table.setHorizontalHeaderLabels(["包名", "声明", "已安装版本", "状态"])
        self.dependency_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dependency_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.dependency_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dependency_table.setAlternatingRowColors(True)
        self.dependency_table.verticalHeader().setVisible(False)
        self.dependency_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.dependency_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.dependency_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.dependency_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.dependency_table.setStyleSheet(
            """
            QTableWidget {
                background: rgba(28, 25, 18, 0.85);
                color: #d8cfb8;
                border: 1px solid #4a3f2a;
                border-radius: 8px;
                gridline-color: rgba(74, 63, 42, 0.6);
                alternate-background-color: rgba(41, 35, 24, 0.7);
            }
            QHeaderView::section {
                background: #30291d;
                color: #f0ddb0;
                border: none;
                border-bottom: 1px solid #4a3f2a;
                padding: 8px;
            }
            QTableWidget::item:selected {
                background: rgba(192, 140, 30, 0.25);
            }
            """
        )
        layout.addWidget(self.dependency_table, 1)

        log_box = QGroupBox("执行日志")
        log_box.setStyleSheet(self._group_box_style())
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(12, 12, 12, 12)
        self.dependency_log_output = QPlainTextEdit()
        self.dependency_log_output.setReadOnly(True)
        self.dependency_log_output.setStyleSheet(self._editor_style())
        self.dependency_log_output.setFixedHeight(160)
        log_layout.addWidget(self.dependency_log_output)
        layout.addWidget(log_box)

        return tab

    def _load_general_settings(self):
        self._captured_hotkey = self._config.get("hotkey", self._default_hotkey)
        self.hotkey_input.set_hotkey_text(_hotkey_to_display(self._captured_hotkey))
        self.hotkey_input.set_capture_mode(False)
        roots = self._config.get("search_roots") or []
        self.search_roots_input.setPlainText("\n".join(roots))

    def _save_general_settings(self):
        hotkey = self._captured_hotkey.strip() or self._default_hotkey
        roots = [line.strip() for line in self.search_roots_input.toPlainText().splitlines() if line.strip()]

        self._config["hotkey"] = hotkey
        if roots:
            self._config["search_roots"] = roots
        else:
            self._config.pop("search_roots", None)

        config_path = os.path.join(self._project_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

        self.status_label.setText("设置已保存")

    def _set_page(self, index: int):
        self.page_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            selected = i == index
            btn.setChecked(selected)
            btn.setStyleSheet(self._nav_button_style(selected))

    def _on_hotkey_captured(self, hotkey: str):
        if hotkey:
            self._captured_hotkey = _hotkey_to_storage(hotkey)
            self.hotkey_input.set_hotkey_text(_hotkey_to_display(self._captured_hotkey))
            self.status_label.setText(f"已识别快捷键: {_hotkey_to_display(self._captured_hotkey)}")

    def _on_hotkey_capture_started(self):
        self.status_label.setText("请按下新的快捷键组合，移开焦点即可结束录制")

    def _on_hotkey_capture_finished(self):
        self.hotkey_input.set_hotkey_text(_hotkey_to_display(self._captured_hotkey))
        if self.status_label.text() == "请按下新的快捷键组合，移开焦点即可结束录制":
            self.status_label.setText("快捷键录制已结束")

    def _reset_hotkey_to_default(self):
        self._captured_hotkey = self._default_hotkey
        self.hotkey_input.set_hotkey_text(_hotkey_to_display(self._captured_hotkey))
        self.hotkey_input.set_capture_mode(False)
        self.status_label.setText(f"已重置为默认快捷键: {_hotkey_to_display(self._default_hotkey)}")

    def show_window(self):
        self._load_general_settings()
        self.refresh_dependency_state()
        self.show_window_centered()
        self.raise_()
        self.activateWindow()

    def refresh_dependency_state(self):
        if self._dep_busy:
            return
        self._pending_dependency_change = None
        self._set_dependency_busy(True, "正在刷新依赖状态...")
        self.dependency_log.emit("开始刷新依赖状态...")
        threading.Thread(target=self._dependency_refresh_worker, daemon=True).start()

    def _sync_requirements(self):
        if self._dep_busy:
            return
        self._pending_dependency_change = None
        self._set_dependency_busy(True, "正在同步 requirements.txt ...")
        threading.Thread(target=self._dependency_install_requirements_worker, daemon=True).start()

    def _install_dependency_prompt(self):
        if self._dep_busy:
            return

        spec, ok = QInputDialog.getText(
            self,
            "安装依赖",
            "输入要安装的依赖名或版本约束，例如 requests 或 httpx==0.28.1：",
        )
        spec = spec.strip()
        if not ok or not spec:
            return

        package_name, _ = _parse_requirement_line(spec)
        if not package_name:
            QMessageBox.warning(self, "安装依赖", "依赖格式无法识别，请输入标准的 pip 包名。")
            return

        self._pending_dependency_change = ("add", spec)
        self._set_dependency_busy(True, f"正在安装 {spec} ...")
        threading.Thread(target=self._dependency_install_package_worker, args=(spec,), daemon=True).start()

    def _remove_selected_dependencies(self):
        if self._dep_busy:
            return

        selected_rows = sorted({item.row() for item in self.dependency_table.selectedItems()})
        if not selected_rows:
            QMessageBox.information(self, "卸载依赖", "请先在列表中选择要移除的依赖。")
            return

        names = []
        for row in selected_rows:
            item = self.dependency_table.item(row, 0)
            if item:
                names.append(item.text().strip())
        names = [name for name in names if name]
        if not names:
            return

        msg = "将从 requirements.txt 移除并卸载以下依赖：\n\n" + "\n".join(names)
        reply = QMessageBox.question(
            self,
            "卸载依赖",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._pending_dependency_change = ("remove", names)
        self._set_dependency_busy(True, "正在卸载选中的依赖...")
        threading.Thread(target=self._dependency_uninstall_packages_worker, args=(names,), daemon=True).start()

    def _dependency_refresh_worker(self):
        pip_ready, pip_message = self._ensure_pip()
        installed = {}
        if pip_ready:
            result = self._run_hidden_command([self._python_exe, "-m", "pip", "list", "--format=json"])
            if result.returncode == 0:
                try:
                    payload = json.loads(result.stdout or "[]")
                    installed = {
                        _normalize_package_name(item.get("name", "")): item.get("version", "")
                        for item in payload
                        if item.get("name")
                    }
                except json.JSONDecodeError:
                    self.dependency_log.emit("读取 pip 列表失败，返回内容不是合法 JSON。")
            else:
                self.dependency_log.emit(result.stdout.strip() or "读取 pip 列表失败。")

        rows = []
        declared_names = set()
        for line in self._read_requirements_lines():
            package_name, raw_spec = _parse_requirement_line(line)
            if not package_name:
                continue

            normalized = _normalize_package_name(package_name)
            declared_names.add(normalized)
            installed_version = installed.get(normalized, "")
            status = self._build_dependency_status(raw_spec, installed_version)
            rows.append(
                {
                    "name": package_name,
                    "requirement": raw_spec,
                    "installed_version": installed_version or "-",
                    "status": status,
                }
            )

        extras = sorted(
            name for name in installed.keys()
            if name not in declared_names and name not in {"pip", "setuptools", "wheel"}
        )
        self.dependency_state_ready.emit(
            {
                "pip_ready": pip_ready,
                "pip_message": pip_message,
                "rows": rows,
                "extra_count": len(extras),
            }
        )

    def _dependency_install_requirements_worker(self):
        pip_ready, pip_message = self._ensure_pip()
        if not pip_ready:
            self.dependency_action_done.emit(False, pip_message)
            return

        self.dependency_log.emit("开始同步 requirements.txt ...")
        result = self._run_hidden_command(
            [self._python_exe, "-m", "pip", "install", "-r", self._requirements_path]
        )
        self.dependency_log.emit(result.stdout.strip() or "未输出额外日志。")
        self.dependency_action_done.emit(result.returncode == 0, "requirements.txt 同步完成" if result.returncode == 0 else "requirements.txt 同步失败")

    def _dependency_install_package_worker(self, spec: str):
        pip_ready, pip_message = self._ensure_pip()
        if not pip_ready:
            self.dependency_action_done.emit(False, pip_message)
            return

        self.dependency_log.emit(f"开始安装依赖: {spec}")
        result = self._run_hidden_command([self._python_exe, "-m", "pip", "install", spec])
        self.dependency_log.emit(result.stdout.strip() or "未输出额外日志。")
        self.dependency_action_done.emit(result.returncode == 0, f"{spec} 安装完成" if result.returncode == 0 else f"{spec} 安装失败")

    def _dependency_uninstall_packages_worker(self, package_names: list[str]):
        pip_ready, pip_message = self._ensure_pip()
        if not pip_ready:
            self.dependency_action_done.emit(False, pip_message)
            return

        self.dependency_log.emit("开始卸载依赖: " + ", ".join(package_names))
        result = self._run_hidden_command(
            [self._python_exe, "-m", "pip", "uninstall", "-y", *package_names]
        )
        self.dependency_log.emit(result.stdout.strip() or "未输出额外日志。")
        self.dependency_action_done.emit(result.returncode == 0, "依赖卸载完成" if result.returncode == 0 else "依赖卸载失败")

    def _ensure_pip(self) -> tuple[bool, str]:
        if not os.path.exists(self._python_exe):
            msg = "未找到 runtime/python.exe"
            self.dependency_log.emit(msg)
            return False, msg

        check = self._run_hidden_command([self._python_exe, "-m", "pip", "--version"])
        if check.returncode == 0:
            return True, (check.stdout or "").strip()

        if not os.path.exists(self._get_pip_py):
            msg = "未找到 runtime/get-pip.py"
            self.dependency_log.emit(msg)
            return False, msg

        self.dependency_log.emit("pip 不存在，开始引导安装...")
        bootstrap = self._run_hidden_command([self._python_exe, self._get_pip_py])
        self.dependency_log.emit(bootstrap.stdout.strip() or "未输出额外日志。")
        if bootstrap.returncode != 0:
            return False, "pip 引导安装失败"

        recheck = self._run_hidden_command([self._python_exe, "-m", "pip", "--version"])
        return recheck.returncode == 0, (recheck.stdout or "").strip() if recheck.returncode == 0 else "pip 安装失败"

    def _run_hidden_command(self, args: list[str]) -> subprocess.CompletedProcess:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return subprocess.run(
            args,
            cwd=self._project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startupinfo,
        )

    def _apply_dependency_state(self, state: dict):
        self.dependency_table.setRowCount(0)
        rows = state.get("rows", [])
        self.dependency_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, key in enumerate(("name", "requirement", "installed_version", "status")):
                item = QTableWidgetItem(str(row.get(key, "")))
                self.dependency_table.setItem(row_index, column, item)

        self._filter_dependency_rows(self.dependency_filter.text())
        pip_message = state.get("pip_message") or "未检测到 pip"
        self.pip_status_label.setText(pip_message)
        self.dependency_summary_label.setText(
            f"requirements.txt 中声明 {len(rows)} 项依赖，额外已安装 {state.get('extra_count', 0)} 项。"
        )
        self._set_dependency_busy(False, "依赖状态已刷新")

    def _finish_dependency_action(self, success: bool, message: str):
        if success and self._pending_dependency_change:
            action, payload = self._pending_dependency_change
            if action == "add":
                self._upsert_requirement_line(payload)
            elif action == "remove":
                self._remove_requirement_lines(payload)
        self._pending_dependency_change = None
        self._set_dependency_busy(False, message)
        self.refresh_dependency_state()
        if not success:
            QMessageBox.warning(self, "依赖管理", message)

    def _append_dependency_log(self, message: str):
        if not message:
            return
        self.dependency_log_output.appendPlainText(message.rstrip())

    def _filter_dependency_rows(self, text: str):
        keyword = text.strip().lower()
        for row in range(self.dependency_table.rowCount()):
            visible = True
            if keyword:
                package_item = self.dependency_table.item(row, 0)
                requirement_item = self.dependency_table.item(row, 1)
                haystack = " ".join(
                    filter(
                        None,
                        [
                            package_item.text().lower() if package_item else "",
                            requirement_item.text().lower() if requirement_item else "",
                        ],
                    )
                )
                visible = keyword in haystack
            self.dependency_table.setRowHidden(row, not visible)

    def _set_dependency_busy(self, busy: bool, message: str):
        self._dep_busy = busy
        for button in (
            self.refresh_deps_btn,
            self.sync_requirements_btn,
            self.add_dependency_btn,
            self.remove_dependency_btn,
        ):
            button.setEnabled(not busy)
        self.status_label.setText(message)

    def _build_dependency_status(self, requirement: str, installed_version: str) -> str:
        if not installed_version:
            return "未安装"
        if "==" in requirement:
            expected = requirement.split("==", 1)[1].strip()
            return "版本匹配" if expected == installed_version else "版本不一致"
        return "已安装"

    def _read_requirements_lines(self) -> list[str]:
        if not os.path.exists(self._requirements_path):
            return []
        with open(self._requirements_path, "r", encoding="utf-8") as f:
            return f.read().splitlines()

    def _write_requirements_lines(self, lines: list[str]):
        with open(self._requirements_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")

    def _upsert_requirement_line(self, spec: str):
        package_name, _ = _parse_requirement_line(spec)
        if not package_name:
            return

        normalized = _normalize_package_name(package_name)
        lines = self._read_requirements_lines()
        replaced = False
        new_lines = []
        for line in lines:
            existing_name, _ = _parse_requirement_line(line)
            if existing_name and _normalize_package_name(existing_name) == normalized:
                if not replaced:
                    new_lines.append(spec)
                    replaced = True
                continue
            new_lines.append(line)

        if not replaced:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append(spec)
        self._write_requirements_lines(new_lines)

    def _remove_requirement_lines(self, package_names: list[str]):
        normalized_targets = {_normalize_package_name(name) for name in package_names}
        lines = self._read_requirements_lines()
        new_lines = []
        for line in lines:
            existing_name, _ = _parse_requirement_line(line)
            if existing_name and _normalize_package_name(existing_name) in normalized_targets:
                continue
            new_lines.append(line)
        self._write_requirements_lines(new_lines)

    def _form_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #d8cfb8; font-size: 13px;")
        return label

    def _value_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #d8cfb8; font-size: 13px;")
        return label

    def _group_box_style(self) -> str:
        return (
            "QGroupBox {"
            " color: #f0ddb0;"
            " border: 1px solid #4a3f2a;"
            " border-radius: 8px;"
            " margin-top: 8px;"
            " padding-top: 12px;"
            " background: rgba(34, 30, 22, 0.72);"
            "}"
            "QGroupBox::title {"
            " subcontrol-origin: margin;"
            " left: 12px;"
            " padding: 0 6px;"
            "}"
        )

    def _input_style(self) -> str:
        return (
            "QLineEdit {"
            " background: rgba(21, 18, 13, 0.92);"
            " color: #d8cfb8;"
            " border: 1px solid #4a3f2a;"
            " border-radius: 6px;"
            " padding: 8px 10px;"
            "}"
            "QLineEdit:focus { border-color: #c08c1e; }"
        )

    def _editor_style(self) -> str:
        return (
            "QPlainTextEdit {"
            " background: rgba(21, 18, 13, 0.92);"
            " color: #d8cfb8;"
            " border: 1px solid #4a3f2a;"
            " border-radius: 6px;"
            " padding: 8px;"
            "}"
        )

    def _primary_button_style(self) -> str:
        return (
            "QPushButton {"
            " background: #c08c1e;"
            " color: #1c1a14;"
            " border: none;"
            " border-radius: 6px;"
            " padding: 8px 14px;"
            " font-size: 13px;"
            " font-weight: bold;"
            "}"
            "QPushButton:hover { background: #d39c28; }"
            "QPushButton:disabled { background: #6f6247; color: #2a251a; }"
        )

    def _secondary_button_style(self) -> str:
        return (
            "QPushButton {"
            " background: rgba(192, 140, 30, 0.1);"
            " color: #d8cfb8;"
            " border: 1px solid #4a3f2a;"
            " border-radius: 6px;"
            " padding: 8px 14px;"
            " font-size: 13px;"
            "}"
            "QPushButton:hover { background: rgba(192, 140, 30, 0.18); }"
            "QPushButton:disabled { color: #786d57; border-color: #3b3325; }"
        )

    def _nav_button_style(self, selected: bool) -> str:
        if selected:
            return (
                "QPushButton {"
                " background: rgba(192, 140, 30, 0.18);"
                " color: #f0ddb0;"
                " border: 1px solid rgba(192, 140, 30, 0.35);"
                " border-radius: 8px;"
                " padding: 0 18px;"
                " text-align: left;"
                " font-size: 14px;"
                " font-weight: bold;"
                "}"
            )
        return (
            "QPushButton {"
            " background: transparent;"
            " color: #a99b7c;"
            " border: 1px solid transparent;"
            " border-radius: 8px;"
            " padding: 0 18px;"
            " text-align: left;"
            " font-size: 14px;"
            "}"
            "QPushButton:hover {"
            " background: rgba(192, 140, 30, 0.08);"
            " color: #f0ddb0;"
            "}"
        )
