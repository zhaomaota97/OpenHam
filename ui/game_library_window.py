"""游戏库窗口：管理自己的游戏（AI 发明的 + 导入的），一键发布到房间。"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QLabel, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt

from ui.window_base import OpenHamWindowBase
from core import game_library
from core.game_package import GamePackageError


class GameLibraryWindow(OpenHamWindowBase):
    def __init__(self, on_publish, on_invent):
        super().__init__(title="游戏库", shadow_size=0, min_w=520, min_h=460)
        self.title_lbl.setText("游戏库")
        self._on_publish = on_publish    # on_publish(folder)
        self._on_invent = on_invent      # on_invent()
        self._games = []
        self._build()

    def _build(self):
        root = QWidget()
        root.setStyleSheet(self._qss())
        v = QVBoxLayout(root)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        top = QHBoxLayout(); top.setSpacing(8)
        invent = QPushButton("✨ 发明新游戏")
        invent.setObjectName("ai")
        invent.clicked.connect(self._invent)
        imp = QPushButton("📁 导入游戏")
        imp.clicked.connect(self._import)
        top.addWidget(invent)
        top.addWidget(imp)
        top.addStretch()
        v.addLayout(top)

        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        self.list = QListWidget()
        self.list.setObjectName("list")
        self.list.itemDoubleClicked.connect(lambda _i: self._publish())
        v.addWidget(self.list, 1)

        bot = QHBoxLayout(); bot.setSpacing(8)
        pub = QPushButton("🚀 发布到房间")
        pub.setObjectName("primary")
        pub.clicked.connect(self._publish)
        dele = QPushButton("🗑 删除")
        dele.clicked.connect(self._delete)
        bot.addWidget(pub, 1)
        bot.addWidget(dele)
        v.addLayout(bot)

        self.content_layout.addWidget(root)

    def _refresh(self):
        self.list.clear()
        self._games = game_library.list_games()
        for g in self._games:
            self.list.addItem("🎮  " + g["name"])
        if self._games:
            self.list.setCurrentRow(0)
            self.hint.setText("选一个游戏 → 发布到房间（双击也行）。")
        else:
            self.hint.setText("还没有游戏。点「✨ 发明新游戏」让 AI 现做一个，或「📁 导入游戏」。")

    def _selected(self):
        i = self.list.currentRow()
        return self._games[i] if 0 <= i < len(self._games) else None

    def _publish(self):
        g = self._selected()
        if not g:
            self.hint.setText("请先在列表里选一个游戏。")
            return
        self.hide_window()
        self._on_publish(g["folder"])

    def _delete(self):
        g = self._selected()
        if not g:
            return
        if QMessageBox.question(self, "删除游戏", f"删除「{g['name']}」？此操作不可恢复。") == QMessageBox.StandardButton.Yes:
            game_library.delete_game(g["folder"])
            self._refresh()

    def _import(self):
        folder = QFileDialog.getExistingDirectory(self, "选择游戏文件夹（里面要有 index.html）")
        if not folder:
            return
        try:
            game_library.import_folder(folder)
            self._refresh()
            self.hint.setText("✅ 导入成功。")
        except GamePackageError as e:
            self.hint.setText(f"⚠️ 导入失败：{e}")

    def _invent(self):
        self.hide_window()
        self._on_invent()

    def show_window(self):
        self._refresh()
        self.show_window_centered()
        self.raise_()
        self.activateWindow()

    def _qss(self) -> str:
        return """
            QWidget { background: transparent; }
            QLabel#hint { color: #8a9a7a; font-size: 12px; }
            QListWidget#list {
                background: rgba(21,18,13,0.92); color: #e6dcc2;
                border: 1px solid #4a3f2a; border-radius: 8px; padding: 4px;
                font-size: 14px;
            }
            QListWidget#list::item { padding: 9px 8px; border-radius: 5px; }
            QListWidget#list::item:selected { background: rgba(192,140,30,0.25); color: #fff; }
            QPushButton {
                background: rgba(192,140,30,0.10); color: #e6dcc2;
                border: 1px solid #4a3f2a; border-radius: 6px; padding: 8px 14px; font-size: 13px;
            }
            QPushButton:hover { background: rgba(192,140,30,0.20); }
            QPushButton#primary { background: #c08c1e; color: #1c1a14; font-weight: bold; border: none; }
            QPushButton#primary:hover { background: #d39c28; }
            QPushButton#ai {
                background: rgba(160,80,200,0.15); color: #d090f0;
                border: 1px solid rgba(160,80,200,0.3); font-weight: bold;
            }
            QPushButton#ai:hover { background: rgba(160,80,200,0.3); }
        """
