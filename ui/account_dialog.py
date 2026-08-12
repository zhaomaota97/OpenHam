"""登录对话框：默认用账号密码登录（走网关，可靠、不需要本地端口/浏览器）；
也可选「用浏览器登录」。登录在后台线程跑，成功后把云端 AI 聊天/待办拉到本地。"""
import threading

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit)

from core import account, cloud_sync


class _Worker(QThread):
    done = pyqtSignal(bool, str)   # (成功?, 用户名或错误信息)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            name = self._fn()
            try:
                cloud_sync.pull_all()
            except Exception:
                pass
            self.done.emit(True, name or "")
        except Exception as e:
            self.done.emit(False, str(e))


class AccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "login"          # login | register
        self._cancel = threading.Event()
        self._worker = None
        self.setWindowTitle("登录")
        self.setModal(True)
        self.setMinimumWidth(340)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(12)

        tip = QLabel("登录后即可使用 AI，并在多台设备间同步。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#86868b;font-size:13px;")
        root.addWidget(tip)

        self.user_in = QLineEdit()
        self.user_in.setPlaceholderText("用户名")
        root.addWidget(self.user_in)

        self.pw_in = QLineEdit()
        self.pw_in.setPlaceholderText("密码")
        self.pw_in.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_in.returnPressed.connect(self._submit)
        root.addWidget(self.pw_in)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#86868b;font-size:12px;")
        root.addWidget(self.status)

        self.primary = QPushButton("登 录")
        self.primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary.clicked.connect(self._submit)
        root.addWidget(self.primary)

        sub = QHBoxLayout()
        self.toggle = QPushButton("没有账号？去注册")
        self.toggle.setFlat(True)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setStyleSheet("color:#0a84ff;border:none;font-size:12px;text-align:left;")
        self.toggle.clicked.connect(self._toggle_mode)
        sub.addWidget(self.toggle)
        sub.addStretch(1)
        self.browser_btn = QPushButton("用浏览器登录")
        self.browser_btn.setFlat(True)
        self.browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browser_btn.setStyleSheet("color:#86868b;border:none;font-size:12px;")
        self.browser_btn.clicked.connect(self._browser)
        sub.addWidget(self.browser_btn)
        root.addLayout(sub)

    def _toggle_mode(self):
        self._mode = "register" if self._mode == "login" else "login"
        is_login = self._mode == "login"
        self.primary.setText("登 录" if is_login else "注 册")
        self.toggle.setText("没有账号？去注册" if is_login else "已有账号？去登录")
        self.status.setText("")

    def _run(self, fn, busy_text):
        self.primary.setEnabled(False)
        self.browser_btn.setEnabled(False)
        self.status.setStyleSheet("color:#86868b;font-size:12px;")
        self.status.setText(busy_text)
        self._worker = _Worker(fn)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _submit(self):
        u = self.user_in.text().strip()
        p = self.pw_in.text()
        if not u or not p:
            self.status.setStyleSheet("color:#d9534f;font-size:12px;")
            self.status.setText("请输入用户名和密码")
            return
        if self._mode == "login":
            self._run(lambda: account.password_login(u, p), "登录中…")
        else:
            self._run(lambda: account.register(u, p), "注册中…")

    def _browser(self):
        self._cancel.clear()
        self._run(lambda: account.sso_login(cancel_event=self._cancel),
                  "已在浏览器打开登录页，请完成登录…")

    def _on_done(self, ok: bool, msg: str):
        if ok:
            self.accept()
        elif msg != "已取消":
            self.status.setStyleSheet("color:#d9534f;font-size:12px;")
            self.status.setText(msg)
            self.primary.setEnabled(True)
            self.browser_btn.setEnabled(True)

    def closeEvent(self, e):
        self._cancel.set()
        super().closeEvent(e)

    def reject(self):
        self._cancel.set()
        super().reject()
