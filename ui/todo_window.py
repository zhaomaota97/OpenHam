"""任务：Google Tasks 风格的待办清单窗口。

入口：主程序输入框里以 `++` 开头唤起（见 plugins/todo.py）；也可从托盘菜单「任务」打开。
- `++`          → 仅打开窗口
- `++买牛奶`     → 打开窗口并在当前清单新建一条「买牛奶」

特性（对标 Google Tasks）：
- 多清单（左侧）：新建 / 重命名 / 删除 / 切换
- 任务：圆形勾选完成、标题、备注、到期日期；点标题打开详情编辑
- 子任务：缩进显示、各自勾选/删除、行内「添加子任务」
- 已完成：底部可折叠分区，删除线，勾选可恢复
- 排序：我的顺序（手动拖拽）/ 按日期；一键删除已完成
数据落地 todo/tasks.json（属用户数据，git 忽略）。窗口本体后续可与「聊天」打通。
"""
import os
import json
import time
import uuid

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QPlainTextEdit, QListWidget, QListWidgetItem, QScrollArea, QFrame,
    QDialog, QDialogButtonBox, QComboBox, QCheckBox, QDateEdit, QMenu,
    QInputDialog, QAbstractItemView, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QDate
from PyQt6.QtGui import QFont

from ui.window_base import OpenHamWindowBase
from ui import theme, icons


# ── 数据层 ──────────────────────────────────────────────────────────
def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_path() -> str:
    d = os.path.join(_base_dir(), "todo")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "tasks.json")


def _now() -> float:
    return time.time()


def _make_sub(title: str) -> dict:
    return {"id": uuid.uuid4().hex, "title": title or "", "done": False}


def _make_task(title: str) -> dict:
    return {"id": uuid.uuid4().hex, "title": title or "", "notes": "",
            "due": None, "done": False, "created": _now(),
            "completed": None, "subtasks": []}


def _make_list(name: str) -> dict:
    return {"id": uuid.uuid4().hex, "name": name or "我的任务",
            "created": _now(), "tasks": [], "sort": "my"}


def _norm_task(t: dict) -> dict:
    t.setdefault("id", uuid.uuid4().hex)
    t.setdefault("title", "")
    t.setdefault("notes", "")
    t.setdefault("due", None)
    t.setdefault("done", False)
    t.setdefault("created", _now())
    t.setdefault("completed", None)
    subs = t.get("subtasks") or []
    t["subtasks"] = [{"id": s.get("id", uuid.uuid4().hex),
                      "title": s.get("title", ""), "done": bool(s.get("done"))}
                     for s in subs]
    return t


def _load() -> dict:
    p = _data_path()
    data = None
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
    if not isinstance(data, dict) or not data.get("lists"):
        data = {"lists": [_make_list("我的任务")], "current": None}
    for lst in data["lists"]:
        lst.setdefault("id", uuid.uuid4().hex)
        lst.setdefault("name", "我的任务")
        lst.setdefault("sort", "my")
        lst["tasks"] = [_norm_task(t) for t in lst.get("tasks", [])]
    ids = [l["id"] for l in data["lists"]]
    if data.get("current") not in ids:
        data["current"] = ids[0]
    return data


def _save(data: dict):
    try:
        with open(_data_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[todo] 保存失败: {e}")


def _fmt_due(due: str):
    """返回 (展示文本, 是否逾期)。due 形如 'YYYY-MM-DD'，无则 (None, False)。"""
    if not due:
        return None, False
    try:
        y, m, d = (int(x) for x in due.split("-"))
    except Exception:
        return None, False
    lt = time.localtime()
    today = (lt.tm_year, lt.tm_mon, lt.tm_mday)
    overdue = (y, m, d) < today
    if (y, m, d) == today:
        return "今天", False
    # 明天
    tt = time.localtime(time.mktime((y, m, d, 12, 0, 0, 0, 0, -1)))
    _ = tt
    if y == lt.tm_year:
        return f"{m}月{d}日", overdue
    return f"{y}年{m}月{d}日", overdue


# ── 可点击标签 ──────────────────────────────────────────────────────
class _ClickLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ── 支持拖拽排序的任务列表 ───────────────────────────────────────────
class _DragList(QListWidget):
    reordered = pyqtSignal()

    def dropEvent(self, e):
        super().dropEvent(e)
        QTimer.singleShot(0, self.reordered.emit)


# ── 任务详情编辑对话框 ──────────────────────────────────────────────
class _TaskDialog(QDialog):
    def __init__(self, parent, task: dict, lists, cur_list_id):
        super().__init__(parent)
        self.setWindowTitle("任务详情")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        self._task = task
        self._subs = [dict(s) for s in task.get("subtasks", [])]
        self._deleted = False
        self._target_list = cur_list_id

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        self.title_in = QLineEdit(task.get("title", ""))
        self.title_in.setPlaceholderText("任务标题")
        self.title_in.setStyleSheet(self._in_qss(15, True))
        lay.addWidget(self.title_in)

        self.notes_in = QPlainTextEdit(task.get("notes", ""))
        self.notes_in.setPlaceholderText("添加备注")
        self.notes_in.setFixedHeight(80)
        self.notes_in.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.R_IN}px; padding: 7px 9px; color: {theme.TEXT};"
            f" font-size: 13px; }}")
        lay.addWidget(self.notes_in)

        # 日期
        drow = QHBoxLayout()
        drow.setSpacing(8)
        self.date_chk = QCheckBox("到期日期")
        self.date_chk.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setStyleSheet(
            f"QDateEdit {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.R_IN}px; padding: 5px 8px; color: {theme.TEXT};"
            f" font-size: 13px; }}")
        due = task.get("due")
        if due:
            try:
                y, m, d = (int(x) for x in due.split("-"))
                self.date_edit.setDate(QDate(y, m, d))
                self.date_chk.setChecked(True)
            except Exception:
                self.date_edit.setDate(QDate.currentDate())
        else:
            self.date_edit.setDate(QDate.currentDate())
            self.date_edit.setEnabled(False)
        self.date_chk.toggled.connect(self.date_edit.setEnabled)
        drow.addWidget(self.date_chk)
        drow.addWidget(self.date_edit, 1)
        lay.addLayout(drow)

        # 所属清单
        if len(lists) > 1:
            lrow = QHBoxLayout()
            lrow.setSpacing(8)
            lab = QLabel("清单")
            lab.setStyleSheet(f"color: {theme.TEXT2}; font-size: 13px;")
            self.list_box = QComboBox()
            self.list_box.setStyleSheet(
                f"QComboBox {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.R_IN}px; padding: 5px 8px; color: {theme.TEXT};"
                f" font-size: 13px; }}")
            for l in lists:
                self.list_box.addItem(l["name"], l["id"])
                if l["id"] == cur_list_id:
                    self.list_box.setCurrentIndex(self.list_box.count() - 1)
            lrow.addWidget(lab)
            lrow.addWidget(self.list_box, 1)
            lay.addLayout(lrow)
        else:
            self.list_box = None

        # 子任务
        sub_head = QLabel("子任务")
        sub_head.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600;")
        lay.addWidget(sub_head)
        self._sub_host = QWidget()
        self._sub_v = QVBoxLayout(self._sub_host)
        self._sub_v.setContentsMargins(0, 0, 0, 0)
        self._sub_v.setSpacing(4)
        lay.addWidget(self._sub_host)
        self._render_subs()

        addrow = QHBoxLayout()
        addrow.setSpacing(8)
        self._sub_in = QLineEdit()
        self._sub_in.setPlaceholderText("添加子任务，回车确认")
        self._sub_in.setStyleSheet(self._in_qss(13, False))
        self._sub_in.returnPressed.connect(self._add_sub)
        addrow.addWidget(self._sub_in, 1)
        lay.addLayout(addrow)

        # 底部按钮
        btns = QHBoxLayout()
        dele = QPushButton("删除任务")
        dele.setCursor(Qt.CursorShape.PointingHandCursor)
        dele.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.DANGER}; border: none;"
            f" font-size: 13px; padding: 6px 4px; }} QPushButton:hover {{ text-decoration: underline; }}")
        dele.clicked.connect(self._do_delete)
        btns.addWidget(dele)
        btns.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("完成")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        btns.addWidget(bb)
        lay.addLayout(btns)

    def _in_qss(self, size, bold):
        return (f"QLineEdit {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.R_IN}px; padding: 7px 9px; color: {theme.TEXT};"
                f" font-size: {size}px; font-weight: {'600' if bold else '400'}; }}")

    def _render_subs(self):
        while self._sub_v.count():
            it = self._sub_v.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for s in self._subs:
            row = QHBoxLayout()
            row.setSpacing(6)
            cb = QCheckBox()
            cb.setChecked(s["done"])
            cb.toggled.connect(lambda v, ss=s: ss.update(done=v))
            lab = QLabel(s["title"])
            lab.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
            rm = QPushButton("✕")
            rm.setFixedSize(20, 20)
            rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme.TEXT3}; border: none;"
                f" font-size: 12px; }} QPushButton:hover {{ color: {theme.DANGER}; }}")
            rm.clicked.connect(lambda _, ss=s: self._del_sub(ss))
            host = QWidget()
            host.setLayout(row)
            row.addWidget(cb)
            row.addWidget(lab, 1)
            row.addWidget(rm)
            self._sub_v.addWidget(host)

    def _add_sub(self):
        t = self._sub_in.text().strip()
        if not t:
            return
        self._subs.append(_make_sub(t))
        self._sub_in.clear()
        self._render_subs()

    def _del_sub(self, s):
        self._subs = [x for x in self._subs if x["id"] != s["id"]]
        self._render_subs()

    def _do_delete(self):
        self._deleted = True
        self.accept()

    def result_task(self):
        """把编辑结果写回字典并返回 (deleted, target_list_id)。"""
        if self._deleted:
            return True, self._target_list
        self._task["title"] = self.title_in.text().strip()
        self._task["notes"] = self.notes_in.toPlainText().strip()
        if self.date_chk.isChecked():
            qd = self.date_edit.date()
            self._task["due"] = f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"
        else:
            self._task["due"] = None
        self._task["subtasks"] = self._subs
        target = self.list_box.currentData() if self.list_box else self._target_list
        return False, target


# ── 主窗口 ──────────────────────────────────────────────────────────
class TodoWindow(OpenHamWindowBase):
    def __init__(self):
        super().__init__(title="任务", min_w=760, min_h=600)
        self.resize(940, 720)
        self.data = _load()
        self._show_completed = False
        self._adding_sub_for = None    # 正在行内添加子任务的任务 id
        self._build()
        self._refresh_lists()
        self._render_tasks()

    # 当前清单
    def _cur_list(self):
        cid = self.data.get("current")
        for l in self.data["lists"]:
            if l["id"] == cid:
                return l
        return self.data["lists"][0]

    # ── UI 骨架 ─────────────────────────────────────────────────────
    def _build(self):
        body = QWidget()
        h = QHBoxLayout(body)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        h.addWidget(self._build_main(), 1)
        self.content_layout.addWidget(body)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("todoSide")
        side.setFixedWidth(232)
        side.setStyleSheet(
            f"#todoSide {{ background: #fafafb; border-right: 1px solid {theme.BORDER}; }}")
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 18, 14, 14)
        v.setSpacing(10)
        cap = QLabel("清单")
        cap.setStyleSheet(f"color: {theme.TEXT3}; font-size: 11px; font-weight: 700;"
                          " letter-spacing: 1px; padding-left: 8px;")
        v.addWidget(cap)
        self.lists_w = QListWidget()
        self.lists_w.setFrameShape(QFrame.Shape.NoFrame)
        self.lists_w.setSpacing(2)
        self.lists_w.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ color: {theme.TEXT}; padding: 9px 12px; border-radius: {theme.R_BTN}px;"
            f" font-size: 14px; }}"
            f"QListWidget::item:hover {{ background: {theme.SUBTLE}; }}"
            f"QListWidget::item:selected {{ background: {theme.ACCENT_SOFT}; color: {theme.TEXT}; }}")
        self.lists_w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lists_w.customContextMenuRequested.connect(self._list_menu)
        self.lists_w.currentRowChanged.connect(self._on_list_row)
        v.addWidget(self.lists_w, 1)
        add = QPushButton("  新建清单")
        add.setIcon(icons.qicon("add", color=theme.TEXT2))
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT2}; border: none;"
            f" text-align: left; padding: 10px 12px; border-radius: {theme.R_BTN}px; font-size: 14px; }}"
            f"QPushButton:hover {{ background: {theme.SUBTLE}; color: {theme.TEXT}; }}")
        add.clicked.connect(self._add_list)
        v.addWidget(add)
        return side

    def _build_main(self):
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 内容居中成一栏（最大宽 ~700），两侧留白，更像 Tasks/Things 的清爽感
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addStretch(1)
        col = QWidget()
        col.setMaximumWidth(720)
        col.setMinimumWidth(400)
        col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v = QVBoxLayout(col)
        v.setContentsMargins(28, 22, 28, 14)
        v.setSpacing(14)
        center.addWidget(col, 50)      # 列占主导：填到 maxWidth 后多余空间才回流给两侧留白
        center.addStretch(1)
        outer.addLayout(center, 1)

        # 标题行
        top = QHBoxLayout()
        self.list_title = QLabel("")
        self.list_title.setStyleSheet(f"color: {theme.TEXT}; font-size: 24px; font-weight: 700;")
        top.addWidget(self.list_title)
        top.addStretch(1)
        self.menu_btn = QPushButton()
        self.menu_btn.setIcon(icons.qicon("more_v", color=theme.TEXT2))
        self.menu_btn.setFixedSize(32, 32)
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {theme.SUBTLE}; }}")
        self.menu_btn.clicked.connect(self._open_list_menu)
        top.addWidget(self.menu_btn)
        v.addLayout(top)

        # 添加任务输入
        addrow = QFrame()
        addrow.setObjectName("addRow")
        addrow.setStyleSheet(
            f"#addRow {{ background: {theme.CARD}; border: 1.5px solid {theme.BORDER_IN};"
            f" border-radius: 12px; }}"
            f"#addRow:hover {{ border-color: {theme.INDIGO}; }}")
        ah = QHBoxLayout(addrow)
        ah.setContentsMargins(16, 6, 12, 6)
        ah.setSpacing(10)
        plus = QLabel()
        plus.setPixmap(icons.qicon("add", color=theme.INDIGO).pixmap(QSize(18, 18)))
        ah.addWidget(plus)
        self.add_in = QLineEdit()
        self.add_in.setPlaceholderText("添加任务")
        self.add_in.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {theme.TEXT};"
            f" font-size: 15px; padding: 10px 0; }}")
        self.add_in.returnPressed.connect(self._add_task)
        ah.addWidget(self.add_in, 1)
        v.addWidget(addrow)

        # 滚动区：活动任务 + 已完成
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        host = QWidget()
        self.body_v = QVBoxLayout(host)
        self.body_v.setContentsMargins(0, 0, 0, 0)
        self.body_v.setSpacing(6)

        self.active_list = _DragList()
        self.active_list.setFrameShape(QFrame.Shape.NoFrame)
        self.active_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.active_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.active_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.active_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.active_list.setSpacing(0)
        self.active_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { border-radius: 10px; }"
            f"QListWidget::item:hover {{ background: {theme.SUBTLE}; }}")
        self.active_list.reordered.connect(self._on_reorder)
        self.body_v.addWidget(self.active_list)

        self.empty_lbl = QLabel("还没有任务。在上面输入框里添加一条吧。")
        self.empty_lbl.setStyleSheet(f"color: {theme.TEXT3}; font-size: 14px; padding: 14px 4px;")
        self.body_v.addWidget(self.empty_lbl)

        # 已完成分区
        self.comp_btn = QPushButton()
        self.comp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.comp_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT2}; border: none;"
            f" text-align: left; padding: 12px 4px 8px 4px; font-size: 13px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {theme.TEXT}; }}")
        self.comp_btn.clicked.connect(self._toggle_completed)
        self.body_v.addWidget(self.comp_btn)
        self.comp_host = QWidget()
        self.comp_v = QVBoxLayout(self.comp_host)
        self.comp_v.setContentsMargins(0, 0, 0, 0)
        self.comp_v.setSpacing(0)
        self.body_v.addWidget(self.comp_host)

        self.body_v.addStretch(1)
        self.scroll.setWidget(host)
        v.addWidget(self.scroll, 1)
        return wrap

    # ── 清单 ────────────────────────────────────────────────────────
    def _refresh_lists(self):
        self.lists_w.blockSignals(True)
        self.lists_w.clear()
        cur_row = 0
        for i, l in enumerate(self.data["lists"]):
            n_active = sum(1 for t in l["tasks"] if not t["done"])
            it = QListWidgetItem(f"{l['name']}" + (f"   {n_active}" if n_active else ""))
            it.setData(Qt.ItemDataRole.UserRole, l["id"])
            self.lists_w.addItem(it)
            if l["id"] == self.data["current"]:
                cur_row = i
        self.lists_w.setCurrentRow(cur_row)
        self.lists_w.blockSignals(False)
        self.list_title.setText(self._cur_list()["name"])

    def _on_list_row(self, row):
        if row < 0:
            return
        it = self.lists_w.item(row)
        if it is None:
            return
        self.data["current"] = it.data(Qt.ItemDataRole.UserRole)
        self.list_title.setText(self._cur_list()["name"])
        self._show_completed = False
        self._adding_sub_for = None
        self._render_tasks()

    def _add_list(self):
        name, ok = QInputDialog.getText(self, "新建清单", "清单名称：")
        if not ok or not name.strip():
            return
        l = _make_list(name.strip())
        self.data["lists"].append(l)
        self.data["current"] = l["id"]
        _save(self.data)
        self._refresh_lists()
        self._render_tasks()

    def _list_menu(self, pos):
        it = self.lists_w.itemAt(pos)
        if it is None:
            return
        lid = it.data(Qt.ItemDataRole.UserRole)
        m = theme.style_menu(QMenu(self))
        a_ren = m.addAction("重命名")
        a_del = m.addAction("删除清单")
        if len(self.data["lists"]) <= 1:
            a_del.setEnabled(False)
        act = m.exec(self.lists_w.mapToGlobal(pos))
        if act is a_ren:
            self._rename_list(lid)
        elif act is a_del:
            self._delete_list(lid)

    def _rename_list(self, lid):
        lst = next((l for l in self.data["lists"] if l["id"] == lid), None)
        if not lst:
            return
        name, ok = QInputDialog.getText(self, "重命名清单", "清单名称：", text=lst["name"])
        if ok and name.strip():
            lst["name"] = name.strip()
            _save(self.data)
            self._refresh_lists()

    def _delete_list(self, lid):
        if len(self.data["lists"]) <= 1:
            return
        self.data["lists"] = [l for l in self.data["lists"] if l["id"] != lid]
        if self.data["current"] == lid:
            self.data["current"] = self.data["lists"][0]["id"]
        _save(self.data)
        self._refresh_lists()
        self._render_tasks()

    def _open_list_menu(self):
        lst = self._cur_list()
        m = theme.style_menu(QMenu(self))
        a_my = m.addAction("按我的顺序")
        a_date = m.addAction("按日期排序")
        a_my.setCheckable(True)
        a_date.setCheckable(True)
        a_my.setChecked(lst.get("sort", "my") == "my")
        a_date.setChecked(lst.get("sort") == "date")
        m.addSeparator()
        a_ren = m.addAction("重命名清单")
        a_del = m.addAction("删除清单")
        if len(self.data["lists"]) <= 1:
            a_del.setEnabled(False)
        m.addSeparator()
        a_clear = m.addAction("删除所有已完成的任务")
        if not any(t["done"] for t in lst["tasks"]):
            a_clear.setEnabled(False)
        act = m.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))
        if act is a_my:
            lst["sort"] = "my"; _save(self.data); self._render_tasks()
        elif act is a_date:
            lst["sort"] = "date"; _save(self.data); self._render_tasks()
        elif act is a_ren:
            self._rename_list(lst["id"])
        elif act is a_del:
            self._delete_list(lst["id"])
        elif act is a_clear:
            lst["tasks"] = [t for t in lst["tasks"] if not t["done"]]
            _save(self.data); self._refresh_lists(); self._render_tasks()

    # ── 任务渲染 ────────────────────────────────────────────────────
    def _render_tasks(self):
        lst = self._cur_list()
        sort = lst.get("sort", "my")
        active = [t for t in lst["tasks"] if not t["done"]]
        done = [t for t in lst["tasks"] if t["done"]]
        if sort == "date":
            active.sort(key=lambda t: (t.get("due") is None, t.get("due") or ""))
            self.active_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        else:
            self.active_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        self.active_list.clear()
        for t in active:
            card = self._task_card(t)
            h = card.sizeHint().height()
            card.setMinimumHeight(h)        # 关键：否则 QListWidget 会把行压扁致内容重叠
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, t["id"])
            it.setSizeHint(QSize(0, h))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDragEnabled)
            self.active_list.addItem(it)
            self.active_list.setItemWidget(it, card)
        # 标题自动换行的真实高度依赖实际宽度，待布局稳定后按真实宽度再校正一次
        self._fix_card_heights()
        QTimer.singleShot(0, self._fix_card_heights)
        self.empty_lbl.setVisible(not active and not done)

        # 已完成
        for i in reversed(range(self.comp_v.count())):
            w = self.comp_v.itemAt(i).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        if done:
            self.comp_btn.setVisible(True)
            self.comp_btn.setText(f"已完成（{len(done)}）")
            self.comp_btn.setIcon(icons.qicon("angle_down" if self._show_completed else "angle_right",
                                              color=theme.TEXT2))
            self.comp_host.setVisible(self._show_completed)
            if self._show_completed:
                done.sort(key=lambda t: t.get("completed") or 0, reverse=True)
                for t in done:
                    self.comp_v.addWidget(self._completed_row(t))
        else:
            self.comp_btn.setVisible(False)
            self.comp_host.setVisible(False)

        self._refresh_lists_counts()

    def _refresh_lists_counts(self):
        # 仅更新左侧每个清单的未完成计数（不重建选中态）
        for i in range(self.lists_w.count()):
            it = self.lists_w.item(i)
            lid = it.data(Qt.ItemDataRole.UserRole)
            lst = next((l for l in self.data["lists"] if l["id"] == lid), None)
            if not lst:
                continue
            n = sum(1 for t in lst["tasks"] if not t["done"])
            it.setText(f"{lst['name']}" + (f"   {n}" if n else ""))

    def _fix_card_heights(self):
        """按列表的真实宽度重算每行高度（标题自动换行会改变行高），并设置列表总高。"""
        al = self.active_list
        w = al.viewport().width()
        n = al.count()
        if w > 0:
            for i in range(n):
                it = al.item(i)
                card = al.itemWidget(it)
                if card is None:
                    continue
                if card.hasHeightForWidth():
                    h = max(card.minimumSizeHint().height(), card.heightForWidth(w))
                else:
                    h = card.sizeHint().height()
                if h != card.minimumHeight():
                    card.setMinimumHeight(h)
                if abs(it.sizeHint().height() - h) > 0:
                    it.setSizeHint(QSize(0, h))
        total = sum(al.item(i).sizeHint().height() for i in range(n)) + 8
        al.setFixedHeight(total if n else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fix_card_heights)

    def _task_card(self, t):
        card = QWidget()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 11, 14, 11)
        outer.setSpacing(5)

        row = QHBoxLayout()
        row.setSpacing(12)
        cb = QPushButton()
        cb.setIcon(icons.qicon("circle_o", color=theme.BORDER_IN))
        cb.setIconSize(QSize(21, 21))
        cb.setFixedSize(26, 26)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet("QPushButton { background: transparent; border: none; }")
        cb.clicked.connect(lambda: self._complete_task(t["id"], True))
        row.addWidget(cb, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        title = _ClickLabel(t["title"] or "（无标题）")
        title.setWordWrap(True)
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        title.setStyleSheet(f"color: {theme.TEXT}; font-size: 15px; background: transparent;")
        title.clicked.connect(lambda: self._open_detail(t["id"]))
        col.addWidget(title)

        # 备注预览 + 日期
        meta = QHBoxLayout()
        meta.setSpacing(8)
        has_meta = False
        if t.get("notes"):
            n = t["notes"].strip().replace("\n", " ")
            n = n if len(n) <= 44 else n[:44] + "…"
            nl = QLabel(n)
            nl.setStyleSheet(f"color: {theme.TEXT3}; font-size: 13px; background: transparent;")
            meta.addWidget(nl)
            has_meta = True
        dtext, overdue = _fmt_due(t.get("due"))
        if dtext:
            dl = QLabel(dtext)
            if overdue:
                dl.setStyleSheet(f"color: {theme.DANGER}; font-size: 12px; background: #fdecec;"
                                 " border-radius: 6px; padding: 2px 8px;")
            else:
                dl.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; background: {theme.ACCENT_SOFT};"
                                 " border-radius: 6px; padding: 2px 8px;")
            meta.addWidget(dl)
            has_meta = True
        if has_meta:
            meta.addStretch(1)
            col.addLayout(meta)

        # 子任务
        for s in t.get("subtasks", []):
            col.addLayout(self._sub_row(t["id"], s))

        # 行内添加子任务
        if self._adding_sub_for == t["id"]:
            si = QLineEdit()
            si.setPlaceholderText("子任务，回车确认")
            si.setStyleSheet(
                f"QLineEdit {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER_IN};"
                f" border-radius: 8px; padding: 6px 10px; color: {theme.TEXT}; font-size: 13px; }}")
            si.returnPressed.connect(lambda: self._commit_subtask(t["id"], si.text()))
            si.installEventFilter(self)
            self._sub_input = si
            col.addSpacing(2)
            col.addWidget(si)
            QTimer.singleShot(0, si.setFocus)
        else:
            add_sub = _ClickLabel("＋ 子任务")
            add_sub.setCursor(Qt.CursorShape.PointingHandCursor)
            add_sub.setStyleSheet(f"color: {theme.TEXT3}; font-size: 13px; background: transparent;"
                                  " padding-top: 1px;")
            add_sub.clicked.connect(lambda: self._begin_subtask(t["id"]))
            col.addWidget(add_sub)

        row.addLayout(col, 1)
        outer.addLayout(row)
        return card

    def _sub_row(self, task_id, s):
        row = QHBoxLayout()
        row.setContentsMargins(4, 1, 0, 1)
        row.setSpacing(10)
        cb = QPushButton()
        cb.setIcon(icons.qicon("check_done" if s["done"] else "circle_o",
                               color=theme.SUCCESS if s["done"] else theme.BORDER_IN))
        cb.setIconSize(QSize(16, 16))
        cb.setFixedSize(22, 22)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet("QPushButton { background: transparent; border: none; }")
        cb.clicked.connect(lambda: self._toggle_sub(task_id, s["id"]))
        row.addWidget(cb)
        lab = QLabel(s["title"])
        if s["done"]:
            lab.setStyleSheet(f"color: {theme.TEXT3}; font-size: 14px; text-decoration: line-through;"
                              " background: transparent;")
        else:
            lab.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; background: transparent;")
        row.addWidget(lab, 1)
        return row

    def _completed_row(self, t):
        row = QFrame()
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 14, 8)
        h.setSpacing(12)
        cb = QPushButton()
        cb.setIcon(icons.qicon("check_done", color=theme.SUCCESS))
        cb.setIconSize(QSize(21, 21))
        cb.setFixedSize(26, 26)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet("QPushButton { background: transparent; border: none; }")
        cb.clicked.connect(lambda: self._complete_task(t["id"], False))
        h.addWidget(cb)
        lab = _ClickLabel(t["title"] or "（无标题）")
        lab.setCursor(Qt.CursorShape.PointingHandCursor)
        lab.setStyleSheet(f"color: {theme.TEXT3}; font-size: 15px; text-decoration: line-through;"
                          " background: transparent;")
        lab.clicked.connect(lambda: self._open_detail(t["id"]))
        h.addWidget(lab, 1)
        return row

    def eventFilter(self, obj, e):
        # 行内子任务输入失焦即取消
        from PyQt6.QtCore import QEvent
        if e.type() == QEvent.Type.FocusOut and self._adding_sub_for is not None:
            QTimer.singleShot(0, self._cancel_subtask)
        return super().eventFilter(obj, e)

    # ── 任务操作 ────────────────────────────────────────────────────
    def _find_task(self, tid):
        for t in self._cur_list()["tasks"]:
            if t["id"] == tid:
                return t
        return None

    def _add_task(self):
        title = self.add_in.text().strip()
        if not title:
            return
        self.add_in.clear()
        self._cur_list()["tasks"].insert(0, _make_task(title))
        _save(self.data)
        self._render_tasks()

    def _complete_task(self, tid, done):
        t = self._find_task(tid)
        if not t:
            return
        t["done"] = done
        t["completed"] = _now() if done else None
        _save(self.data)
        self._render_tasks()

    def _open_detail(self, tid):
        t = self._find_task(tid)
        if not t:
            return
        dlg = _TaskDialog(self, t, self.data["lists"], self._cur_list()["id"])
        if dlg.exec():
            deleted, target = dlg.result_task()
            cur = self._cur_list()
            if deleted:
                cur["tasks"] = [x for x in cur["tasks"] if x["id"] != tid]
            elif target and target != cur["id"]:
                cur["tasks"] = [x for x in cur["tasks"] if x["id"] != tid]
                dest = next((l for l in self.data["lists"] if l["id"] == target), None)
                if dest is not None:
                    dest["tasks"].insert(0, t)
            _save(self.data)
            self._refresh_lists_counts()
            self._render_tasks()

    def _toggle_sub(self, task_id, sub_id):
        t = self._find_task(task_id)
        if not t:
            return
        for s in t.get("subtasks", []):
            if s["id"] == sub_id:
                s["done"] = not s["done"]
                break
        _save(self.data)
        self._render_tasks()

    def _begin_subtask(self, tid):
        self._adding_sub_for = tid
        self._render_tasks()

    def _commit_subtask(self, tid, text):
        text = (text or "").strip()
        t = self._find_task(tid)
        if t is not None and text:
            t.setdefault("subtasks", []).append(_make_sub(text))
            _save(self.data)
        self._adding_sub_for = None
        self._render_tasks()

    def _cancel_subtask(self):
        if self._adding_sub_for is not None:
            self._adding_sub_for = None
            self._render_tasks()

    def _toggle_completed(self):
        self._show_completed = not self._show_completed
        self._render_tasks()

    def _on_reorder(self):
        lst = self._cur_list()
        order = [self.active_list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.active_list.count())]
        by_id = {t["id"]: t for t in lst["tasks"]}
        done = [t for t in lst["tasks"] if t["done"]]
        new_active = [by_id[i] for i in order if i in by_id and not by_id[i]["done"]]
        lst["tasks"] = new_active + done
        _save(self.data)
        self._render_tasks()

    # ── 对外 ────────────────────────────────────────────────────────
    def open(self):
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        if not self.isVisible():
            self.show_window_centered()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self.add_in.setFocus()

    def add_quick(self, title: str):
        """供 ++ 快捷命令：在当前清单新建一条任务并打开窗口。"""
        title = (title or "").strip()
        if title:
            self._cur_list()["tasks"].insert(0, _make_task(title))
            _save(self.data)
            self._render_tasks()
        self.open()
