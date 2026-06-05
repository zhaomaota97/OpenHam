"""沙箱游戏窗口：在 QWebEngineView 里渲染游戏包的 index.html。

通过 QWebChannel 自动注入 window.OpenHam 桥，游戏 JS 无需任何样板即可：
    OpenHam.send({...})            // 把本方操作发给房间其他人
    OpenHam.on(function(obj){...}) // 接收他人操作
    OpenHam.me / OpenHam.isHost    // 自己的 id / 是否房主
消息经 OpenHam relay 通道转发，从而实现"一起玩"。

安全：游戏只在 Chromium 沙箱里渲染 html/js，不触碰本地可执行文件。
"""
import json

from PyQt6.QtCore import Qt, QObject, QUrl, QFile, QIODevice, pyqtSlot
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QLineEdit, QPushButton)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineScript
from PyQt6.QtWebChannel import QWebChannel

from ui.window_base import OpenHamWindowBase
from core.logging_setup import get_logger

log = get_logger("game")


def _qwebchannel_js() -> str:
    """读取 Qt 内置的 qwebchannel.js 源码以便注入。"""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.OpenModeFlag.ReadOnly):
        data = bytes(f.readAll()).decode("utf-8")
        f.close()
        return data
    log.warning("未能读取内置 qwebchannel.js")
    return ""


def _bridge_init_js(self_id: str, is_host: bool) -> str:
    return _qwebchannel_js() + """
    (function(){
      new QWebChannel(qt.webChannelTransport, function(channel){
        var bridge = channel.objects.openham_bridge;
        window.OpenHam = {
          me: %s,
          isHost: %s,
          _cbs: [],
          send: function(obj){ bridge.send(JSON.stringify(obj)); },
          on: function(cb){ this._cbs.push(cb); }
        };
        window.__openham_recv = function(s){
          var o = JSON.parse(s);
          window.OpenHam._cbs.forEach(function(cb){ try{ cb(o);}catch(e){console.error(e);} });
        };
        if (typeof window.OpenHamReady === 'function') window.OpenHamReady();
      });
    })();
    """ % (json.dumps(self_id), "true" if is_host else "false")


class _Bridge(QObject):
    """JS → Python：游戏调用 OpenHam.send 时进入这里。"""
    def __init__(self, on_send):
        super().__init__()
        self._on_send = on_send

    @pyqtSlot(str)
    def send(self, json_str: str):
        try:
            self._on_send(json.loads(json_str))
        except Exception as e:
            log.warning("游戏发送解析失败: %s", e)


class GameWindow(OpenHamWindowBase):
    def __init__(self, on_game_send, on_chat_send=None):
        """on_game_send(obj): 游戏 JS 发来的操作；on_chat_send(text): 游戏页内发言。"""
        super().__init__(title="游戏", shadow_size=0, min_w=820, min_h=620)
        self.title_lbl.setText("游戏")
        self._on_chat_send = on_chat_send

        self.view = QWebEngineView()
        self.page = self.view.page()
        self._bridge = _Bridge(on_game_send)
        self._channel = QWebChannel(self.page)
        self._channel.registerObject("openham_bridge", self._bridge)
        self.page.setWebChannel(self._channel)
        self.content_layout.addWidget(self.view, 1)

        # 标题栏聊天开关 + 可折叠聊天面板（嵌在游戏窗口内）
        self._chat_btn = QPushButton("💬")
        self._chat_btn.setFixedSize(30, 30)
        self._chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chat_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#c09030;border:none;font-size:15px;}"
            "QPushButton:hover{background:rgba(192,140,30,0.2);border-radius:4px;}")
        self._chat_btn.clicked.connect(self._toggle_chat)
        self.header_tools_layout.addWidget(self._chat_btn)

        self._chat_panel = self._build_chat_panel()
        self.content_layout.addWidget(self._chat_panel)
        self._chat_panel.hide()

    def _build_chat_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background:#181610;")
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(6)
        self._chat_log = QTextEdit()
        self._chat_log.setReadOnly(True)
        self._chat_log.setFixedHeight(120)
        self._chat_log.setStyleSheet(
            "QTextEdit{background:rgba(21,18,13,0.9);color:#d8cfb8;border:1px solid #4a3f2a;"
            "border-radius:6px;font-size:13px;padding:6px;}")
        row = QHBoxLayout(); row.setSpacing(6)
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("发言…")
        self._chat_input.setStyleSheet(
            "QLineEdit{background:rgba(21,18,13,0.9);color:#ede5d0;border:1px solid #4a3f2a;"
            "border-radius:6px;padding:8px;}QLineEdit:focus{border-color:#c08c1e;}")
        self._chat_input.returnPressed.connect(self._send_chat)
        send = QPushButton("发送")
        send.setStyleSheet(
            "QPushButton{background:#c08c1e;color:#1c1a14;border:none;border-radius:6px;"
            "padding:8px 14px;font-weight:bold;}")
        send.clicked.connect(self._send_chat)
        row.addWidget(self._chat_input, 1); row.addWidget(send)
        v.addWidget(self._chat_log); v.addLayout(row)
        return panel

    def _toggle_chat(self):
        self._chat_panel.setVisible(not self._chat_panel.isVisible())
        if self._chat_panel.isVisible():
            self._chat_input.setFocus()
            self._chat_btn.setText("💬")

    def _send_chat(self):
        text = self._chat_input.text().strip()
        if not text:
            return
        if self._on_chat_send:
            self._on_chat_send(text)
        self._chat_input.clear()

    def add_chat(self, name: str, text: str, mine: bool = False):
        if name is None:
            self._chat_log.append(f'<span style="color:#6f6a55;">— {text} —</span>')
        else:
            color = "#c9b173" if mine else "#9fd0c0"
            self._chat_log.append(
                f'<span style="color:{color};font-weight:bold;">{name}</span>'
                f'<span style="color:#d8cfb8;">：{text}</span>')
        if not self._chat_panel.isVisible():
            self._chat_btn.setText("🔴")

    def load_game(self, entry_path: str, self_id: str, is_host: bool, name: str = "游戏"):
        self.title_lbl.setText(f"游戏 · {name}")
        # 注入桥脚本（DocumentCreation 时机，确保游戏脚本运行前 OpenHam 就绪）
        self.page.scripts().clear()
        script = QWebEngineScript()
        script.setName("openham_bridge")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(_bridge_init_js(self_id, is_host))
        self.page.scripts().insert(script)

        self.view.load(QUrl.fromLocalFile(entry_path))

    def deliver(self, obj: dict):
        """把他人的操作推给游戏 JS（触发 OpenHam.on 回调）。"""
        payload = json.dumps(json.dumps(obj))  # 双层转义后作为 JS 字符串参数
        self.page.runJavaScript(f"window.__openham_recv && window.__openham_recv({payload});")

    def hide_window(self):
        try:
            self.view.setUrl(QUrl("about:blank"))
        except Exception:
            pass
        super().hide_window()
