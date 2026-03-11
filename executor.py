import subprocess
import ast
import operator
import os
import re as _re
from pathlib import Path
from openai import OpenAI

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
        result = _eval_node(tree)
        # 整数结果去掉小数点
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"= {result}"
    except ZeroDivisionError:
        return "= 除以零错误"
    except Exception:
        return None


def call_deepseek_stream(text: str, api_key: str):
    """流式调用 DeepSeek，逐个 yield 文本片段；失败时 yield 错误提示。"""
    print(f"[DeepSeek] 开始流式请求，文本: {text!r}，key 前8位: {api_key[:8]}...")
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个极度精简的助手，必须用中文回答，"
                        "回答内容严格不超过120个汉字，直接给出答案，不要任何废话。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=160,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                print(f"[DeepSeek] chunk: {delta!r}")
                yield delta
        print("[DeepSeek] 流式完成")
    except Exception as e:
        import traceback
        print(f"[DeepSeek] 异常: {e}")
        traceback.print_exc()
        yield f"❌ AI 请求失败：{e}"


def execute(text: str) -> str:
    """执行预设指令。命中返回 '✅ ...'，未命中返回 None。"""
    text = text.strip()

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

    return None


# 指令 → 预览文本的映射，与 execute 中的逻辑保持同步
_PREVIEWS = {
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
}

def preview(text: str):
    """返回指令的预览提示字符串，无匹配则返回 None。"""
    t = text.strip()
    p = _PREVIEWS.get(t)
    if p:
        return p
    pomo = parse_pomodoro(t)
    if pomo:
        action, mins = pomo
        if action == 'stop':
            return '↩ 停止番茄钟'
        return f'↩ 开始 {mins} 分钟番茄钟 🍅'
    return None


def parse_pomodoro(text: str):
    """解析番茄钟指令。返回 ('start', minutes) 或 ('stop', 0) 或 None。"""
    text = text.strip()
    if text in ('番茄停', '停番茄', '番茄 停', '番茄钟 停'):
        return ('stop', 0)
    m = _re.match(r'^番茄(?:钟)?\s*(\d+)?$', text)
    if m:
        mins = int(m.group(1)) if m.group(1) else 25
        if 1 <= mins <= 120:
            return ('start', mins)
    return None


# ─── 文件搜索 ────────────────────────────────────────────────

_SKIP_DIRS = frozenset({
    'node_modules', '.git', '__pycache__', 'venv', '.venv', 'env',
    'dist', 'build', '.idea', '.vscode', '$Recycle.Bin',
    'Windows', 'System32', 'SysWOW64',
    'Program Files', 'Program Files (x86)', 'ProgramData', 'AppData',
})


def _default_search_roots() -> list:
    home = Path.home()
    return [str(p) for p in [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home,
    ] if p.exists()]


def search_files(query: str, roots: list | None = None,
                 max_depth: int = 5, max_results: int = 20) -> list:
    """搜索文件名包含 query 的文件，返回 {'name', 'path', 'dir'} 列表。"""
    q = query.strip().lower()
    if not q:
        return []
    roots = roots or _default_search_roots()
    results: list = []
    seen: set = set()

    for root in roots:
        if len(results) >= max_results:
            break
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == '.' else len(rel.split(os.sep))
            if depth >= max_depth:
                dirnames.clear()
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith('.')
            ]
            for name in filenames:
                if q in name.lower():
                    full_path = os.path.join(dirpath, name)
                    if full_path not in seen:
                        seen.add(full_path)
                        results.append({
                            'name': name,
                            'path': full_path,
                            'dir': dirpath,
                        })
                        if len(results) >= max_results:
                            return results
    return results
