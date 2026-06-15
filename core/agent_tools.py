"""智能体工具：给聊天里的 bot / 团队成员「类 agent」能力——真的能执行系统命令、
读写文件、列目录、联网取数据、查系统信息。每个工具都返回一段文本结果（带超时/截断/
异常兜底），由聊天窗口的「智能体循环」把结果回喂给模型，模型据此继续直到完成任务。

安全：默认在 UI 里逐条确认后才执行（见 ai_chat_window 的审批/自动开关）；这里只负责
执行与兜底，不做权限判断。输出统一截断，命令带超时，绝不让单个工具卡死或刷屏。
"""
import os
import platform
import subprocess
import urllib.request

_MAX_OUT = 6000      # 单次工具输出上限（字符），超出截断
_TIMEOUT = 30        # shell 命令超时（秒）


def _truncate(s: str) -> str:
    s = s or ""
    if len(s) > _MAX_OUT:
        return s[:_MAX_OUT] + f"\n…（输出过长已截断，共 {len(s)} 字符）"
    return s


def shell(cmd: str, _content: str = "") -> str:
    cmd = (cmd or "").strip()
    if not cmd:
        return "（命令为空）"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=_TIMEOUT,
                           text=True, encoding="utf-8", errors="replace")
        out = (r.stdout or "").rstrip()
        if r.stderr and r.stderr.strip():
            out += ("\n" if out else "") + "[stderr] " + r.stderr.strip()
        out = out or "（无输出）"
        return _truncate(f"{out}\n[退出码 {r.returncode}]")
    except subprocess.TimeoutExpired:
        return f"（命令超过 {_TIMEOUT}s 超时，已终止）"
    except Exception as e:
        return f"（执行出错：{e}）"


def read_file(path: str, _content: str = "") -> str:
    try:
        with open(path.strip(), encoding="utf-8", errors="replace") as f:
            return _truncate(f.read()) or "（文件为空）"
    except Exception as e:
        return f"（读取失败：{e}）"


def write_file(path: str, content: str = "") -> str:
    try:
        path = path.strip()
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
        return f"（已写入 {path}，{len(content or '')} 字符）"
    except Exception as e:
        return f"（写入失败：{e}）"


def list_dir(path: str, _content: str = "") -> str:
    try:
        path = (path or ".").strip() or "."
        rows = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            try:
                tag = "<DIR>" if os.path.isdir(full) else f"{os.path.getsize(full)}"
            except Exception:
                tag = "?"
            rows.append(f"{tag:>10}  {name}")
        return _truncate(f"目录 {os.path.abspath(path)}（{len(rows)} 项）:\n" + "\n".join(rows))
    except Exception as e:
        return f"（列目录失败：{e}）"


def http_get(url: str, _content: str = "") -> str:
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return "（仅支持 http/https 链接）"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OpenHam-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(300000)
            ctype = r.headers.get("Content-Type", "")
        text = raw.decode("utf-8", "replace")
        return _truncate(f"[{ctype}]\n{text}")
    except Exception as e:
        return f"（请求失败：{e}）"


def sysinfo(_arg: str = "", _content: str = "") -> str:
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = "?"
    return (f"系统：{platform.platform()}\n"
            f"Python：{platform.python_version()}\n"
            f"用户：{user}\n"
            f"当前目录：{os.getcwd()}\n"
            f"处理器：{platform.processor() or platform.machine()}\n"
            f"CPU 逻辑核：{os.cpu_count()}")


_TOOLS = {
    "shell": shell, "cmd": shell, "run": shell,
    "read": read_file, "write": write_file,
    "list": list_dir, "ls": list_dir, "dir": list_dir,
    "http": http_get, "fetch": http_get, "get": http_get,
    "sysinfo": sysinfo, "info": sysinfo,
}

# 工具名 → 中文说明（UI 展示用）
TOOL_LABELS = {
    "shell": "执行命令", "read": "读取文件", "write": "写入文件",
    "list": "列出目录", "http": "联网获取", "sysinfo": "系统信息",
}


def normalize(name: str) -> str:
    """把别名归一到标准工具名。"""
    n = (name or "").strip().lower()
    fn = _TOOLS.get(n)
    for std, f in (("shell", shell), ("read", read_file), ("write", write_file),
                   ("list", list_dir), ("http", http_get), ("sysinfo", sysinfo)):
        if fn is f:
            return std
    return n


def run_tool(name: str, arg: str = "", content: str = "") -> str:
    """执行一个工具，返回文本结果。name 支持别名。"""
    fn = _TOOLS.get((name or "").strip().lower())
    if fn is None:
        return f"（未知工具：{name}，可用：shell/read/write/list/http/sysinfo）"
    try:
        return fn(arg, content)
    except Exception as e:
        return f"（工具执行异常：{e}）"
