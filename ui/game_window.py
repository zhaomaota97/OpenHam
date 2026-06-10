"""沙箱游戏窗口：在 QWebEngineView 里渲染游戏包的 index.html。

通过 QWebChannel 自动注入 window.OpenHam 桥，游戏 JS 无需任何样板即可：
    OpenHam.send({...})            // 把本方操作发给房间其他人
    OpenHam.on(function(obj){...}) // 接收他人操作
    OpenHam.me / OpenHam.isHost    // 自己的 id / 是否房主
消息经 OpenHam relay 通道转发，从而实现"一起玩"。

安全：游戏只在 Chromium 沙箱里渲染 html/js，不触碰本地可执行文件。
"""
import os
import json

from PyQt6.QtCore import Qt, QObject, QUrl, QFile, QIODevice, pyqtSlot
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QLineEdit, QPushButton)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineScript
from PyQt6.QtWebChannel import QWebChannel

from ui.window_base import OpenHamWindowBase
from ui import icons
from ui import theme
from core.logging_setup import get_logger

log = get_logger("game")

_ASSET_CACHE = {}


def _read_asset(name: str) -> str:
    """读取 assets/ 下的脚本（Phaser、统一输入层等），结果缓存。"""
    if name in _ASSET_CACHE:
        return _ASSET_CACHE[name]
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "assets", name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception as e:
        log.warning("读取游戏资源 %s 失败：%s", name, e)
        src = ""
    _ASSET_CACHE[name] = src
    return src


def _qwebchannel_js() -> str:
    """读取 Qt 内置的 qwebchannel.js 源码以便注入。"""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.OpenModeFlag.ReadOnly):
        data = bytes(f.readAll()).decode("utf-8")
        f.close()
        return data
    log.warning("未能读取内置 qwebchannel.js")
    return ""


def _bridge_init_js(self_id: str, is_host: bool, name: str = "玩家") -> str:
    # 用属性合并而非整体赋值，确保和 openham_controls.js 注入的 OpenHam.input 共存
    return _qwebchannel_js() + """
    (function(){
      var OH = window.OpenHam = window.OpenHam || {};
      OH.me = %s; OH.name = %s; OH.isHost = %s; OH._cbs = OH._cbs || [];
      OH.on = function(cb){ this._cbs.push(cb); };
      window.__openham_recv = function(s){
        var o = JSON.parse(s);
        if (o && o.__oh){ if (OH._onmsg) OH._onmsg(o); return; }  // 平台内部消息
        (window.OpenHam._cbs||[]).forEach(function(cb){ try{ cb(o);}catch(e){console.error(e);} });
      };
      new QWebChannel(qt.webChannelTransport, function(channel){
        var bridge = channel.objects.openham_bridge;
        OH.send = function(obj){ bridge.send(JSON.stringify(obj)); };
        if (OH._onready) OH._onready();
        if (typeof window.OpenHamReady === 'function') window.OpenHamReady();
      });
    })();
    """ % (json.dumps(self_id), json.dumps(name), "true" if is_host else "false")


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
        self._chat_btn = QPushButton()
        self._chat_btn.setIcon(icons.qicon("chat"))
        self._chat_btn.setFixedSize(30, 30)
        self._chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chat_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;border-radius:7px;}}"
            f"QPushButton:hover{{background:{theme.HOVER};}}")
        self._chat_btn.clicked.connect(self._toggle_chat)
        self.header_tools_layout.addWidget(self._chat_btn)

        self._chat_panel = self._build_chat_panel()
        self.content_layout.addWidget(self._chat_panel)
        self._chat_panel.hide()

    def _build_chat_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(f"background:{theme.BG};")
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(6)
        self._chat_log = QTextEdit()
        self._chat_log.setReadOnly(True)
        self._chat_log.setFixedHeight(120)
        self._chat_log.setStyleSheet(
            f"QTextEdit{{background:{theme.SURFACE};color:{theme.TEXT};border:1px solid {theme.BORDER};"
            "border-radius:8px;font-size:13px;padding:6px;}")
        row = QHBoxLayout(); row.setSpacing(6)
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("发言…")
        self._chat_input.setStyleSheet(
            f"QLineEdit{{background:{theme.SURFACE};color:{theme.TEXT};border:1px solid {theme.BORDER_IN};"
            f"border-radius:8px;padding:8px;}}QLineEdit:focus{{border-color:{theme.ACCENT};}}")
        self._chat_input.returnPressed.connect(self._send_chat)
        send = QPushButton("发送")
        send.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT};color:#fff;border:none;border-radius:8px;"
            "padding:8px 14px;font-weight:600;}"
            f"QPushButton:hover{{background:{theme.ACCENT_HOV};}}")
        send.clicked.connect(self._send_chat)
        row.addWidget(self._chat_input, 1); row.addWidget(send)
        v.addWidget(self._chat_log); v.addLayout(row)
        return panel

    def _toggle_chat(self):
        self._chat_panel.setVisible(not self._chat_panel.isVisible())
        if self._chat_panel.isVisible():
            self._chat_input.setFocus()
            self._chat_btn.setIcon(icons.qicon("chat"))

    def _send_chat(self):
        text = self._chat_input.text().strip()
        if not text:
            return
        if self._on_chat_send:
            self._on_chat_send(text)
        self._chat_input.clear()

    def add_chat(self, name: str, text: str, mine: bool = False):
        if name is None:
            self._chat_log.append(
                f'<span style="color:{theme.TEXT2};">— {icons.richify(text)} —</span>')
        else:
            color = theme.ACCENT if mine else "#5b6470"
            self._chat_log.append(
                f'<span style="color:{color};font-weight:600;">{name}</span>'
                f'<span style="color:{theme.TEXT};">：{text}</span>')
        if not self._chat_panel.isVisible():
            self._chat_btn.setIcon(icons.qicon("offline"))

    def load_game(self, entry_path: str, self_id: str, is_host: bool,
                  name: str = "游戏", player_name: str = "玩家"):
        self.title_lbl.setText(f"游戏 · {name}")
        # DocumentCreation 时机依次注入：Phaser 引擎 → 统一输入层 → OpenHam 桥
        # 保证游戏脚本运行前，window.Phaser / OpenHam.input / OpenHam 都已就绪。
        self.page.scripts().clear()
        # 统一输入层 + OpenHam 桥：注入脚本(DocumentCreation)即可
        for sname, src in (
            ("openham_controls", _read_asset("openham_controls.js")),
            ("openham_bridge", _bridge_init_js(self_id, is_host, player_name)),
        ):
            if not src:
                continue
            s = QWebEngineScript()
            s.setName(sname)
            s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            s.setRunsOnSubFrames(False)
            s.setSourceCode(src)
            self.page.scripts().insert(s)

        # Phaser 是 UMD，必须以正常 <script> 运行(top-level this=window)才能挂全局；
        # 注入脚本里 this 非 window 会失败，所以把它内联进游戏 HTML 的 <head>。
        entry_path = self._inject_phaser_inline(entry_path)
        self.view.load(QUrl.fromLocalFile(entry_path))

    def _inject_phaser_inline(self, entry_path: str) -> str:
        phaser = _read_asset("phaser.min.js")
        if not phaser:
            return entry_path
        try:
            with open(entry_path, "r", encoding="utf-8") as f:
                html = f.read()
            if "openham_phaser_injected" in html:
                return entry_path   # 已注入过
            tag = "<script id='openham_phaser_injected'>\n" + phaser + "\n</script>\n"
            low = html.lower()
            if "<head>" in low:
                i = low.index("<head>") + len("<head>")
                html = html[:i] + "\n" + tag + html[i:]
            elif "<body" in low:
                i = low.index(">", low.index("<body")) + 1
                html = html[:i] + "\n" + tag + html[i:]
            else:
                html = tag + html
            with open(entry_path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as e:
            log.warning("内联 Phaser 到游戏 HTML 失败：%s", e)
        return entry_path

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
