import subprocess
import ast
import operator
import os
import json as _json
import socket as _socket
from gitlab.preset import GITLAB_PREVIEWS

from utils.system_tools import get_system_info, parse_pomodoro

_cached_scripts = None
_cached_scripts_mtime = 0.0

def _sm_load_scripts() -> list:
    """带系统级缓存的 scripts.json 读取器。"""
    global _cached_scripts, _cached_scripts_mtime
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "script_manager", "scripts.json")
    if not os.path.exists(p):
        return []
    try:
        mtime = os.path.getmtime(p)
        if _cached_scripts is not None and mtime == _cached_scripts_mtime:
            return _cached_scripts
        with open(p, "r", encoding="utf-8") as f:
            _cached_scripts = _json.load(f).get("scripts", [])
            _cached_scripts_mtime = mtime
            return _cached_scripts
    except Exception:
        return _cached_scripts or []

# main.py 启动后会把 ScriptManagerOverlay 实例注入到这里
_script_overlay = None

def set_script_overlay(overlay):
    global _script_overlay
    _script_overlay = overlay

# 允许的运算符映射，不使用 eval() 避免安全风险
_OPERATORS = {
    ast.Add:      operator.add,
    ast.Sub:      operator.sub,
    ast.Mult:     operator.mul,
    ast.Div:      operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod:      operator.mod,
    ast.Pow:      operator.pow,
    ast.USub:     operator.neg,
    ast.UAdd:     operator.pos,
}

def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        # 防止除以0
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ZeroDivisionError
        # 限制指数过大
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")

def evaluate_expr(text: str):
    """尝试将 text 作为算术表达式求值。
    成功返回结果字符串，无法识别则返回 None。"""
    text = text.strip()
    if not text:
        return None
    try:
        tree = ast.parse(text, mode="eval")
        # 忽略单纯的数字和带符号数字，如 123 或 -5
        if isinstance(tree.body, ast.Constant):
            return None
        if isinstance(tree.body, ast.UnaryOp) and isinstance(tree.body.operand, ast.Constant):
            return None
            
        result = _eval_node(tree)
        # 整数结果去掉小数点
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"= {result}"
    except ZeroDivisionError:
        return "= 除以零错误"
    except Exception:
        return None


def check_script_trigger(text: str) -> str | None:
    """
    检查 text 是否匹配任意脚本触发命令。
    命中则通过 overlay.run_trigger() 运行，返回提示字符串；未命中返回 None。
    """
    for s in _sm_load_scripts():
        if s.get("trigger", "").strip() == text.strip():
            if _script_overlay is not None:
                _script_overlay.run_trigger(text, silent=False)
                return f"✅ 正在执行脚本「{s.get('trigger', text)}」"
            return f"✅ 脚本触发成功（overlay 未就绪）"
    return None


def execute(text: str) -> str:
    """执行预设指令。命中返回 '✅ ...'，未命中返回 None。"""
    text = text.strip()

    # 脚本管理器
    if text == "脚本配置":
        if _script_overlay is not None:
            _script_overlay.open()
        return "✅ 已打开脚本管理器"

    # 检查自定义脚本触发命令
    _trigger_result = check_script_trigger(text)
    if _trigger_result is not None:
        return _trigger_result

    if text == "计算器":
        subprocess.Popen("calc.exe")
        return "✅ 已打开计算器"

    if text == "记事本":
        subprocess.Popen("notepad.exe")
        return "✅ 已打开记事本"

    if text == "cmd":
        subprocess.Popen("cmd.exe")
        return "✅ 已打开 CMD"

    if text in ("powershell", "ps"):
        subprocess.Popen("powershell.exe")
        return "✅ 已打开 PowerShell"

    if text in ("资源管理器", "文件管理器"):
        subprocess.Popen("explorer.exe")
        return "✅ 已打开资源管理器"

    if text == "任务管理器":
        subprocess.Popen("taskmgr.exe")
        return "✅ 已打开任务管理器"

    if text in ("控制面板", "control"):
        subprocess.Popen("control.exe")
        return "✅ 已打开控制面板"

    if text in ("设置", "settings"):
        subprocess.Popen(["explorer.exe", "ms-settings:"])
        return "✅ 已打开设置"

    if text in ("截图", "截图工具"):
        subprocess.Popen(["explorer.exe", "ms-screenclip:"])
        return "✅ 请框选截图区域"

    if text in ("画图", "mspaint"):
        subprocess.Popen("mspaint.exe")
        return "✅ 已打开画图"

    if text == "电脑信息":
        return "ℹ️\n" + get_system_info()

    return None


# 指令 → 预览文本的映射，与 execute 中的逻辑保持同步
_PREVIEWS = {
    "脚本配置": "↩ 打开脚本管理器",
    "计算器": "↩ 打开计算器",
    "记事本": "↩ 打开记事本",
    "cmd": "↩ 打开 CMD",
    "powershell": "↩ 打开 PowerShell",
    "ps": "↩ 打开 PowerShell",
    "资源管理器": "↩ 打开资源管理器",
    "文件管理器": "↩ 打开资源管理器",
    "任务管理器": "↩ 打开任务管理器",
    "控制面板": "↩ 打开控制面板",
    "control": "↩ 打开控制面板",
    "设置": "↩ 打开设置",
    "settings": "↩ 打开设置",
    "截图": "↩ 框选截图",
    "截图工具": "↩ 框选截图",
    "画图": "↩ 打开画图",
    "mspaint": "↩ 打开画图",
    "电脑信息": "↩ 查看系统信息",
    "转二维码": "↩ 剪贴板文字 → 二维码",
    "ocr": "↩ 框选区域识别文字",
    "提取文字": "↩ 框选区域识别文字",
    "截图翻译": "↩ 框选区域识别文字",
}

def preview(text: str):
    """返回指令的预览提示字符串，无匹配则返回 None。"""
    t = text.strip()
    p = _PREVIEWS.get(t)
    if p:
        return p
    if t == "ip":
        try:
            return f"📶 {_socket.gethostbyname(_socket.gethostname())}"
        except Exception:
            return "📶 获取失败"
    pomo = parse_pomodoro(t)
    if pomo:
        action, mins = pomo
        if action == 'stop':
            return '↩ 停止番茄钟'
        return f'↩ 开始 {mins} 分钟番茄钟 🍅'
    gitlab_p = GITLAB_PREVIEWS.get(t)
    if gitlab_p:
        return gitlab_p
    # 动态脚本触发命令预览
    try:
        for s in _sm_load_scripts():
            trigger = s.get("trigger", "").strip()
            if trigger == t:
                desc = s.get("description", "").strip()
                if desc:
                    return f"↩ {desc} [{trigger}]"
                return f"↩ 运行脚本「{trigger}」"
    except Exception:
        pass
    return None

def get_autocomplete(text: str) -> tuple[str, str] | None:
    """返回给定前缀的最佳补全结果及其说明（若有）。"""
    t = text.strip()
    if not t:
        return None
        
    candidates = {}
    for k, v in _PREVIEWS.items():
        candidates[k] = v.lstrip("↩ ")
    for k, v in GITLAB_PREVIEWS.items():
        candidates[k] = v.lstrip("↩ ")
        
    try:
        for s in _sm_load_scripts():
            trig = s.get("trigger", "").strip()
            desc = s.get("description", "").strip()
            if trig:
                candidates[trig] = desc
    except Exception:
        pass
    
    matches = [c for c in candidates if c.startswith(t) and c != t]
    if matches:
        matches.sort(key=len)
        best = matches[0]
        return best, candidates[best]
    return None

