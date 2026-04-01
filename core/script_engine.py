import subprocess
import ast
import operator
import os
import json as _json
import socket as _socket
from plugins.gitlab.preset import GITLAB_PREVIEWS
from utils.system_tools import get_system_info

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
    检查 text 是否匹配任意脚本触发命令。支持前缀带参数匹配。
    命中则通过 overlay.run_trigger() 运行，返回提示字符串；未命中返回 None。
    """
    t = text.strip()
    parts = t.split(maxsplit=1)
    prefix = parts[0] if len(parts) > 1 else t
    
    for s in _sm_load_scripts():
        trigger = s.get("trigger", "").strip()
        if trigger == t or trigger == prefix:
            if _script_overlay is not None:
                # 依然传递完整的带参数 text 进去，交由内部决定如何使用保留的参数
                _script_overlay.run_trigger(t, silent=False)
                return f"✅ 正在执行脚本「{trigger}」"
            return f"✅ 脚本触发成功（overlay 未就绪）"
    return None


def execute(text: str) -> str:
    """执行预设指令。命中返回 '✅ ...'，未命中返回 None。"""
    text = text.strip()

    # 检查自定义脚本触发命令
    _trigger_result = check_script_trigger(text)
    if _trigger_result is not None:
        return _trigger_result

    return None


def preview(text: str):
    """返回指令的预览提示字符串，无匹配则返回 None。支持前缀参数匹配。"""
    t = text.strip()
    parts = t.split(maxsplit=1)
    prefix = parts[0] if len(parts) > 1 else t
    
    from core.plugin_manager import get_plugin_previews
    pl_previews = get_plugin_previews()
    if t in pl_previews: return pl_previews[t]
    if prefix in pl_previews: return pl_previews[prefix]

    if t in ("脚本", "脚本配置") or prefix in ("脚本", "脚本配置"):
        return "⚙️ 打开脚本管理器"

    if t == "ip" or prefix == "ip":
        try:
            return f"📶 {_socket.gethostbyname(_socket.gethostname())}"
        except Exception:
            return "📶 获取失败"
            
    gitlab_p = GITLAB_PREVIEWS.get(t) or GITLAB_PREVIEWS.get(prefix)
    if gitlab_p:
        return gitlab_p
        
    # 动态脚本触发命令预览
    try:
        for s in _sm_load_scripts():
            trigger = s.get("trigger", "").strip()
            if trigger == t or trigger == prefix:
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
    parts = t.split(maxsplit=1)
    prefix = parts[0] if len(parts) > 1 else t
        
    candidates = {
        "脚本配置": "打开脚本管理器",
        "脚本": "打开脚本管理器"
    }
    from core.plugin_manager import get_plugin_previews
    for k, v in get_plugin_previews().items():
        candidates[k] = v.lstrip("🧩 ")
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
    
    # 补全列表匹配前缀：例如输入 "番" 补全 "番茄钟"
    matches = [c for c in candidates if c.startswith(prefix) and c != prefix]
    if matches:
        matches.sort(key=len)
        best = matches[0]
        return best, candidates[best]
    return None

