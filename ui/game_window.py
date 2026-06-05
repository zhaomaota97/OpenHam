"""沙箱游戏窗口：在 QWebEngineView 里渲染游戏包的 index.html。

通过 QWebChannel 自动注入 window.OpenHam 桥，游戏 JS 无需任何样板即可：
    OpenHam.send({...})            // 把本方操作发给房间其他人
    OpenHam.on(function(obj){...}) // 接收他人操作
    OpenHam.me / OpenHam.isHost    // 自己的 id / 是否房主
消息经 OpenHam relay 通道转发，从而实现"一起玩"。

安全：游戏只在 Chromium 沙箱里渲染 html/js，不触碰本地可执行文件。
"""
import json

from PyQt6.QtCore import QObject, QUrl, QFile, QIODevice, pyqtSlot
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
    def __init__(self, on_game_send):
        """on_game_send(obj): 游戏内 JS 发来的操作，转交给联机层广播。"""
        super().__init__(title="游戏", shadow_size=0, min_w=820, min_h=620)
        self.title_lbl.setText("游戏")

        self.view = QWebEngineView()
        self.page = self.view.page()
        self._bridge = _Bridge(on_game_send)
        self._channel = QWebChannel(self.page)
        self._channel.registerObject("openham_bridge", self._bridge)
        self.page.setWebChannel(self._channel)
        self.content_layout.addWidget(self.view)

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
