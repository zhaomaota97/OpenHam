import time
import threading
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from core.plugin_manager import openham_plugin
from ui.pomodoro import PomodoroOverlay

# 模块级状态
_api = None
_overlay = None
_timer_gen = 0
_timer_end = 0.0
_countdown_qtimer = None
_action_timer_label = None
_action_timer_sep = None

def setup_pomodoro(api):
    global _api, _overlay, _countdown_qtimer, _action_timer_label, _action_timer_sep
    _api = api
    _overlay = PomodoroOverlay()
    
    _countdown_qtimer = QTimer()
    _countdown_qtimer.setInterval(1000)
    _countdown_qtimer.timeout.connect(_update_countdown)
    
    # 动态插入托盘菜单
    tray_menu: QMenu = api.call("get_tray_menu")
    if tray_menu:
        # 我们把番茄钟状态插在最上面
        _action_timer_label = QAction("🍅 剩余 --:--", tray_menu)
        _action_timer_label.setEnabled(False)
        _action_timer_label.setVisible(False)
        actions = tray_menu.actions()
        if actions:
            tray_menu.insertAction(actions[0], _action_timer_label)
            _action_timer_sep = tray_menu.insertSeparator(actions[0])
            _action_timer_sep.setVisible(False)

def _update_countdown():
    global _timer_end
    if _timer_end <= 0:
        _countdown_qtimer.stop()
        return
    remaining = _timer_end - time.time()
    
    tray: QSystemTrayIcon = _api.call("get_tray_icon")
    hotkey_str = _api.call("get_tray_hotkey_str")
    
    if remaining <= 0:
        _timer_end = 0
        _countdown_qtimer.stop()
        if tray: tray.setToolTip(f"OpenHam  ({hotkey_str})")
        if _action_timer_label: _action_timer_label.setVisible(False)
        if _action_timer_sep: _action_timer_sep.setVisible(False)
        _overlay.hide()
    else:
        m, s = divmod(int(remaining), 60)
        label = f"🍅 剩余 {m:02d}:{s:02d}"
        if tray: tray.setToolTip(f"OpenHam  {label}")
        if _action_timer_label: _action_timer_label.setText(label)
        _overlay.update_text(f"🍅 {m:02d}:{s:02d}")

def parse_dynamic(text: str):
    """尝试判断是否属于不需要指令名、直接由独立前缀唤醒的隐式参数 (如 25m)"""
    text = text.strip().lower()
    if text.endswith("m"):
        num = text[:-1]
        if num.isdigit() and 0 < int(num) <= 999:
            return ("start", int(num))
    return None

def match_pomodoro(text: str) -> bool:
    # 动态拦截仅暴露最为严谨的隐式参数规则，杜绝其他杂音
    return parse_dynamic(text) is not None

@openham_plugin(
    actions={
        "start": {"desc": "启动番茄钟", "trigger": ["番茄钟"]},
        "stop": {"desc": "停止番茄钟", "trigger": ["stop", "停止番茄钟"]}
    },
    match=match_pomodoro,
    desc="🍅 桌面交互番茄钟",
    setup=setup_pomodoro
)
def execute_pomodoro(text: str, action: str = None):
    global _timer_gen, _timer_end
    
    if action == "stop":
        mins = 0
    elif action == "start":
        parts = text.strip().split(maxsplit=1)
        mins = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() and 0 < int(parts[1]) <= 999 else 25
    else:
        # 当从不受 Tag 约束的全局正则动态入口 (例如: 盲敲 "40m") 切入时，进行兜底解析
        pomo = parse_dynamic(text)
        if not pomo:
            return {"type": "error", "content": "❌ 参数格式错误"}
        action, mins = pomo
    _timer_gen += 1
    
    tray: QSystemTrayIcon = _api.call("get_tray_icon")
    hotkey_str = _api.call("get_tray_hotkey_str")
    
    if action == "stop":
        _timer_end = 0
        _countdown_qtimer.stop()
        if tray: tray.setToolTip(f"OpenHam  ({hotkey_str})")
        if _action_timer_label: _action_timer_label.setVisible(False)
        if _action_timer_sep: _action_timer_sep.setVisible(False)
        _overlay.hide()
        return {"type": "result", "content": "✅ 番茄钟已停止"}
        
    else:
        my_gen = _timer_gen
        _timer_end = time.time() + mins * 60
        if _action_timer_label:
            _action_timer_label.setText(f"🍅 剩余 {mins:02d}:00")
            _action_timer_label.setVisible(True)
        if _action_timer_sep:
            _action_timer_sep.setVisible(True)
            
        _overlay.update_text(f"🍅 {mins:02d}:00")
        _overlay.show()
        _countdown_qtimer.start()
        
        show_toast = _api.call("show_toast")
        
        def _run(gen=my_gen, m=mins):
            time.sleep(m * 60)
            if _timer_gen == gen and show_toast:
                show_toast("🍅 番茄钟", f"{m} 分钟到了！好好休息一下 ☕")
                
        threading.Thread(target=_run, daemon=True).start()
        return {"type": "result", "content": f"✅ 🍅 {mins} 分钟，加油！"}
