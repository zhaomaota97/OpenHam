"""AI 对话插件窗口：Monica 风格，带「Bots」（每个 bot 有自己的 system prompt 与会话历史）。

布局（三栏）：
- 最左 Bots 栏：每个 bot 一个头像；点头像切换 bot，点「+」新建 bot（名称 + system prompt），
  右键可编辑/删除。每个 bot 各自维护一份会话历史。
- 会话侧栏：搜索框 + 新建会话 + 当前 bot 下按时间分组（今天/昨天/7 天内/更早）的会话列表。
- 消息区：用户=右侧浅灰气泡；助手=「bot 头像 + bot 名 + 模型标签 + 纯 Markdown 正文」。

其余：流式响应、携带上下文（含 bot 的 system prompt）、持久化；模型沿用全局 AI 配置。
入口：主程序输入框里以 `--` 开头即唤起本窗口（见 plugins/ai_chat.py），无需其它触发词。
"""
import os
import re
import time
import uuid
import json
import datetime
import tempfile
import threading

from PyQt6.QtCore import (Qt, QObject, pyqtSignal, QTimer, QSize, QPointF,
                          QPoint, QRectF)
from PyQt6.QtGui import (QColor, QPixmap, QPainter, QFont, QIcon, QBrush, QPen,
                         QPolygonF, QTextCursor, QTextBlockFormat, QTextTable,
                         QTextTableFormat, QTextFrameFormat, QTextLength)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QScrollArea, QPlainTextEdit, QMenu,
    QLineEdit, QTextBrowser, QDialog, QDialogButtonBox,
    QCheckBox, QSpinBox, QDoubleSpinBox,
)

from ui.window_base import OpenHamWindowBase
from ui import icons, theme
from core import app_config
from core.ai_client import call_chat_stream, call_deepseek_sync, _CHAT_SYS
from core import agent_tools


# ── Bot 能力：交互控件（choices 快捷回复 / ask 澄清提问）──
CAP_CHOICES = "choices"
CAP_ASK = "ask"
CAP_TOOLS = "tools"      # 智能体：可执行命令/读写文件/联网等
CAP_MEMORY = "memory"    # 记忆：读取全局用户记忆（个性化、不重复追问已知信息）

# 用户明确说「记一下……」时，从其话里提炼出要记住的具体内容（直接入库，不再询问）
_MEM_EXTRACT_SYS = (
    "用户刚刚明确要求记住某些信息。请从最近对话里提炼出用户希望长期记住的【具体内容】，"
    "每条用一句简短客观的话陈述（如『用户在上海』『用户的生日是 5 月 1 日』『用户用 React 开发』）。"
    "通常就是用户这句话里点名要记的内容；若用户说『记住刚才那个』之类，则指上文提到的相应内容。"
    "用 JSON 数组返回这些内容（字符串），已有记忆里有的不要重复，确实没有可记的就返回 []。只输出 JSON。"
)

# 用户主动要求记忆的触发词（只有命中才入库，不再每轮自动嗅探）
_REMEMBER_TRIGGERS = (
    "记一下", "记下来", "记下", "记住", "记录一下", "记录下", "帮我记", "请记住",
    "请记一下", "记个", "记到记忆", "存一下", "存到记忆", "remember ", "记笔记",
)


def _wants_remember(text):
    """判断用户这句话是否在主动要求记忆。"""
    t = (text or "").strip().lower()
    return any(k in t for k in _REMEMBER_TRIGGERS)


def _memory_block(notes):
    """把全局记忆拼成注入 system 的文本块。"""
    if not notes:
        return ""
    lines = "\n".join(f"- {t}" for t in notes[:60])
    return ("【关于用户的已知信息（长期记忆）】\n" + lines + "\n"
            "请据此个性化回答：已经知道的信息不要再追问（如已知所在地就别再问城市）；"
            "记忆可能过时，若与用户当前所说明显冲突，以用户当前所说为准。")

_CHOICES_RULE = (
    "【快捷回复能力·重要】每次回答的最后，都要再追加一个「快捷追问选项」块，"
    "给出 2–4 个用户接下来最可能想问的问题或指令，方便其一键继续"
    "（仅当确实不适合时才省略，例如纯告别）。格式必须是独立的围栏代码块，"
    "语言标签写 openham:choices，每行一个选项、每个不超过 15 字：\n"
    "```openham:choices\n选项一\n选项二\n选项三\n```\n"
    "该块放在回答最末尾；块之外照常正常作答；不要解释这个块本身。"
)
_ASK_RULE = (
    "【澄清提问能力】当用户需求不够明确、有多种合理理解、或你需要关键信息才能动手时，"
    "不要凭空假设、也不要长篇文字追问，而要用一个 openham:ask 块提一个带可点选项的澄清问题，"
    "拿到用户选择后再继续。语法：\n"
    "```openham:ask\nquestion: 你的问题?\n- 选项一\n- 选项二\n- 选项三\n```\n"
    "若该问题允许多选，在标签后加 multi：第一行写 ```openham:ask multi。\n"
    "选项 2–5 个、简短；一次只问最关键的一个问题；意图已经清楚时不要提问，直接作答。"
)
_TOOLS_RULE = (
    "【智能体工具能力】你能调用本机工具真正地执行任务（执行命令、读写文件、列目录、联网获取、查系统信息）。"
    "当任务需要时，输出一个独立的围栏代码块，语言标签写 openham:tool，"
    "第一行写「工具: 主参数」，其余行作为附加内容（仅 write 需要）：\n"
    "· 执行命令(Windows)：```openham:tool\nshell: dir\n```\n"
    "· 读取文件：```openham:tool\nread: C:\\路径\\文件.txt\n```\n"
    "· 写入文件(第一行路径，其余行内容)：```openham:tool\nwrite: C:\\路径\\out.txt\n要写入的内容\n```\n"
    "· 列出目录：```openham:tool\nlist: C:\\路径\n```\n"
    "· 联网获取(网页/接口)：```openham:tool\nhttp: https://example.com\n```\n"
    "· 系统信息：```openham:tool\nsysinfo:\n```\n"
    "规则：一次只调用一个工具；调用后系统会把真实执行结果回给你，你据此继续，"
    "可多轮调用，直到完成后给出**不含工具块**的最终答复。不要假设/编造结果，必须真的调用工具拿到。"
    "命令要安全、最小化、避免破坏性操作（删除/格式化等先说明再谨慎执行）。"
)
# 匹配交互控件 / 工具围栏块（choices/ask/tool，保留出现顺序），以及流式未闭合的尾块
_KINDS = "choices|ask|tool"
_BLOCK_RE = re.compile(
    r"```[ \t]*openham:(" + _KINDS + r")([^\n]*)\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE)
_BLOCK_TRAILING_RE = re.compile(
    r"```[ \t]*openham:(?:" + _KINDS + r")[^\n]*\r?\n.*$",
    re.DOTALL | re.IGNORECASE)


def _parse_ask_body(body: str):
    q, opts = "", []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("question:") or low.startswith("q:"):
            q = s.split(":", 1)[1].strip()
        elif s[:1] in "-*•":
            o = s.lstrip("-*• ").strip()
            if o:
                opts.append(o)
        elif not q:
            q = s
    return q, opts[:6]


def _parse_tool_body(body: str):
    """工具块体：第一行「工具: 主参数」，其余行作为内容（write 用）。"""
    lines = (body or "").splitlines()
    first = lines[0].strip() if lines else ""
    content = "\n".join(lines[1:])
    if ":" in first or "：" in first:
        sep = "：" if ("：" in first and (":" not in first or first.index("：") < first.index(":"))) else ":"
        name, _, arg = first.partition(sep)
        name, arg = name.strip(), arg.strip()
    else:
        name, arg = first.strip(), ""
    return agent_tools.normalize(name), arg, content


def _parse_blocks(text: str):
    """提取消息里的 choices / ask / tool 块，返回 (去块后的 Markdown, 控件列表)。"""
    blocks = []
    for mt in _BLOCK_RE.finditer(text or ""):
        kind = mt.group(1).lower()
        mods = (mt.group(2) or "").lower()
        body = mt.group(3)
        if kind == "choices":
            items = [l.strip().lstrip("-*• ").strip() for l in body.splitlines()]
            items = [x for x in items if x][:4]
            if items:
                blocks.append({"type": "choices", "items": items})
        elif kind == "tool":
            tool, arg, content = _parse_tool_body(body)
            if tool:
                blocks.append({"type": "tool", "tool": tool, "arg": arg, "content": content})
        else:
            q, opts = _parse_ask_body(body)
            if opts:
                blocks.append({"type": "ask", "multi": ("multi" in mods),
                               "question": q, "options": opts})
    stripped = _BLOCK_RE.sub("", text or "")
    stripped = _BLOCK_TRAILING_RE.sub("", stripped)   # 流式未闭合时也先隐藏
    return stripped.strip(), blocks


def _first_tool_call(text: str):
    """返回消息里第一个 openham:tool 调用 {tool,arg,content}，没有则 None。"""
    _, blocks = _parse_blocks(text or "")
    for b in blocks:
        if b["type"] == "tool":
            return b
    return None


def _tool_head(tool, arg):
    label = agent_tools.TOOL_LABELS.get(tool, tool or "工具")
    return f"{label}" + (f" › {arg}" if arg else "")


def _api_msg(m):
    """存储消息 → 发给模型的 {role, content}。tool 角色转成 user(工具执行结果)。"""
    if m.get("role") == "tool":
        head = _tool_head(m.get("tool"), m.get("arg"))
        return {"role": "user", "content": f"【{head} 的执行结果】\n{m.get('content', '')}"}
    return {"role": m.get("role", "user"), "content": m.get("content", "")}


def _run_agent_loop(history, max_iters=8, cfg=None):
    """同步智能体循环（团队成员在工作线程里用）：调用模型→若有工具调用就执行→把结果回喂→
    继续，直到无工具调用或到上限，返回最终交付文本（团队流水线里工具自动执行）。"""
    msgs = list(history)
    final = ""
    for _ in range(max_iters):
        final = "".join(t for k, t in call_chat_stream(msgs, max_tokens=1500, cfg=cfg)
                        if k == "answer").strip()
        tc = _first_tool_call(final)
        if not tc:
            return final
        result = agent_tools.run_tool(tc["tool"], tc.get("arg", ""), tc.get("content", ""))
        msgs.append({"role": "assistant", "content": final})
        msgs.append({"role": "user", "content": f"【{_tool_head(tc['tool'], tc.get('arg'))} 的执行结果】\n{result}"})
    return final


def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_path() -> str:
    d = os.path.join(_base_dir(), "ai_chat")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "sessions.json")


def _norm_session(s: dict) -> dict:
    s.setdefault("id", uuid.uuid4().hex)
    s.setdefault("title", "新对话")
    s.setdefault("created", time.time())
    s.setdefault("messages", [])
    return s


MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")   # 仅此两款可选
MAX_OUTPUT = 393216                                 # 384K：文档所列单次最大输出
# 最大输出长度档位（必含最大档）；用档位选择代替自由输入，简单不易错
TOKEN_TIERS = [("4K", 4096), ("16K", 16384), ("64K", 65536), ("384K·最大", MAX_OUTPUT)]


def _snap_tier(v) -> int:
    """把任意 max_tokens 吸附到最接近的档位值。"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 65536
    return min((val for _, val in TOKEN_TIERS), key=lambda x: abs(x - v))


def _default_config() -> dict:
    """bot 的模型/参数配置（均为具体默认值，依 DeepSeek 文档；不再有「跟随全局」）。"""
    return {"model": "deepseek-v4-flash", "thinking": True,
            "reasoning_effort": "high", "max_tokens": 65536,
            "temperature": 1.0, "top_p": 1.0,
            "stop": [], "response_format": ""}


def _norm_config(cfg) -> dict:
    out = _default_config()
    if isinstance(cfg, dict):
        for k in out:
            if k in cfg and cfg[k] is not None:
                out[k] = cfg[k]
    if out["model"] not in MODELS:
        out["model"] = MODELS[0]
    if not isinstance(out["thinking"], bool):
        out["thinking"] = True
    if out["reasoning_effort"] not in ("high", "max"):
        out["reasoning_effort"] = "high"
    try:
        out["max_tokens"] = max(1, min(MAX_OUTPUT, int(out["max_tokens"] or 65536)))
    except (TypeError, ValueError):
        out["max_tokens"] = 65536
    return out


def _parse_seed(text: str) -> list:
    """把「用户：/助手：」分行文本解析成 [{role, content}] 自带对话。"""
    msgs, role, buf = [], None, []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(用户|助手|user|assistant|u|a)\s*[:：]\s*(.*)$", line, re.I)
        if m:
            if role is not None:
                c = "\n".join(buf).strip()
                if c:
                    msgs.append({"role": role, "content": c})
            r = m.group(1).lower()
            role = "user" if r in ("用户", "user", "u") else "assistant"
            buf = [m.group(2)]
        elif role is not None:
            buf.append(line)
    if role is not None:
        c = "\n".join(buf).strip()
        if c:
            msgs.append({"role": role, "content": c})
    return msgs


def _seed_to_text(seed) -> str:
    return "\n".join(("用户：" if m.get("role") == "user" else "助手：") + m.get("content", "")
                     for m in (seed or []))


def _make_bot(name: str, system: str, capabilities=None, sessions=None,
              config=None, seed=None) -> dict:
    return {"id": uuid.uuid4().hex, "name": name or "助手",
            "system": system or "", "capabilities": list(capabilities or []),
            "config": _norm_config(config), "seed": list(seed or []),
            "created": time.time(),
            "sessions": [_norm_session(s) for s in (sessions or [])]}


def _make_team(name: str, members, desc: str = "") -> dict:
    """团队：和 bot 一样存在 bots 列表里，用 is_team 区分。
    members 为成员（专家）bot id；desc 是团队目标，供编排器拆解任务时参考。
    团队本身扮演「编排器」：用户只和编排器对话，编排器拆任务给成员、再汇总交付。"""
    return {"id": uuid.uuid4().hex, "name": name or "团队", "is_team": True,
            "desc": desc or "", "members": list(members or []),
            "created": time.time(), "sessions": []}


def _load_store() -> dict:
    """返回 {"bots": [...], "current_bot": id}。兼容旧的「顶层 sessions」格式。"""
    p = _data_path()
    if not os.path.exists(p):
        return {"bots": [_make_bot("Hamster", "")], "current_bot": None}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"bots": [_make_bot("Hamster", "")], "current_bot": None}

    if "bots" not in data:   # 旧格式迁移：把原来的会话塞进默认 bot（Hamster）
        old = data.get("sessions", [])
        return {"bots": [_make_bot("Hamster", "", old)], "current_bot": None}

    bots = data.get("bots", [])
    for b in bots:
        b.setdefault("id", uuid.uuid4().hex)
        b.setdefault("name", "助手")
        b.setdefault("system", "")
        b.setdefault("capabilities", [])
        # 文字游戏已拆为独立插件，移除旧的 game/dice 能力（聊天仅保留 choices/ask）
        b["capabilities"] = [c for c in b["capabilities"] if c not in ("game", "dice")]
        b.setdefault("created", time.time())
        b["sessions"] = [_norm_session(s) for s in b.get("sessions", [])]
    if not bots:
        bots = [_make_bot("Hamster", "")]
    elif bots[0]["name"] == "默认助手":   # 旧默认助手改名为 Hamster
        bots[0]["name"] = "Hamster"
    # 全局记忆：跨所有 bot 共享，[{id,text,created}]
    memory = [m for m in data.get("memory", []) if isinstance(m, dict) and m.get("text")]
    return {"bots": bots, "current_bot": data.get("current_bot"), "memory": memory}


def _save_store(store: dict):
    try:
        with open(_data_path(), "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _time_group(ts: float) -> str:
    try:
        delta = (datetime.date.today()
                 - datetime.date.fromtimestamp(ts or time.time())).days
    except Exception:
        return "更早"
    if delta <= 0:
        return "今天"
    if delta == 1:
        return "昨天"
    if delta <= 7:
        return "7 天内"
    return "更早"


_GROUP_ORDER = ["今天", "昨天", "7 天内", "更早"]
# 克制、低饱和的配色（避免刺眼的纯色），圆角方形头像
_AVA_PALETTE = ["#5b6b8c", "#4a7c6f", "#8c5b6b", "#6b5b8c",
                "#8c7a5b", "#4f7d8a", "#7a8c5b", "#9c6f4a"]
_ava_cache = {}
_SS = 3   # 头像超采样倍率：按物理像素绘制再标 DPR，保证高分屏清晰不糊


def _letter_avatar(name: str, px: int = 34) -> QPixmap:
    name = name.strip() or "?"
    ch = name[:1].upper()
    key = (name, px)
    if key in _ava_cache:
        return _ava_cache[key]
    color = _AVA_PALETTE[(sum(ord(c) for c in name)) % len(_AVA_PALETTE)]
    s = int(px * _SS)
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    r = s * 0.30
    p.drawRoundedRect(0, 0, s, s, r, r)
    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setPixelSize(int(s * 0.42))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, ch)
    p.end()
    pm.setDevicePixelRatio(_SS)
    _ava_cache[key] = pm
    return pm


def _model_label() -> str:
    try:
        return app_config.get("ai_model") or "AI"
    except Exception:
        return "AI"


_check_cache = {}


def _check_png(checked: bool) -> str:
    """自绘勾选框：选中=靛紫底+白勾；未选=白底细边。返回 PNG 路径（供 QSS image:url）。"""
    if checked in _check_cache:
        return _check_cache[checked]
    s = 40
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rad = s * 0.26
    if checked:
        p.setBrush(QColor(theme.INDIGO))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(1, 1, s - 2, s - 2, rad, rad)
        pen = QPen(QColor("#ffffff"))
        pen.setWidthF(s * 0.12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(s * 0.27, s * 0.52),
                                  QPointF(s * 0.42, s * 0.67),
                                  QPointF(s * 0.73, s * 0.33)]))
    else:
        p.setBrush(QColor(theme.CARD))
        pen = QPen(QColor(theme.BORDER_IN))
        pen.setWidthF(s * 0.06)
        p.setPen(pen)
        p.drawRoundedRect(2, 2, s - 4, s - 4, rad, rad)
    p.end()
    try:
        d = os.path.join(tempfile.gettempdir(), "openham_chk")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"chk_{int(checked)}.png")
        pm.save(path, "PNG")
        _check_cache[checked] = path.replace("\\", "/")
        return _check_cache[checked]
    except Exception:
        return ""


def _checkbox_style() -> str:
    return (f"QCheckBox {{ color: {theme.TEXT}; font-size: 14px; spacing: 8px;"
            f" background: transparent; }}"
            f"QCheckBox::indicator {{ width: 19px; height: 19px;"
            f" image: url({_check_png(False)}); }}"
            f"QCheckBox::indicator:checked {{ image: url({_check_png(True)}); }}")


def _spin_qss() -> str:
    return (f"QSpinBox, QDoubleSpinBox {{ background: {theme.SUBTLE}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER}; border-radius: 7px; padding: 4px 8px;"
            f" min-width: 96px; font-size: 13px; }}"
            f"QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {theme.TEXT3};"
            f" background: {theme.CARD}; }}")


class _Segmented(QWidget):
    """分段选择（二/三选一）。纯按钮，无原生弹层、不发黑。options=[(label, value), ...]"""

    def __init__(self, options, value=None, parent=None):
        super().__init__(parent)
        self._value = value if value is not None else options[0][1]
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self._btns = []
        for label, val in options:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(val == self._value)
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.SUBTLE}; color: {theme.TEXT2};"
                f" border: 1px solid {theme.BORDER}; border-radius: 7px;"
                f" padding: 6px 14px; font-size: 13px; }}"
                f"QPushButton:checked {{ background: {theme.ACCENT}; color: #fff;"
                f" border-color: {theme.ACCENT}; font-weight: 600; }}")
            b.clicked.connect(lambda _, v=val: self._pick(v))
            self._btns.append((b, val))
            h.addWidget(b)
        h.addStretch(1)

    def _pick(self, v):
        self._value = v
        for b, val in self._btns:
            b.setChecked(val == v)

    def value(self):
        return self._value


class _BotDialog(QDialog):
    """新建 / 编辑 bot：名称 + system prompt + 能力 + 模型与参数配置。"""

    def __init__(self, parent=None, name="", system="", capabilities=None,
                 config=None, seed=None):
        super().__init__(parent)
        self.setWindowTitle("新建 Bot" if not name else "编辑 Bot")
        self.setMinimumSize(500, 620)
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        cfg = _norm_config(config)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(20, 18, 20, 10)
        lay.setSpacing(8)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        lay.addWidget(self._lbl("名称"))
        self.name_in = QLineEdit(name)
        self.name_in.setPlaceholderText("例如：翻译官、代码助手、营养师…")
        lay.addWidget(self.name_in)

        lay.addSpacing(4)
        lay.addWidget(self._lbl("System Prompt（人设 / 指令，可留空用默认）"))
        self.sys_in = QPlainTextEdit(system)
        self.sys_in.setPlaceholderText(
            "例如：你是一名专业英汉翻译，只输出译文，不加解释。")
        self.sys_in.setFixedHeight(110)
        lay.addWidget(self.sys_in)

        lay.addSpacing(4)
        lay.addWidget(self._lbl("能力"))
        caps = capabilities or []
        self.cap_choices = QCheckBox("快捷回复按钮（AI 给出可点击的追问选项）")
        self.cap_ask = QCheckBox("澄清提问（AI 主动用单选/多选问清你的需求）")
        self.cap_tools = QCheckBox("智能体工具（可执行命令 / 读写文件 / 联网，⚠ 谨慎）")
        self.cap_memory = QCheckBox("记忆（读取全局用户记忆，知道你的所在地/偏好等，不重复追问）")
        for cb, on in ((self.cap_choices, CAP_CHOICES in caps),
                       (self.cap_ask, CAP_ASK in caps),
                       (self.cap_tools, CAP_TOOLS in caps),
                       (self.cap_memory, CAP_MEMORY in caps)):
            cb.setChecked(on)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.setStyleSheet(_checkbox_style())
            lay.addWidget(cb)

        # ── 模型 & 思考（常用，直接可见）─────────────────────────────────
        lay.addSpacing(10)
        lay.addWidget(self._lbl("模型"))
        self.model_seg = _Segmented([(m, m) for m in MODELS], cfg["model"])
        lay.addWidget(self.model_seg)

        lay.addWidget(self._sub("思考模式（开启后展示思考过程）"))
        self.think_seg = _Segmented([("开启", "on"), ("关闭", "off")],
                                    "on" if cfg["thinking"] else "off")
        lay.addWidget(self.think_seg)

        # ── 高级（默认折叠）：输出长度 / 采样 / 停止 / 响应格式 / 自带对话 ──
        lay.addSpacing(12)
        self.adv_btn = QPushButton()
        self.adv_btn.setCheckable(True)
        self.adv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adv_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT}; border: none;"
            f" text-align: left; padding: 6px 2px; font-size: 13px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {theme.INDIGO}; }}")
        self.adv_btn.toggled.connect(self._toggle_adv)
        lay.addWidget(self.adv_btn)

        self.adv_box = QWidget()
        av = QVBoxLayout(self.adv_box)
        av.setContentsMargins(0, 2, 0, 0)
        av.setSpacing(8)

        av.addWidget(self._sub("推理强度 reasoning_effort（思考模式下生效）"))
        self.effort_seg = _Segmented([("high", "high"), ("max", "max")], cfg["reasoning_effort"])
        av.addWidget(self.effort_seg)

        av.addWidget(self._sub("最大输出长度 max_tokens（按档位选择）"))
        self.maxtok_seg = _Segmented(TOKEN_TIERS, _snap_tier(cfg["max_tokens"]))
        av.addWidget(self.maxtok_seg)

        srow = QHBoxLayout()
        srow.setSpacing(16)
        tcol = QVBoxLayout()
        tcol.setSpacing(4)
        tcol.addWidget(self._sub("温度 temperature（0–2，默认 1）"))
        self.temp_spin = self._dspin(0.0, 2.0, 0.1, 2, cfg["temperature"])
        tcol.addWidget(self.temp_spin)
        srow.addLayout(tcol)
        pcol = QVBoxLayout()
        pcol.setSpacing(4)
        pcol.addWidget(self._sub("top_p（0–1，默认 1）"))
        self.topp_spin = self._dspin(0.0, 1.0, 0.05, 2, cfg["top_p"])
        pcol.addWidget(self.topp_spin)
        srow.addLayout(pcol)
        av.addLayout(srow)

        av.addWidget(self._sub("停止序列 stop（逗号分隔，最多 16 个，可留空）"))
        self.stop_in = QLineEdit(", ".join(cfg["stop"] or []))
        self.stop_in.setPlaceholderText("如：。, ###, END")
        av.addWidget(self.stop_in)

        av.addWidget(self._sub("响应格式 response_format"))
        self.fmt_seg = _Segmented([("文本", ""), ("JSON", "json")], cfg["response_format"] or "")
        av.addWidget(self.fmt_seg)

        av.addWidget(self._sub("自带对话（每次新会话都从这段对话继续，不显示在聊天里）"))
        hint = QLabel("用「用户：」「助手：」开头分行写，模型会把它当作已发生的上下文接着续聊。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT3}; font-size: 12px;")
        av.addWidget(hint)
        self.seed_in = QPlainTextEdit(_seed_to_text(seed or []))
        self.seed_in.setPlaceholderText("用户：你好\n助手：你好！我是你的专属助手，已经了解你的偏好，请直接说需求。")
        self.seed_in.setFixedHeight(130)
        av.addWidget(self.seed_in)

        lay.addWidget(self.adv_box)
        self.adv_btn.setChecked(bool(seed))   # 有自带对话则默认展开
        self._toggle_adv(bool(seed))

        lay.addStretch(1)

        # 底部按钮（固定在滚动区外）
        bar = QWidget()
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(20, 8, 20, 14)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        bh.addWidget(btns)
        root.addWidget(bar)

    def _lbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600;")
        return l

    def _sub(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; margin-top: 4px;")
        return l

    def _toggle_adv(self, on):
        self.adv_box.setVisible(on)
        self.adv_btn.setText(("▾ " if on else "▸ ")
                             + "高级（输出长度 / 采样 / 停止 / 响应格式 / 自带对话）")

    def _dspin(self, lo, hi, step, decimals, value):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(decimals)
        s.setValue(float(value))
        s.setStyleSheet(_spin_qss())
        return s

    def values(self):
        caps = []
        if self.cap_choices.isChecked():
            caps.append(CAP_CHOICES)
        if self.cap_ask.isChecked():
            caps.append(CAP_ASK)
        if self.cap_tools.isChecked():
            caps.append(CAP_TOOLS)
        if self.cap_memory.isChecked():
            caps.append(CAP_MEMORY)
        config = {
            "model": self.model_seg.value(),
            "thinking": self.think_seg.value() == "on",
            "reasoning_effort": self.effort_seg.value(),
            "max_tokens": int(self.maxtok_seg.value()),
            "temperature": round(self.temp_spin.value(), 2),
            "top_p": round(self.topp_spin.value(), 2),
            "stop": [s.strip() for s in self.stop_in.text().split(",") if s.strip()][:16],
            "response_format": self.fmt_seg.value(),
        }
        seed = _parse_seed(self.seed_in.toPlainText())
        return (self.name_in.text().strip(),
                self.sys_in.toPlainText().strip(), caps, config, seed)


class _TeamDialog(QDialog):
    """新建 / 编辑团队：团队名 + 目标说明 + 勾选成员（专家 bot）。"""

    def __init__(self, parent=None, name="", members=None, candidates=None, desc=""):
        super().__init__(parent)
        self.setWindowTitle("团队")
        self.setMinimumWidth(400)
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        from PyQt6.QtWidgets import QCheckBox
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        lab = QLabel("团队名")
        lab.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600;")
        lay.addWidget(lab)
        self.name_in = QLineEdit(name)
        self.name_in.setPlaceholderText("例如：分析报告团队、产品评审团…")
        lay.addWidget(self.name_in)
        lay.addSpacing(2)
        lab_d = QLabel("团队目标 / 编排说明（可留空）")
        lab_d.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600;")
        lay.addWidget(lab_d)
        self.desc_in = QPlainTextEdit(desc)
        self.desc_in.setPlaceholderText("例如：负责产出专业的行业分析报告——由编排器把用户需求"
                                        "拆给各专家、再汇总成稿。")
        self.desc_in.setFixedHeight(70)
        lay.addWidget(self.desc_in)
        lay.addSpacing(2)
        lab2 = QLabel("成员专家（2 个及以上；每个 bot 的人设即其专长）")
        lab2.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600;")
        lay.addWidget(lab2)
        members = set(members or [])
        self._boxes = []
        host = QWidget()
        hv = QVBoxLayout(host)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(4)
        for b in (candidates or []):
            cb = QCheckBox(b["name"])
            cb.setChecked(b["id"] in members)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.setStyleSheet(_checkbox_style())
            cb._bot_id = b["id"]
            self._boxes.append(cb)
            hv.addWidget(cb)
        hv.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setMaximumHeight(220)
        sc.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        sc.setWidget(host)
        lay.addWidget(sc)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self):
        ids = [cb._bot_id for cb in self._boxes if cb.isChecked()]
        return (self.name_in.text().strip(), self.desc_in.toPlainText().strip(), ids)


class _MemoryDialog(QDialog):
    """全局记忆管理：查看 / 删除 / 手动添加。"""

    def __init__(self, parent, memory):
        super().__init__(parent)
        self.setWindowTitle("全局记忆")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        self._items = [dict(m) for m in (memory or [])]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        tip = QLabel("这些记忆对【所有带「记忆」能力的 Bot】生效——它们聊天时会知道这些信息。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        lay.addWidget(tip)
        self._list_host = QWidget()
        self._lv = QVBoxLayout(self._list_host)
        self._lv.setContentsMargins(0, 0, 0, 0)
        self._lv.setSpacing(5)
        self._lv.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setMinimumHeight(220)
        sc.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        sc.setWidget(self._list_host)
        lay.addWidget(sc, 1)
        for m in self._items:
            self._add_row(m)
        add = QHBoxLayout()
        add.setSpacing(8)
        self._in = QLineEdit()
        self._in.setPlaceholderText("手动添加一条记忆，如：用户在上海")
        self._in.returnPressed.connect(self._add_manual)
        add.addWidget(self._in, 1)
        addb = QPushButton("添加")
        addb.setObjectName("primary")
        addb.clicked.connect(self._add_manual)
        add.addWidget(addb)
        lay.addLayout(add)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.button(QDialogButtonBox.StandardButton.Close).setText("完成")
        btns.rejected.connect(self.accept)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
        self._empty = QLabel("（还没有记忆。聊天时确认入库，或在上方手动添加。）")
        self._empty.setStyleSheet(f"color: {theme.TEXT3}; font-size: 12px;")
        self._lv.insertWidget(0, self._empty)
        self._empty.setVisible(not self._items)

    def _add_row(self, m):
        row = QFrame()
        row.setObjectName("memItem")
        row.setStyleSheet(
            f"#memItem {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; }}")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 6, 8, 6)
        h.setSpacing(8)
        lab = QLabel(m["text"])
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; background: transparent;"
                          " border: none;")
        h.addWidget(lab, 1)
        rm = QPushButton()
        rm.setIcon(icons.qicon("delete", color="#c87a6a"))
        rm.setIconSize(QSize(13, 13))
        rm.setFixedSize(24, 24)
        rm.setCursor(Qt.CursorShape.PointingHandCursor)
        rm.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 6px; }"
                         f"QPushButton:hover {{ background: #fbeeec; }}")
        rm.clicked.connect(lambda _, mm=m, rr=row: self._del(mm, rr))
        h.addWidget(rm)
        self._lv.insertWidget(self._lv.count() - 1, row)

    def _del(self, m, row):
        if m in self._items:
            self._items.remove(m)
        row.setParent(None)
        row.deleteLater()
        self._empty.setVisible(not self._items)

    def _add_manual(self):
        t = self._in.text().strip()
        if not t:
            return
        m = {"id": uuid.uuid4().hex, "text": t, "created": time.time()}
        self._items.append(m)
        self._add_row(m)
        self._in.clear()
        self._empty.setVisible(False)

    def result_memory(self):
        return self._items


class _MessageRow(QWidget):
    """一条消息。用户=右侧浅灰气泡；助手=左侧「头像+名称+模型标签+Markdown 正文」。"""

    def __init__(self, role: str, bot_name="Hamster", bot_avatar=None,
                 host=None, parent=None):
        super().__init__(parent)
        self.role = role
        self._raw = ""
        self.host = host
        self._pinned = False
        # 限定到自身，避免 bare 样式级联到子 QMenu（导致复制下拉菜单背景变黑）
        self.setObjectName("msgRow")
        self.setStyleSheet("#msgRow { background: transparent; }")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if role == "user":
            self.browser = None
            self.bubble = QLabel("")
            self.bubble.setWordWrap(True)
            self.bubble.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self.bubble.setStyleSheet(
                f"QLabel {{ background: {theme.SUBTLE}; color: {theme.TEXT};"
                f" border-radius: 14px; padding: 10px 14px; font-size: 15px;"
                f" selection-background-color: {theme.SEL_TEXT_BG};"
                f" selection-color: {theme.SEL_TEXT_FG}; }}")
            self.bubble.installEventFilter(self)   # 开始新选择时清掉其它消息选区
            self.actions = self._build_actions()
            rightw = QWidget()
            rightw.setStyleSheet("background: transparent;")
            rv = QVBoxLayout(rightw)
            rv.setContentsMargins(0, 0, 0, 0)
            rv.setSpacing(3)
            rv.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignRight)
            rv.addWidget(self.actions, 0, Qt.AlignmentFlag.AlignRight)
            outer.addStretch(1)
            outer.addWidget(rightw)
        elif role == "tool":
            self.browser = None
            self.bubble = None
            self.actions = None
            col = QVBoxLayout()
            col.setContentsMargins(30, 0, 0, 0)     # 与助手正文左缩进对齐
            col.setSpacing(0)
            card = QFrame()
            card.setObjectName("toolRes")
            card.setStyleSheet(
                f"#toolRes {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
                f" border-radius: 10px; }}")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(12, 8, 12, 10)
            cv.setSpacing(4)
            hdr = QLabel("⎿ 工具结果")
            hdr.setStyleSheet(f"color: {theme.TEXT3}; font-size: 11px; font-weight: 600;"
                              " background: transparent;")
            cv.addWidget(hdr)
            self.tool_out = QLabel("")
            self.tool_out.setWordWrap(True)
            self.tool_out.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.tool_out.setStyleSheet(
                "QLabel { background: transparent; color: #2a2a2e;"
                " font-family: Consolas, 'Courier New', monospace; font-size: 12px; }")
            self.tool_out.installEventFilter(self)
            cv.addWidget(self.tool_out)
            col.addWidget(card)
            outer.addLayout(col, 1)
        else:
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(6)
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(8)
            avatar = QLabel()
            avatar.setPixmap(bot_avatar if bot_avatar is not None
                             else _letter_avatar(bot_name, 22))
            avatar.setFixedSize(22, 22)
            head.addWidget(avatar)
            name = QLabel(bot_name)
            name.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;"
                " background: transparent;")
            head.addWidget(name)
            badge = QLabel(_model_label())
            badge.setStyleSheet(
                f"QLabel {{ color: {theme.INDIGO}; background: {theme.INDIGO_SOFT};"
                " border-radius: 6px; padding: 1px 7px; font-size: 11px; }}")
            head.addWidget(badge)
            head.addStretch(1)
            col.addLayout(head)

            # 思考过程（思考模式下出现，可折叠；优雅的浅灰卡片）
            self.reason_box = QFrame()
            self.reason_box.setObjectName("reasonBox")
            self.reason_box.setStyleSheet(
                f"#reasonBox {{ background: #f7f7fb; border: 1px solid {theme.BORDER};"
                f" border-radius: 10px; }}")
            rv = QVBoxLayout(self.reason_box)
            rv.setContentsMargins(12, 8, 12, 9)
            rv.setSpacing(6)
            self.reason_btn = QPushButton("  思考过程")
            self.reason_btn.setCheckable(True)
            self.reason_btn.setIcon(icons.qicon("angle_right", color=theme.TEXT2))
            self.reason_btn.setIconSize(QSize(12, 12))
            self.reason_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.reason_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme.TEXT2}; border: none;"
                f" text-align: left; font-size: 12px; font-weight: 600; padding: 0; }}"
                f"QPushButton:hover {{ color: {theme.TEXT}; }}")
            self.reason_btn.toggled.connect(self._toggle_reason)
            rv.addWidget(self.reason_btn)
            self.reason_lbl = QLabel("")
            self.reason_lbl.setWordWrap(True)
            self.reason_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.reason_lbl.setStyleSheet(
                f"QLabel {{ background: transparent; color: {theme.TEXT2}; font-size: 13px; }}")
            self.reason_lbl.setVisible(False)
            self.reason_lbl.installEventFilter(self)
            rv.addWidget(self.reason_lbl)
            self.reason_box.setVisible(False)
            col.addWidget(self.reason_box)

            self.browser = QTextBrowser()
            self.browser.setOpenExternalLinks(True)
            self.browser.setFrameShape(QFrame.Shape.NoFrame)
            self.browser.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setStyleSheet(
                f"QTextBrowser {{ background: transparent; border: none;"
                f" color: #1d1d1f; font-size: 15px;"
                f" selection-background-color: {theme.SEL_TEXT_BG};"
                f" selection-color: {theme.SEL_TEXT_FG}; }}")
            self.browser.viewport().installEventFilter(self)   # 选区互斥
            self.browser.document().setDefaultStyleSheet(
                "pre, code { background:#f3f3f5; font-family:Consolas,monospace; }"
                "a { color:#6e56cf; }")
            col.addWidget(self.browser)
            # 交互控件容器（choices 快捷回复 / ask 澄清提问），默认隐藏
            self.blocks_host = QWidget()
            self.blocks_host.setStyleSheet("background: transparent;")
            self.blocks_layout = QVBoxLayout(self.blocks_host)
            self.blocks_layout.setContentsMargins(0, 2, 0, 0)
            self.blocks_layout.setSpacing(8)
            self.blocks_host.setVisible(False)
            col.addWidget(self.blocks_host)
            self.actions = self._build_actions()
            col.addWidget(self.actions)
            self.bubble = None
            outer.addLayout(col, 1)

        if getattr(self, "actions", None) is not None:
            self._set_buttons(False)   # 默认隐藏按钮（占位条仍在），hover/置顶时显示

    def _build_actions(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("msgActions")
        bar.setStyleSheet("#msgActions { background: transparent; }")
        bar.setFixedHeight(28)            # 始终占位，避免 hover 出现按钮时抖动
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)

        def mkbtn(icon_name, tip):
            b = QPushButton()
            b.setIcon(icons.qicon(icon_name, color=theme.TEXT3))
            b.setIconSize(QSize(13, 13))
            b.setFixedSize(26, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; border-radius: 6px; }}"
                f"QPushButton:hover {{ background: {theme.SUBTLE}; }}")
            return b

        self.copy_btn = mkbtn("copy", "复制")
        if self.role == "assistant":
            self.copy_btn.clicked.connect(self._copy_menu)
            self.regen_btn = mkbtn("refresh", "重新生成")
            self.regen_btn.clicked.connect(
                lambda: self.host and self.host._regenerate(self))
            h.addWidget(self.copy_btn)
            h.addWidget(self.regen_btn)
            h.addStretch(1)
        else:
            self.copy_btn.clicked.connect(
                lambda: self.host and self.host._copy_plain(self))
            self.edit_btn = mkbtn("edit", "编辑")
            self.edit_btn.clicked.connect(
                lambda: self.host and self.host._edit_user(self))
            h.addWidget(self.copy_btn)
            h.addWidget(self.edit_btn)
        return bar

    def _copy_menu(self):
        if self.host is None:
            return
        menu = theme.style_menu(QMenu(self))
        a1 = menu.addAction("复制为 Markdown")
        a2 = menu.addAction("复制为纯文本")
        chosen = menu.exec(self.copy_btn.mapToGlobal(
            self.copy_btn.rect().bottomLeft()))
        if chosen == a1:
            self.host._copy_markdown(self)
        elif chosen == a2:
            self.host._copy_plain(self)

    def _set_buttons(self, vis: bool):
        if getattr(self, "actions", None) is None:   # tool 结果行无操作按钮
            return
        self.copy_btn.setVisible(vis)
        if self.role == "assistant":
            self.regen_btn.setVisible(vis)
        else:
            self.edit_btn.setVisible(vis)

    def set_actions_pinned(self, pinned: bool):
        """最新一条 AI 回答固定显示按钮；其余仅 hover 显示。"""
        self._pinned = bool(pinned)
        self._set_buttons(self._pinned)

    def enterEvent(self, event):
        self._set_buttons(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._pinned:
            self._set_buttons(False)
        super().leaveEvent(event)

    def eventFilter(self, obj, event):
        # 在某条消息里开始新选择时，清掉其它消息的旧选区（各消息是独立文本控件，不会自动互斥）
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress and self.host is not None:
            self.host._clear_text_selections(obj)
        return False

    def set_text(self, text: str, final: bool = False):
        self._raw = text
        if self.role == "tool":
            self.tool_out.setText(text)
        elif self.role == "user":
            self.bubble.setText(text)
        else:
            md, blocks = _parse_blocks(text)       # 去掉控件块再渲染 Markdown
            self.browser.setMarkdown(md)
            self._improve_typography()
            self._style_tables()
            self._fit_height()
            if final:                              # 仅在回答完成时渲染交互控件
                self._render_blocks(blocks)

    def set_reasoning(self, text: str, streaming: bool = False):
        """显示/更新「思考过程」卡片。streaming=True 时展开并显示「正在思考…」。"""
        if self.role != "assistant" or getattr(self, "reason_box", None) is None:
            return
        self._reasoning = text or ""
        if not text:
            self.reason_box.setVisible(False)
            return
        self.reason_box.setVisible(True)
        self.reason_lbl.setText(text)
        if streaming:
            self.reason_btn.setText("  正在思考…")
            if not self.reason_btn.isChecked():
                self.reason_btn.setChecked(True)   # 思考中默认展开
        else:
            self.reason_btn.setText("  思考过程")

    def _toggle_reason(self, on: bool):
        self.reason_lbl.setVisible(on)
        self.reason_btn.setIcon(icons.qicon("angle_down" if on else "angle_right",
                                            color=theme.TEXT2))

    def _render_blocks(self, blocks):
        while self.blocks_layout.count():
            it = self.blocks_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        if not blocks or self.host is None:
            self.blocks_host.setVisible(False)
            return
        for b in blocks:
            if b["type"] == "choices":
                self.blocks_layout.addWidget(self._make_choices_widget(b["items"]))
            elif b["type"] == "tool":
                self.blocks_layout.addWidget(self._make_tool_widget(b))
            else:
                self.blocks_layout.addWidget(self._make_ask_widget(b))
        # choices 全部为空时容器可能为空
        self.blocks_host.setVisible(self.blocks_layout.count() > 0)

    def _make_tool_widget(self, block) -> QWidget:
        """智能体的工具调用卡片：图标 + 工具名 + 命令/参数（只读展示）。"""
        card = QFrame()
        card.setObjectName("toolCall")
        card.setStyleSheet(
            f"#toolCall {{ background: #f4f1fb; border: 1px solid #e2dcf6;"
            f" border-radius: 10px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(3)
        label = agent_tools.TOOL_LABELS.get(block.get("tool"), block.get("tool", "工具"))
        head = QLabel(f"🔧 {label}")
        head.setStyleSheet(f"color: {theme.INDIGO}; font-size: 12px; font-weight: 700;"
                           " background: transparent; border: none;")
        v.addWidget(head)
        arg = block.get("arg", "")
        content = block.get("content", "")
        body = arg + (("\n" + content) if (block.get("tool") == "write" and content) else "")
        if body.strip():
            cmd = QLabel(body)
            cmd.setWordWrap(True)
            cmd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cmd.setStyleSheet(
                "QLabel { background: transparent; color: #3a3550; border: none;"
                " font-family: Consolas, 'Courier New', monospace; font-size: 12px; }")
            v.addWidget(cmd)
        return card

    def _make_choices_widget(self, items) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for c in items:
            b = QPushButton(c)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.INDIGO_SOFT}; color: {theme.INDIGO};"
                f" border: 1px solid #d8d6fb; border-radius: 15px;"
                f" padding: 6px 14px; font-size: 14px; }}"
                f"QPushButton:hover {{ background: #ece8fb; }}")
            b.clicked.connect(lambda _=False, t=c: self.host._send_quick(t))
            h.addWidget(b)
        h.addStretch(1)
        return w

    def _make_ask_widget(self, block) -> QWidget:
        card = QFrame()
        card.setObjectName("askCard")
        card.setStyleSheet(
            f"#askCard {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 12px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        q = QLabel(block.get("question") or "请选择：")
        q.setWordWrap(True)
        q.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;"
                        " background: transparent; border: none;")
        v.addWidget(q)
        opts = block.get("options", [])

        if block.get("multi"):
            from PyQt6.QtWidgets import QCheckBox
            checks = []
            for o in opts:
                cb = QCheckBox(o)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                cb.setStyleSheet(_checkbox_style())
                v.addWidget(cb)
                checks.append(cb)
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 0)
            submit = QPushButton("提交")
            submit.setCursor(Qt.CursorShape.PointingHandCursor)
            submit.setStyleSheet(
                f"QPushButton {{ background: {theme.ACCENT}; color: #fff; border: none;"
                f" border-radius: 9px; padding: 7px 18px; font-size: 14px; }}"
                f"QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}")

            def _submit():
                picked = [c.text() for c in checks if c.isChecked()]
                if picked and self.host:
                    self.host._send_quick("、".join(picked))
            submit.clicked.connect(_submit)
            row.addWidget(submit)
            other = self._ask_other_btn()
            row.addWidget(other)
            row.addStretch(1)
            v.addLayout(row)
        else:
            for o in opts:
                b = QPushButton(o)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(
                    f"QPushButton {{ background: {theme.CARD}; color: {theme.TEXT};"
                    f" border: 1px solid {theme.BORDER_IN}; border-radius: 9px;"
                    f" padding: 9px 12px; font-size: 14px; text-align: left; }}"
                    f"QPushButton:hover {{ background: {theme.INDIGO_SOFT};"
                    f" border-color: #d8d6fb; }}")
                b.clicked.connect(lambda _=False, t=o: self.host and self.host._send_quick(t))
                v.addWidget(b)
            v.addWidget(self._ask_other_btn())
        return card

    def _ask_other_btn(self) -> QPushButton:
        other = QPushButton("其他（自己输入）")
        other.setCursor(Qt.CursorShape.PointingHandCursor)
        other.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT2};"
            f" border: none; padding: 5px 2px; font-size: 13px; text-align: left; }}"
            f"QPushButton:hover {{ color: {theme.INDIGO}; }}")
        other.clicked.connect(lambda: self.host and self.host._focus_input())
        return other

    def _improve_typography(self):
        """放宽行距与段间距，让 Markdown 不再挤成一团。"""
        doc = self.browser.document()
        cur = QTextCursor(doc)
        cur.select(QTextCursor.SelectionType.Document)
        bf = QTextBlockFormat()
        bf.setLineHeight(165, 1)   # 1 = ProportionalHeight，约 1.65 倍行距
        bf.setTopMargin(2)
        bf.setBottomMargin(9)
        cur.mergeBlockFormat(bf)

    def _style_tables(self):
        """给 Markdown 表格补上边框/内边距/表头底色（Qt 默认渲染太朴素）。"""
        doc = self.browser.document()
        tables = []
        stack = list(doc.rootFrame().childFrames())
        while stack:
            f = stack.pop()
            if isinstance(f, QTextTable):
                tables.append(f)
            stack.extend(f.childFrames())
        for tbl in tables:
            fmt = QTextTableFormat()
            fmt.setBorder(1)
            fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            fmt.setBorderBrush(QBrush(QColor(theme.BORDER_IN)))
            fmt.setCellPadding(7)
            fmt.setCellSpacing(0)
            try:
                fmt.setBorderCollapse(True)
            except Exception:
                pass
            fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
            tbl.setFormat(fmt)
            # 表头行底色
            for c in range(tbl.columns()):
                cell = tbl.cellAt(0, c)
                cf = cell.format()
                cf.setBackground(QBrush(QColor(theme.SUBTLE)))
                cell.setFormat(cf)

    def set_width(self, content_px: int):
        if self.role == "user":
            self.bubble.setMaximumWidth(max(120, int(content_px * 0.72)))
        elif self.role == "tool":
            self.tool_out.setMaximumWidth(max(160, content_px - 30))
        else:
            self.browser.setFixedWidth(max(160, content_px))
            self._fit_height()

    def _fit_height(self):
        if self.role != "user" and self.browser is not None:
            doc = self.browser.document()
            doc.setTextWidth(self.browser.viewport().width() or self.browser.width())
            self.browser.setFixedHeight(max(24, int(doc.size().height()) + 6))


class _ChatSignals(QObject):
    chunk = pyqtSignal(int, str, str)        # (gen, kind: reasoning/answer, text)
    done = pyqtSignal(int)
    error = pyqtSignal(int, str)
    team_plan = pyqtSignal(int, object)       # gen, {"summary":..,"steps":[{bot,task}]}
    team_step = pyqtSignal(int, int, str)     # gen, 步骤序号, 成员交付内容
    team_final = pyqtSignal(int, str)         # gen, 编排器最终交付
    tool_done = pyqtSignal(int, str)          # gen, 工具执行结果
    mem_candidates = pyqtSignal(object)       # 提炼出的记忆候选 [str]


class AIChatWindow(OpenHamWindowBase):
    """AI 对话主窗口（单例，由插件 setup 创建并复用）。"""

    def __init__(self):
        super().__init__(title="聊天", min_w=940, min_h=600)
        self.resize(1100, 880)            # 默认窗口更高一些
        self._autoscroll = True           # 流式生成时是否自动滚到底

        self.store = _load_store()
        self.bots = self.store["bots"]
        self.cur_bot_id = self.store.get("current_bot") or self.bots[0]["id"]
        if not any(b["id"] == self.cur_bot_id for b in self.bots):
            self.cur_bot_id = self.bots[0]["id"]
        bot = self._cur_bot()
        self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None

        self._rows = []
        self._msgs = []
        self._gen = 0
        self._streaming = False
        self._assistant_row = None
        self._assistant_text = ""
        self._assistant_reasoning = ""
        self._filter = ""
        # 团队：编排器拆任务 → 成员按流程依次交付 → 编排器汇总交付给用户
        self._team_active = False
        self._team = None            # 当前团队 dict
        self._team_task = ""         # 用户这次的需求
        self._team_plan = []         # [{"bot":id,"task":str}]
        self._team_idx = 0
        self._team_deliv = []        # [(成员名, 交付内容)]
        self._team_msgs = []         # 本轮要落库的消息（含编排过程）
        self._typing_row = None      # 当前「工作中…」占位行
        self._typing_phase = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.timeout.connect(self._animate_typing)
        # 智能体：工具调用循环
        self._agent_auto = False     # 是否自动执行工具（否则逐条确认）
        self._agent_iter = 0         # 本轮已执行的工具步数（防止无限循环）
        self._pending_tool = None    # 待确认执行的工具调用
        self._cur_tool = None        # 正在执行的工具
        self._tool_row = None        # 「执行中…」结果行
        self._tool_bar = None        # 工具审批条
        # 全局记忆
        self.store.setdefault("memory", [])
        self._mem_bar = None         # 「已记住」提示条

        self._sig = _ChatSignals()
        self._sig.chunk.connect(self._on_chunk)
        self._sig.done.connect(self._on_done)
        self._sig.error.connect(self._on_error)
        self._sig.team_plan.connect(self._on_team_plan)
        self._sig.team_step.connect(self._on_team_step)
        self._sig.team_final.connect(self._on_team_final)
        self._sig.tool_done.connect(self._on_tool_done)
        self._sig.mem_candidates.connect(self._on_mem_candidates)

        self._build_ui()
        self._add_sidebar_toggle()
        self.title_bar.installEventFilter(self)   # 双击标题栏最大化/还原
        # 基类底部 grip 行会在三栏下方留一道白条、还挤裁掉左栏「新建Bot」按钮；
        # 移除它让内容铺满，缩放手柄改成卡片右下角浮层。
        try:
            self.card_layout.takeAt(self.card_layout.count() - 1)
            self.size_grip.setParent(self.card)
            self.size_grip.raise_()
        except Exception:
            pass
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    # ── 标题栏：折叠/展开会话面板 ─────────────────────────────────────
    def _toggle_btn(self, tip):
        btn = QPushButton()
        btn.setIcon(icons.qicon("panel", color=theme.TEXT2))
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(tip)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        btn.clicked.connect(self._toggle_sidebar)
        return btn

    def _add_sidebar_toggle(self):
        # 全局记忆管理按钮
        self.mem_btn = QPushButton()
        self.mem_btn.setIcon(icons.qicon("memory", color=theme.TEXT2))
        self.mem_btn.setFixedSize(28, 28)   # 图标尺寸跟随基类标题栏按钮默认，保持一致
        self.mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mem_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mem_btn.setToolTip("全局记忆（查看 / 删除 / 添加）")
        self.mem_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        self.mem_btn.clicked.connect(self._open_memory)
        self.header_tools_layout.addWidget(self.mem_btn)
        # 标题栏的按钮只在「面板已折叠」时出现，用来展开（折叠按钮在面板标题内，折叠后看不见）
        self.sidebar_btn = self._toggle_btn("展开会话面板")
        self.sidebar_btn.setVisible(False)
        self.header_tools_layout.addWidget(self.sidebar_btn)

    def _open_memory(self):
        dlg = _MemoryDialog(self, self.store.get("memory", []))
        dlg.exec()
        self.store["memory"] = dlg.result_memory()
        _save_store(self.store)

    def _toggle_sidebar(self):
        show = not self._sidebar.isVisible()
        self._sidebar.setVisible(show)
        self.sidebar_btn.setVisible(not show)   # 折叠后才显示标题栏的展开按钮
        QTimer.singleShot(0, lambda: [m.set_width(self._content_width()) for m in self._msgs])

    # ── 界面骨架 ──────────────────────────────────────────────────────
    def _build_ui(self):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_rail())
        self._sidebar = self._build_sidebar()
        h.addWidget(self._sidebar)
        h.addWidget(self._build_chat(), 1)
        self.content_layout.addWidget(row, 1)

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("botRail")
        rail.setFixedWidth(72)
        rail.setStyleSheet(
            f"#botRail {{ background: {theme.SUBTLE};"
            f" border-right: 1px solid {theme.BORDER};"
            f" border-bottom-left-radius: {theme.R_CARD}px; }}")
        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 12, 0, 12)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # 默认 bot（Hamster）= 顶部 logo 头像，固定在最上方
        self.default_holder = QVBoxLayout()
        self.default_holder.setContentsMargins(0, 0, 0, 0)
        self.default_holder.setSpacing(0)
        dh = QWidget()
        dh.setStyleSheet("background: transparent;")
        dh.setLayout(self.default_holder)
        v.addWidget(dh, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(2)

        # 用户自建 bots 容器（可滚动）
        self.bot_col = QVBoxLayout()
        self.bot_col.setContentsMargins(0, 0, 0, 0)
        self.bot_col.setSpacing(8)
        self.bot_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host.setLayout(self.bot_col)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setStyleSheet("background: transparent;")
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(host)
        v.addWidget(sc, 1)

        add = QPushButton()
        add.setIcon(icons.qicon("add", color=theme.TEXT2))
        add.setIconSize(QSize(18, 18))
        add.setFixedSize(44, 44)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("新建 Bot / 团队")
        add.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px dashed {theme.BORDER_IN};"
            f" border-radius: 12px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        add.clicked.connect(lambda: self._add_menu(add))
        v.addWidget(add, 0, Qt.AlignmentFlag.AlignHCenter)
        return rail

    def _add_menu(self, anchor):
        menu = theme.style_menu(QMenu(self))
        a_bot = menu.addAction(icons.qicon("robot"), "新建 Bot")
        a_grp = menu.addAction(icons.qicon("users"), "新建团队")
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen == a_bot:
            self._create_bot()
        elif chosen == a_grp:
            self._create_team()

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sideBar")
        side.setFixedWidth(244)
        side.setStyleSheet(
            f"#sideBar {{ background: {theme.CARD};"
            f" border-right: 1px solid {theme.BORDER}; }}")
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(10)

        self.bot_title = QLabel("")
        self.bot_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: 700;"
            " background: transparent;")
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title_row.addWidget(self.bot_title)
        title_row.addStretch(1)
        self.collapse_btn = self._toggle_btn("折叠会话面板")   # 会话面板标题右侧的折叠按钮
        title_row.addWidget(self.collapse_btn)
        v.addLayout(title_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索会话")
        self.search.setFixedHeight(36)
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.qicon("search", color=theme.TEXT3),
                              QLineEdit.ActionPosition.LeadingPosition)
        # 等宽聚焦边框 + 固定高度，避免聚焦时被裁剪
        self.search.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 9px;"
            f" padding: 0 8px; font-size: 14px; }}"
            f"QLineEdit:focus {{ border: 1px solid {theme.ACCENT}; }}")
        self.search.textChanged.connect(self._on_search)
        v.addWidget(self.search)

        self.new_btn = QPushButton("  新建会话")
        self.new_btn.setIcon(icons.qicon("add", color=theme.INDIGO))
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.setFixedHeight(38)
        self.new_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.CARD}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 10px;"
            f" font-size: 14px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {theme.INDIGO_SOFT}; border-color: #d8d6fb; }}")
        self.new_btn.clicked.connect(lambda: self._new_session())
        v.addWidget(self.new_btn)

        self.session_list = QListWidget()
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._session_menu)
        self.session_list.itemClicked.connect(self._on_session_clicked)
        # 标题过长不横向滚动，改为右侧省略号
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.session_list.setWordWrap(False)
        self.session_list.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none;"
            f" font-size: 14px; }}"
            f"QListWidget::item {{ border-radius: 8px; padding: 9px 10px; color: {theme.TEXT}; }}"
            f"QListWidget::item:hover {{ background: {theme.SUBTLE}; }}"
            f"QListWidget::item:selected {{ background: {theme.SELECT}; color: {theme.TEXT}; }}")
        v.addWidget(self.session_list, 1)
        return side

    def _build_chat(self) -> QWidget:
        right = QWidget()
        self._chat_area = right
        right.setObjectName("chatArea")
        right.setStyleSheet(
            f"#chatArea {{ background: {theme.BG};"
            f" border-bottom-right-radius: {theme.R_CARD}px; }}")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.msg_host = QWidget()
        self.msg_host.setStyleSheet("background: transparent;")
        self.msg_layout = QVBoxLayout(self.msg_host)
        self.msg_layout.setContentsMargins(28, 18, 28, 14)
        self.msg_layout.setSpacing(10)
        self.msg_layout.addStretch(1)
        self.scroll.setWidget(self.msg_host)
        rv.addWidget(self.scroll, 1)

        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(28, 6, 28, 18)
        wl.setSpacing(0)
        card = QFrame()
        card.setObjectName("inputCard")
        card.setStyleSheet(
            f"#inputCard {{ background: {theme.CARD};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 16px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 12, 10)
        cl.setSpacing(6)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("发消息……（Enter 发送，Shift+Enter 换行）")
        self.input.setFrameShape(QFrame.Shape.NoFrame)
        self.input.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; font-size: 15px; }")
        self.input.setFixedHeight(58)
        self.input.installEventFilter(self)
        cl.addWidget(self.input)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        self.model_pill = QLabel("  " + _model_label())
        self.model_pill.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT2}; background: {theme.SUBTLE};"
            " border-radius: 9px; padding: 3px 10px; font-size: 12px; }}")
        bottom.addWidget(self.model_pill)
        # 智能体「自动执行工具」开关（仅在当前 bot 有 tools 能力时显示）
        self.agent_toggle = QPushButton("✋ 逐条确认")
        self.agent_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.agent_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.agent_toggle.setToolTip("智能体执行工具的方式：逐条确认 / 自动执行")
        self.agent_toggle.clicked.connect(self._toggle_agent_auto)
        bottom.addWidget(self.agent_toggle)
        bottom.addStretch(1)
        self.send_btn = QPushButton()
        self.send_btn.setIcon(icons.qicon("send", color="#ffffff"))
        self.send_btn.setIconSize(QSize(17, 17))
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedSize(38, 38)
        self.send_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; border: none; border-radius: 19px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}"
            f"QPushButton:disabled {{ background: {theme.TEXT3}; }}")
        self.send_btn.clicked.connect(self._on_send_btn)
        bottom.addWidget(self.send_btn)
        cl.addLayout(bottom)
        wl.addWidget(card)
        rv.addWidget(wrap)
        return right

    # ── Bots ──────────────────────────────────────────────────────────
    def _cur_bot(self):
        for b in self.bots:
            if b["id"] == self.cur_bot_id:
                return b
        return self.bots[0]

    @staticmethod
    def _is_team(b):
        return bool(b and (b.get("is_team") or b.get("is_group")))

    def _bot_by_id(self, bid):
        return next((b for b in self.bots if b["id"] == bid), None)

    def _bot_name(self, bid):
        b = self._bot_by_id(bid)
        return b["name"] if b else None

    def _members(self, group):
        """群成员（解析为真实 bot 字典，过滤已删除/非法成员）。"""
        out = []
        for mid in group.get("members", []):
            b = self._bot_by_id(mid)
            if b and not self._is_team(b):
                out.append(b)
        return out

    def _team_avatar(self, group, px):
        """团队头像：把最多 4 个成员的小头像拼成一格。"""
        members = self._members(group)[:4]
        s = int(px * _SS)
        pm = QPixmap(s, s)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.INDIGO_SOFT))
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.3, s * 0.3)
        n = len(members)
        if n == 0:
            p.setBrush(QColor(theme.INDIGO))
            p.drawEllipse(QRectF(s * 0.3, s * 0.3, s * 0.4, s * 0.4))
        elif n == 1:
            p.drawPixmap(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64).toRect(),
                         self._bot_avatar(members[0], px))
        else:
            half = s * 0.46
            gap = s * 0.04
            # 2 个并排；3-4 个 2x2
            spots = ([(gap, s * 0.27), (s - half - gap, s * 0.27)] if n == 2 else
                     [(gap, gap), (s - half - gap, gap),
                      (gap, s - half - gap), (s - half - gap, s - half - gap)])
            for m, (ox, oy) in zip(members, spots):
                p.drawPixmap(QRectF(ox, oy, half, half).toRect(),
                             self._bot_avatar(m, px))
        p.end()
        pm.setDevicePixelRatio(_SS)
        return pm

    def _clear_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _bot_avatar(self, bot, px):
        """默认 bot（Hamster，bots[0]）用 logo 头像；团队用拼图头像；其余用字母头像。"""
        if self._is_team(bot):
            return self._team_avatar(bot, px)
        if self.bots and bot["id"] == self.bots[0]["id"]:
            return _brand_pixmap(px)
        return _letter_avatar(bot["name"], px)

    def _make_bot_row(self, bot) -> QWidget:
        active = bot["id"] == self.cur_bot_id
        btn = QPushButton()
        btn.setIcon(QIcon(self._bot_avatar(bot, 40)))
        btn.setIconSize(QSize(40, 40))
        btn.setFixedSize(52, 52)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._is_team(bot):
            mnames = "、".join(m["name"] for m in self._members(bot)) or "空群"
            btn.setToolTip(f"团队：{bot['name']}（{mnames}）")
        else:
            btn.setToolTip(bot["name"])
        # 选中=柔和浅底（无描边/无指示条），克制优雅
        btn.setStyleSheet(
            f"QPushButton {{ background: {theme.SELECT if active else 'transparent'};"
            f" border: none; border-radius: 15px; padding: 0; }}"
            f"QPushButton:hover {{ background: {theme.SELECT if active else theme.HOVER}; }}")
        bid = bot["id"]
        btn.clicked.connect(lambda _=False, b=bid: self._select_bot(b))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=bid, w=btn: self._bot_menu(b, w, pos))
        return btn

    def _refresh_bots(self):
        # 默认 bot（Hamster）固定最上
        self._clear_layout(self.default_holder)
        self.default_holder.addWidget(self._make_bot_row(self.bots[0]),
                                      0, Qt.AlignmentFlag.AlignHCenter)
        # 其余用户 bot
        self._clear_layout(self.bot_col)
        for b in self.bots[1:]:
            self.bot_col.addWidget(self._make_bot_row(b), 0, Qt.AlignmentFlag.AlignHCenter)
        self.bot_col.addStretch(1)

    def _select_bot(self, bot_id: str):
        if bot_id == self.cur_bot_id:
            return
        self._gen += 1
        self._cancel_team()
        self._set_streaming(False)
        self.cur_bot_id = bot_id
        self.store["current_bot"] = bot_id
        self._filter = ""
        if hasattr(self, "search"):
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        bot = self._cur_bot()
        self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    def _create_bot(self):
        dlg = _BotDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, system, caps, config, seed = dlg.values()
        if not name:
            name = "新 Bot"
        bot = _make_bot(name, system, capabilities=caps, config=config, seed=seed)
        self.bots.append(bot)
        self.cur_bot_id = bot["id"]
        self.store["current_bot"] = bot["id"]
        self.cur_id = None
        _save_store(self.store)
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    def _create_team(self):
        candidates = [b for b in self.bots if not self._is_team(b)]
        dlg = _TeamDialog(self, candidates=candidates)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, desc, ids = dlg.values()
        if len(ids) < 2:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "团队", "请至少选择 2 个成员。")
            return
        grp = _make_team(name or "团队", ids, desc)
        self.bots.append(grp)
        self.cur_bot_id = grp["id"]
        self.store["current_bot"] = grp["id"]
        self.cur_id = None
        _save_store(self.store)
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    def _edit_team(self, gid):
        grp = self._bot_by_id(gid)
        if not grp:
            return
        candidates = [b for b in self.bots if not self._is_team(b)]
        dlg = _TeamDialog(self, grp["name"], grp.get("members"), candidates,
                          grp.get("desc", ""))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, desc, ids = dlg.values()
        if len(ids) < 2:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "团队", "请至少选择 2 个成员。")
            return
        grp["name"] = name or grp["name"]
        grp["desc"] = desc
        grp["members"] = ids
        _save_store(self.store)
        self._refresh_bots()
        if gid == self.cur_bot_id:
            self.bot_title.setText(grp["name"])
            self._load_current()

    def _bot_menu(self, bot_id: str, anchor: QWidget, pos):
        bot = self._bot_by_id(bot_id)
        is_grp = self._is_team(bot)
        menu = theme.style_menu(QMenu(self))
        act_edit = menu.addAction(icons.qicon("edit"), "编辑团队" if is_grp else "编辑 Bot")
        act_del = menu.addAction(icons.qicon("delete"), "解散团队" if is_grp else "删除 Bot")
        is_def = bool(self.bots) and bot_id == self.bots[0]["id"]
        if is_def or len(self.bots) <= 1:   # 默认 Hamster 不可删
            act_del.setEnabled(False)
        chosen = menu.exec(anchor.mapToGlobal(pos))
        if chosen == act_edit:
            self._edit_team(bot_id) if is_grp else self._edit_bot(bot_id)
        elif chosen == act_del:
            self._delete_bot(bot_id)

    def _edit_bot(self, bot_id: str):
        bot = next((b for b in self.bots if b["id"] == bot_id), None)
        if not bot:
            return
        dlg = _BotDialog(self, bot["name"], bot["system"],
                         bot.get("capabilities"), bot.get("config"), bot.get("seed"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, system, caps, config, seed = dlg.values()
        bot["name"] = name or bot["name"]
        bot["system"] = system
        bot["capabilities"] = caps
        bot["config"] = config
        bot["seed"] = seed
        _save_store(self.store)
        self._refresh_bots()
        if bot_id == self.cur_bot_id:
            self.bot_title.setText(bot["name"])
            self._load_current()   # 助手头像/名称随之刷新

    def _delete_bot(self, bot_id: str):
        if len(self.bots) <= 1 or bot_id == self.bots[0]["id"]:   # 默认 Hamster 不可删
            return
        self.bots = [b for b in self.bots if b["id"] != bot_id]
        # 从团队成员里剔除被删 bot；成员不足 2 的群自动解散
        for g in [b for b in self.bots if self._is_team(b)]:
            g["members"] = [m for m in g.get("members", []) if m != bot_id]
        self.bots = [b for b in self.bots
                     if not (self._is_team(b) and len(b.get("members", [])) < 2)]
        self.store["bots"] = self.bots
        if not any(b["id"] == self.cur_bot_id for b in self.bots):
            self._gen += 1
            self._set_streaming(False)
            self.cur_bot_id = self.bots[0]["id"]
            self.store["current_bot"] = self.cur_bot_id
            bot = self._cur_bot()
            self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None
        _save_store(self.store)
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    # ── 会话管理（作用于当前 bot）────────────────────────────────────
    def _sessions(self):
        return self._cur_bot()["sessions"]

    def _cur(self):
        for s in self._sessions():
            if s["id"] == self.cur_id:
                return s
        return None

    def _new_session(self, persist: bool = True):
        cur = self._cur()
        if cur is not None and not cur["messages"]:
            self.input.setFocus()
            return
        s = _norm_session({"title": "新对话", "created": time.time(), "messages": []})
        self._sessions().insert(0, s)
        self.cur_id = s["id"]
        if persist:
            _save_store(self.store)
        self._refresh_session_list()
        self._load_current()
        self.input.setFocus()

    def _on_search(self, text: str):
        self._filter = (text or "").strip().lower()
        self._refresh_session_list()

    def _refresh_session_list(self):
        self.bot_title.setText(self._cur_bot()["name"])
        self.session_list.clear()
        groups = {g: [] for g in _GROUP_ORDER}
        for s in self._sessions():
            if self._filter and self._filter not in (s.get("title") or "").lower():
                continue
            groups[_time_group(s.get("created", 0))].append(s)
        for g in _GROUP_ORDER:
            if not groups[g]:
                continue
            header = QListWidgetItem(g)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            f = header.font()
            f.setPointSize(max(7, f.pointSize() - 1))
            header.setFont(f)
            header.setForeground(QColor(theme.TEXT3))
            self.session_list.addItem(header)
            for s in groups[g]:
                it = QListWidgetItem(s["title"] or "新对话")
                it.setData(Qt.ItemDataRole.UserRole, s["id"])
                self.session_list.addItem(it)
                if s["id"] == self.cur_id:
                    self.session_list.setCurrentItem(it)

    def _on_session_clicked(self, item: QListWidgetItem):
        sid = item.data(Qt.ItemDataRole.UserRole)
        if not sid or sid == self.cur_id:
            return
        self._gen += 1
        self._set_streaming(False)
        self.cur_id = sid
        self._load_current()

    def _session_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        menu = theme.style_menu(QMenu(self))
        act_del = menu.addAction(icons.qicon("delete"), "删除会话")
        if menu.exec(self.session_list.mapToGlobal(pos)) == act_del:
            self._delete_session(sid)

    def _delete_session(self, sid: str):
        bot = self._cur_bot()
        bot["sessions"] = [s for s in bot["sessions"] if s["id"] != sid]
        if self.cur_id == sid:
            self._gen += 1
            self._set_streaming(False)
            self.cur_id = bot["sessions"][0]["id"] if bot["sessions"] else None
        _save_store(self.store)
        self._refresh_session_list()
        self._load_current()

    # ── 消息渲染 ──────────────────────────────────────────────────────
    def _clear_messages(self):
        self._clear_tool_approval()
        self._clear_mem_bar()
        for w in self._rows:
            w.setParent(None)
            w.deleteLater()
        self._rows = []
        self._msgs = []

    def _clear_text_selections(self, except_obj=None):
        """在某条消息里开始新选择时，清掉其它消息的旧选区（实现跨消息单一选区）。"""
        for r in self._msgs:
            br = getattr(r, "browser", None)
            if br is not None and br.viewport() is not except_obj:
                c = br.textCursor()
                if c.hasSelection():
                    c.clearSelection()
                    br.setTextCursor(c)
            bub = getattr(r, "bubble", None)
            if bub is not None and bub is not except_obj and bub.hasSelectedText():
                bub.setSelection(0, 0)

    def _add_message(self, role: str, text: str, final: bool = False,
                     bot=None) -> _MessageRow:
        # 团队里每条助手消息按「说话的成员」显示头像/名字；否则用当前 bot
        b = bot or self._cur_bot()
        msg = _MessageRow(role, bot_name=b["name"],
                          bot_avatar=self._bot_avatar(b, 22), host=self)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, msg)
        self._rows.append(msg)
        self._msgs.append(msg)
        msg.set_width(self._content_width())
        msg.set_text(text, final=final)
        return msg

    def _content_width(self) -> int:
        vw = self.scroll.viewport().width() or 700
        return max(200, vw - 56)

    def _load_current(self):
        self._clear_messages()
        cur = self._cur()
        if cur is None or not cur["messages"]:
            self._show_empty_hint()
        if cur is not None:
            is_grp = self._is_team(self._cur_bot())
            for m in cur["messages"]:
                spk = (self._bot_by_id(m.get("bot"))
                       if is_grp and m["role"] == "assistant" else None)
                row = self._add_message(m["role"], m["content"], final=True, bot=spk)
                if m.get("reasoning") and row is not None:
                    row.set_reasoning(m["reasoning"], streaming=False)
        self._update_action_visibility()
        self._sync_agent_toggle()
        self._scroll_to_bottom()

    def _show_empty_hint(self):
        bot = self._cur_bot()
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 60, 0, 0)
        bl.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(self._bot_avatar(bot, 56))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(logo)
        if self._is_team(bot):
            mnames = "、".join(m["name"] for m in self._members(bot)) or "（无成员）"
            htext = f"团队「{bot['name']}」：{mnames}"
            stext = "把需求交给团队，编排器会拆给成员、再汇总交付"
        else:
            htext = f"我是「{bot['name']}」，有什么可以帮你的？"
            stext = "在下方输入开始对话"
        hint = QLabel(htext)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {theme.TEXT2}; font-size: 16px;"
                           " font-weight: 600; background: transparent;")
        bl.addWidget(hint)
        sub = QLabel(stext)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {theme.TEXT3}; font-size: 13px; background: transparent;")
        bl.addWidget(sub)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, box)
        self._rows.append(box)

    # ── 发送 / 流式 ───────────────────────────────────────────────────
    def _on_send_btn(self):
        if self._streaming:
            self._stop()         # 生成中点击=停止
        else:
            self._send()

    def _send(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        if self._streaming:
            self._stop()         # 发送新消息=中止当前生成
        cur = self._cur()
        if cur is None:
            s = _norm_session({"title": "新对话", "created": time.time(), "messages": []})
            self._sessions().insert(0, s)
            self.cur_id = s["id"]
            self._refresh_session_list()
            cur = self._cur()
        if not cur["messages"]:
            self._clear_messages()
        self.input.clear()

        self._agent_iter = 0            # 新一轮用户消息：重置智能体工具步数
        self._pending_tool = None
        self._clear_tool_approval()
        self._clear_mem_bar()
        cur["messages"].append({"role": "user", "content": text})
        urow = self._add_message("user", text)
        self._maybe_title(cur, text)
        _save_store(self.store)
        self._run_completion()
        self._scroll_row_to_top(urow)   # 新发的消息滚到顶部，完整可见

    def _send_quick(self, text: str):
        """点击快捷回复/选项：把该文本作为用户消息发出。"""
        if self._streaming or not (text or "").strip():
            return
        self.input.setPlainText(text)
        self._send()

    def _focus_input(self):
        """「其他（自己输入）」：聚焦输入框让用户自由补充。"""
        self.input.setFocus()

    def _run_completion(self):
        """基于当前会话已有消息，流式生成一条新的助手回答（供发送/重新生成/编辑后复用）。"""
        cur = self._cur()
        if cur is None:
            return
        if self._is_team(self._cur_bot()):
            self._run_team_completion()
            return
        self._team_active = False          # 普通单 bot 回答
        self._autoscroll = True            # 新一轮生成：恢复自动滚到底
        self._assistant_text = ""
        self._assistant_reasoning = ""     # 思考过程（思考模式下流式累积）
        self._assistant_row = self._add_message("assistant", "▍")
        self._scroll_to_bottom()

        history = []
        bot = self._cur_bot()
        caps = bot.get("capabilities", [])
        sys_prompt = (bot.get("system") or "").strip()
        extras = []
        if CAP_MEMORY in caps:                           # 读取全局记忆
            blk = _memory_block([m["text"] for m in self.store.get("memory", [])])
            if blk:
                extras.append(blk)
        if CAP_TOOLS in caps:
            extras.append(_TOOLS_RULE)
        if CAP_ASK in caps:
            extras.append(_ASK_RULE)
        if CAP_CHOICES in caps:
            extras.append(_CHOICES_RULE)
        if extras:                                       # 绑定能力则并入规则
            sys_prompt = (sys_prompt or _CHAT_SYS).strip() + "\n\n" + "\n\n".join(extras)
        if sys_prompt:
            history.append({"role": "system", "content": sys_prompt})
        # 自带对话：作为「已发生的上下文」插在会话消息之前，模型据此接着续聊（不入库、不显示）
        for sm in bot.get("seed", []):
            if sm.get("content"):
                history.append({"role": sm.get("role", "user"), "content": sm["content"]})
        history += [_api_msg(m) for m in cur["messages"]]
        cfg = bot.get("config")
        self._gen += 1
        gen = self._gen
        self._set_streaming(True)

        def work():
            try:
                for kind, piece in call_chat_stream(history, cfg=cfg):
                    if gen != self._gen:
                        return
                    self._sig.chunk.emit(gen, kind, piece)
                if gen == self._gen:
                    self._sig.done.emit(gen)
            except Exception as e:
                if gen == self._gen:
                    self._sig.error.emit(gen, str(e))

        threading.Thread(target=work, daemon=True).start()

    # ── 团队：编排器拆任务 → 成员按流程交付 → 编排器汇总 ────────────────
    def _run_team_completion(self):
        cur = self._cur()
        team = self._cur_bot()
        members = self._members(team)
        if cur is None:
            return
        if not members:
            self._add_message("assistant", "（这个团队还没有成员，右键团队头像编辑、添加专家吧）",
                              final=True, bot=team)
            return
        task = next((m["content"] for m in reversed(cur["messages"])
                     if m["role"] == "user"), "")
        self._autoscroll = True
        self._team_active = True
        self._team = team
        self._team_task = task
        self._team_plan, self._team_idx, self._team_deliv, self._team_msgs = [], 0, [], []
        self._set_streaming(True)
        self._gen += 1
        gen = self._gen
        self._typing_row = self._add_message("assistant", "•", final=False, bot=team)
        if not self._typing_timer.isActive():
            self._typing_timer.start(380)
        self._scroll_to_bottom()
        history_msgs = list(cur["messages"])

        def work():
            plan = self._plan_task(team, members, task, history_msgs)
            if gen == self._gen:
                self._sig.team_plan.emit(gen, plan)
        threading.Thread(target=work, daemon=True).start()

    def _plan_task(self, team, members, task, messages):
        roster = "\n".join(
            f"- {m['name']}：{(m.get('system') or '通用助手').strip()[:60]}" for m in members)
        ctx = ""
        prev = messages[:-1]
        if prev:
            tail = []
            for mm in prev[-6:]:
                who = "用户" if mm["role"] == "user" else (self._bot_name(mm.get("bot")) or "团队")
                tail.append(f"{who}：{mm['content'][:200]}")
            ctx = "\n之前的对话：\n" + "\n".join(tail) + "\n"
        sysp = (f"你是团队「{team['name']}」的编排器（队长）。"
                + (f"团队目标：{team.get('desc')}。" if team.get("desc") else "")
                + "用户把需求交给你，你要把它拆解成有序的工作步骤，分配给合适的成员专家，"
                "下游成员能用到上游成员的产出。只输出 JSON："
                '{"summary":"一句话告诉用户你的安排","steps":[{"member":"成员名","task":"交给这个成员做的具体事"}]}。'
                "steps 按执行顺序，可只用部分成员；若只是寒暄或无需分工，steps 给空数组、"
                "在 summary 里直接回应用户。务必只输出 JSON。")
        prompt = (f"团队成员（可调用的专家）：\n{roster}\n{ctx}\n用户需求：{task}\n\n请给出编排。只回 JSON。")
        name2id = {m["name"]: m["id"] for m in members}
        out = {"summary": "", "steps": []}
        try:
            raw = call_deepseek_sync(prompt, None, sysp, max_tokens=600)
            mt = re.search(r"\{.*\}", raw, re.DOTALL)
            d = json.loads(re.sub(r",\s*([}\]])", r"\1", mt.group())) if mt else {}
            out["summary"] = str(d.get("summary", "")).strip()
            for st in (d.get("steps") or []):
                mid = name2id.get(str(st.get("member", "")).strip())
                if mid:
                    out["steps"].append({"bot": mid, "task": str(st.get("task", "")).strip()})
        except Exception:
            out["steps"] = [{"bot": m["id"], "task": task} for m in members]
        return out

    def _on_team_plan(self, gen, plan):
        if gen != self._gen:
            return
        summary = plan.get("summary") or "好的，我来安排。"
        steps = plan.get("steps") or []
        team = self._team
        if self._typing_row is not None:
            self._typing_row.set_text(summary, final=True)
            self._typing_row = None
        self._team_msgs.append({"role": "assistant", "content": summary, "bot": team["id"]})
        self._team_plan, self._team_idx = steps, 0
        if self._autoscroll:
            self._scroll_to_bottom()
        if not steps:
            self._finish_team()
            return
        self._run_team_step()

    def _run_team_step(self):
        if self._team_idx >= len(self._team_plan):
            self._run_team_aggregate()
            return
        step = self._team_plan[self._team_idx]
        member = self._bot_by_id(step["bot"])
        if member is None:
            self._team_idx += 1
            self._run_team_step()
            return
        idx = self._team_idx
        self._typing_row = self._add_message("assistant", "•", final=False, bot=member)
        if not self._typing_timer.isActive():
            self._typing_timer.start(380)
        self._scroll_to_bottom()
        history = self._build_member_prompt(member, step["task"])
        self._gen += 1
        gen = self._gen

        use_tools = CAP_TOOLS in member.get("capabilities", [])

        def work():
            try:
                mcfg = member.get("config")
                if use_tools:                      # 成员是智能体：可执行命令/读写文件等
                    text = _run_agent_loop(history, cfg=mcfg).strip()
                else:
                    text = "".join(t for k, t in call_chat_stream(history, max_tokens=1500, cfg=mcfg)
                                   if k == "answer").strip()
            except Exception as e:
                text = f"（{member['name']} 没能完成：{e}）"
            if gen == self._gen:
                self._sig.team_step.emit(gen, idx, text or "（无产出）")
        threading.Thread(target=work, daemon=True).start()

    def _build_member_prompt(self, member, task):
        team = self._team
        sysp = (f"你是团队「{team['name']}」里的成员「{member['name']}」。"
                + (f"你的专长/人设：{member.get('system').strip()} " if member.get("system") else "")
                + "请专注完成编排器交给你的子任务，产出可直接交付给下游/编排器的内容，"
                "专业、具体、有条理，不要寒暄客套，不要复述任务。")
        if CAP_MEMORY in member.get("capabilities", []):
            blk = _memory_block([m["text"] for m in self.store.get("memory", [])])
            if blk:
                sysp += "\n\n" + blk
        if CAP_TOOLS in member.get("capabilities", []):
            sysp += "\n\n" + _TOOLS_RULE
        parts = [f"整体需求：{self._team_task}"]
        if self._team_deliv:
            up = "\n\n".join(f"【{nm} 的交付】\n{ct}" for nm, ct in self._team_deliv)
            parts.append("上游成员已完成：\n" + up)
        parts.append(f"你这一步要做的：{task}\n\n请给出你的交付内容：")
        return [{"role": "system", "content": sysp},
                {"role": "user", "content": "\n\n".join(parts)}]

    def _on_team_step(self, gen, idx, text):
        if gen != self._gen:
            return
        member = self._bot_by_id(self._team_plan[idx]["bot"])
        if self._typing_row is not None:
            self._typing_row.set_text(text, final=True)
            self._typing_row = None
        self._team_deliv.append((member["name"] if member else "成员", text))
        self._team_msgs.append({"role": "assistant", "content": text,
                                "bot": member["id"] if member else None})
        if self._autoscroll:
            self._scroll_to_bottom()
        self._team_idx += 1
        self._run_team_step()

    def _run_team_aggregate(self):
        team = self._team
        self._typing_row = self._add_message("assistant", "•", final=False, bot=team)
        if not self._typing_timer.isActive():
            self._typing_timer.start(380)
        self._scroll_to_bottom()
        deliv = "\n\n".join(f"【{nm}】\n{ct}" for nm, ct in self._team_deliv)
        sysp = (f"你是团队「{team['name']}」的编排器（队长）。把各成员的交付物汇总、整理、"
                "调整成给用户的最终成果：连贯、完整、直接可用，去掉重复与过程痕迹，"
                "可适当润色补全但忠于成员产出。")
        prompt = f"用户需求：{self._team_task}\n\n各成员交付：\n{deliv}\n\n请输出交付给用户的最终成果。"
        self._gen += 1
        gen = self._gen

        def work():
            try:
                text = call_deepseek_sync(prompt, None, sysp, max_tokens=4096).strip()
            except Exception as e:
                text = f"（汇总失败：{e}）"
            if gen == self._gen:
                self._sig.team_final.emit(gen, text or "（无内容）")
        threading.Thread(target=work, daemon=True).start()

    def _on_team_final(self, gen, text):
        if gen != self._gen:
            return
        team = self._team
        if self._typing_row is not None:
            self._typing_row.set_text(text, final=True)
            self._typing_row = None
        self._team_msgs.append({"role": "assistant", "content": text, "bot": team["id"]})
        self._finish_team()

    def _finish_team(self):
        """把本轮所有消息（编排+各交付+汇总）落库，结束。"""
        self._typing_timer.stop()
        self._typing_row = None
        cur = self._cur()
        if cur is not None:
            cur["messages"].extend(self._team_msgs)
            _save_store(self.store)
        self._team_active = False
        self._team_plan, self._team_deliv, self._team_msgs = [], [], []
        self._set_streaming(False)
        self._load_current()
        self._update_action_visibility()
        self._maybe_extract_memory()       # 团队对话也产生记忆候选

    def _cancel_team(self):
        """切换 bot/会话时丢弃进行中的团队任务（不落库）。"""
        self._typing_timer.stop()
        self._typing_row = None
        self._team_active = False
        self._team_plan, self._team_deliv, self._team_msgs = [], [], []

    def _animate_typing(self):
        self._typing_phase = (self._typing_phase + 1) % 3
        dots = ["•", "• •", "• • •"][self._typing_phase]
        if self._team_active and self._typing_row is not None:
            self._typing_row.set_text(dots, final=False)

    # ── 消息操作：复制 / 重新生成 / 编辑 ──────────────────────────────
    def _copy_markdown(self, row):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(row._raw or "")

    def _copy_plain(self, row):
        from PyQt6.QtWidgets import QApplication
        if row.role == "assistant" and row.browser is not None:
            QApplication.clipboard().setText(row.browser.toPlainText())
        else:
            QApplication.clipboard().setText(row._raw or "")

    def _regenerate(self, row):
        if self._streaming:
            return
        cur = self._cur()
        if cur is None:
            return
        try:
            i = self._msgs.index(row)
        except ValueError:
            return
        if i >= len(cur["messages"]) or cur["messages"][i]["role"] != "assistant":
            return
        self._gen += 1
        self._set_streaming(False)
        cur["messages"] = cur["messages"][:i]   # 去掉该回答及其后续
        _save_store(self.store)
        self._load_current()
        self._run_completion()

    def _edit_user(self, row):
        if self._streaming:
            return
        cur = self._cur()
        if cur is None:
            return
        try:
            i = self._msgs.index(row)
        except ValueError:
            return
        if i >= len(cur["messages"]) or cur["messages"][i]["role"] != "user":
            return
        from PyQt6.QtWidgets import QInputDialog
        old = cur["messages"][i]["content"]
        new, ok = QInputDialog.getMultiLineText(
            self, "编辑消息", "修改后将丢弃此条之后的对话，并重新生成回答：", old)
        if not ok:
            return
        new = new.strip()
        if not new:
            return
        self._gen += 1
        self._set_streaming(False)
        cur["messages"] = cur["messages"][:i]            # 丢弃此条及其后续
        cur["messages"].append({"role": "user", "content": new})
        if i == 0:                                       # 首条则更新会话标题
            cur["title"] = (new[:18] + "…") if len(new) > 18 else new
        _save_store(self.store)
        self._refresh_session_list()
        self._load_current()
        self._run_completion()

    def _on_chunk(self, gen: int, kind: str, piece: str):
        if gen != self._gen or self._assistant_row is None:
            return
        if kind == "reasoning":
            self._assistant_reasoning += piece
            self._assistant_row.set_reasoning(self._assistant_reasoning, streaming=True)
        else:
            self._assistant_text += piece
            self._assistant_row.set_text(self._assistant_text + " ▍", final=False)
        if self._autoscroll:
            self._scroll_to_bottom()

    _MAX_AGENT_ITERS = 12

    def _on_done(self, gen: int):
        if gen != self._gen:
            return
        reasoning = (self._assistant_reasoning or "").strip()
        if self._assistant_row is not None:
            self._assistant_row.set_text(self._assistant_text, final=True)
            if reasoning:
                self._assistant_row.set_reasoning(reasoning, streaming=False)
                self._assistant_row.reason_btn.setChecked(False)   # 出完答案默认收起思考
        cur = self._cur()
        if cur is not None:
            msg = {"role": "assistant", "content": self._assistant_text}
            if reasoning:
                msg["reasoning"] = reasoning
            cur["messages"].append(msg)
            _save_store(self.store)
        self._update_action_visibility()
        if self._autoscroll:
            self._scroll_to_bottom()
        # 智能体：若本条回复里有工具调用，则执行→回喂→继续
        bot = self._cur_bot()
        tc = (_first_tool_call(self._assistant_text)
              if CAP_TOOLS in bot.get("capabilities", []) else None)
        if tc and self._agent_iter < self._MAX_AGENT_ITERS:
            self._agent_iter += 1
            if self._agent_auto:
                self._exec_tool(tc)            # 自动执行（保持 streaming 忙碌态）
            else:
                self._pending_tool = tc        # 逐条确认：弹出审批条
                self._set_streaming(False)
                self._show_tool_approval(tc)
            return
        if tc and self._agent_iter >= self._MAX_AGENT_ITERS:
            self._add_message("tool", "（已达工具调用上限，停止自动执行；请直接给出结论或继续指示）")
        self._set_streaming(False)
        self._maybe_extract_memory()       # 一轮真正结束后，提炼记忆候选

    # ── 全局记忆：用户说「记一下…」→ 直接入库 → 供有记忆能力的 bot 读取 ──────
    def _maybe_extract_memory(self):
        """仅当用户这轮【主动要求记忆】时，从其话里提炼要记的内容并直接入库。"""
        cur = self._cur()
        if cur is None:
            return
        msgs = [m for m in cur["messages"] if m.get("role") in ("user", "assistant")]
        last_user = next((m for m in reversed(msgs) if m["role"] == "user"), None)
        if last_user is None or not _wants_remember(last_user["content"]):
            return
        tail = msgs[-6:]
        convo = "\n".join(("用户：" if m["role"] == "user" else "助手：") + m["content"]
                          for m in tail)
        known = "；".join(m["text"] for m in self.store.get("memory", [])) or "（暂无）"
        prompt = f"已有记忆：{known}\n\n最近对话：\n{convo}\n\n请提炼用户要记住的内容（JSON 数组）。"

        def work():
            try:
                raw = call_deepseek_sync(prompt, None, _MEM_EXTRACT_SYS, max_tokens=300)
                mt = re.search(r"\[.*?\]", raw, re.DOTALL)
                cands = json.loads(mt.group()) if mt else []
                cands = [str(c).strip() for c in cands if str(c).strip()]
            except Exception:
                cands = []
            self._sig.mem_candidates.emit(cands)

        threading.Thread(target=work, daemon=True).start()

    def _on_mem_candidates(self, cands):
        """直接入库（不再询问），底部给一条「已记住」提示，可撤销。"""
        existing = {m["text"] for m in self.store.get("memory", [])}
        fresh = [c for c in cands if c not in existing][:6]
        if not fresh:
            return
        saved = []
        for t in fresh:
            m = {"id": uuid.uuid4().hex, "text": t, "created": time.time()}
            self.store.setdefault("memory", []).append(m)
            saved.append(m)
        _save_store(self.store)
        self._show_mem_saved(saved)

    def _show_mem_saved(self, items):
        """已入库提示条：列出刚记下的内容，每条可「撤销」。"""
        self._clear_mem_bar()
        bar = QFrame()
        bar.setObjectName("memBar")
        bar.setStyleSheet(
            "#memBar { background: #eef6f0; border: 1px solid #d3e7d9; border-radius: 12px; }")
        v = QVBoxLayout(bar)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(7)
        head = QLabel("已记住")
        head.setStyleSheet("color: #2c7a4b; font-size: 12px; font-weight: 700;"
                           " background: transparent; border: none;")
        v.addWidget(head)
        for m in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            lab = QLabel("· " + m["text"])
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; background: transparent;"
                              " border: none;")
            row.addWidget(lab, 1)
            undo = QPushButton("撤销")
            undo.setCursor(Qt.CursorShape.PointingHandCursor)
            undo.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme.TEXT3}; border: none;"
                f" font-size: 12px; }} QPushButton:hover {{ color: {theme.DANGER}; }}")
            undo.clicked.connect(lambda _, mm=m, r=row: self._unsave_mem(mm, r))
            row.addWidget(undo)
            v.addLayout(row)
        self._mem_bar = bar
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bar)
        # 卡片含自动换行 QLabel，高度要等布局算完才确定；多推一拍再滚到底，否则滚不到位
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _clear_mem_bar(self):
        bar = getattr(self, "_mem_bar", None)
        if bar is not None:
            bar.setParent(None)
            bar.deleteLater()
            self._mem_bar = None

    def _remove_mem_row(self, row):
        while row.count():
            it = row.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        if self._mem_bar is not None and self._mem_bar.layout().count() <= 1:
            self._clear_mem_bar()

    def _unsave_mem(self, m, row):
        """撤销刚记下的一条（从全局记忆里删除）。"""
        self.store["memory"] = [x for x in self.store.get("memory", [])
                                if x.get("id") != m.get("id")]
        _save_store(self.store)
        self._remove_mem_row(row)

    # ── 智能体：工具执行循环 ──────────────────────────────────────────
    def _show_tool_approval(self, tc):
        """逐条确认模式：在消息区底部弹出审批条（运行 / 跳过 / 本轮全自动）。"""
        self._clear_tool_approval()
        bar = QFrame()
        bar.setObjectName("toolApprove")
        bar.setStyleSheet(
            f"#toolApprove {{ background: {theme.INDIGO_SOFT}; border: 1px solid #d8d6fb;"
            f" border-radius: 12px; }}")
        v = QVBoxLayout(bar)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        head = QLabel(f"⚠ 智能体请求执行：{agent_tools.TOOL_LABELS.get(tc['tool'], tc['tool'])}")
        head.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; font-weight: 700;"
                           " background: transparent; border: none;")
        v.addWidget(head)
        body = tc.get("arg", "") + (("\n" + tc["content"]) if (tc["tool"] == "write" and tc.get("content")) else "")
        if body.strip():
            cmd = QLabel(body)
            cmd.setWordWrap(True)
            cmd.setStyleSheet("QLabel { background: transparent; color: #3a3550; border: none;"
                              " font-family: Consolas, monospace; font-size: 12px; }")
            v.addWidget(cmd)
        row = QHBoxLayout()
        row.setSpacing(8)
        run = QPushButton("运行")
        run.setObjectName("primary")
        run.setCursor(Qt.CursorShape.PointingHandCursor)
        run.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: #fff; border: none;"
            f" border-radius: 8px; padding: 6px 16px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}")
        run.clicked.connect(self._approve_tool)
        skip = QPushButton("跳过")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.clicked.connect(self._skip_tool)
        auto = QPushButton("本轮全部自动")
        auto.setCursor(Qt.CursorShape.PointingHandCursor)
        auto.clicked.connect(self._approve_tool_auto)
        row.addWidget(run)
        row.addWidget(skip)
        row.addStretch(1)
        row.addWidget(auto)
        v.addLayout(row)
        self._tool_bar = bar
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bar)
        self._scroll_to_bottom()

    def _clear_tool_approval(self):
        bar = getattr(self, "_tool_bar", None)
        if bar is not None:
            bar.setParent(None)
            bar.deleteLater()
            self._tool_bar = None

    def _approve_tool(self):
        tc = self._pending_tool
        self._pending_tool = None
        self._clear_tool_approval()
        if tc:
            self._exec_tool(tc)

    def _approve_tool_auto(self):
        self._agent_auto = True
        self._sync_agent_toggle()
        self._approve_tool()

    def _skip_tool(self):
        tc = self._pending_tool
        self._pending_tool = None
        self._clear_tool_approval()
        res = "（用户跳过了这个操作，请改用别的方式或直接给出结论）"
        self._add_message("tool", res)
        self._record_tool_and_continue(tc, res)

    def _exec_tool(self, tc):
        """后台执行工具，结果通过 tool_done 信号回到主线程。"""
        self._set_streaming(True)
        self._cur_tool = tc
        self._tool_row = self._add_message("tool", "执行中…")
        self._scroll_to_bottom()
        self._gen += 1
        gen = self._gen
        tool, arg, content = tc.get("tool"), tc.get("arg", ""), tc.get("content", "")

        def work():
            try:
                out = agent_tools.run_tool(tool, arg, content)
            except Exception as e:
                out = f"（执行异常：{e}）"
            if gen == self._gen:
                self._sig.tool_done.emit(gen, out)

        threading.Thread(target=work, daemon=True).start()

    def _on_tool_done(self, gen, result):
        if gen != self._gen:
            return
        row = getattr(self, "_tool_row", None)
        if row is not None:
            row.set_text(result)
        self._tool_row = None
        self._record_tool_and_continue(getattr(self, "_cur_tool", None), result)
        self._cur_tool = None

    def _record_tool_and_continue(self, tc, result):
        """把工具结果落库为 tool 消息，让 AI 据此继续。"""
        cur = self._cur()
        if cur is not None:
            cur["messages"].append({"role": "tool", "content": result,
                                    "tool": (tc or {}).get("tool", "shell"),
                                    "arg": (tc or {}).get("arg", "")})
            _save_store(self.store)
        if self._autoscroll:
            self._scroll_to_bottom()
        self._run_completion()                 # AI 据结果继续

    def _toggle_agent_auto(self):
        self._agent_auto = not self._agent_auto
        self._sync_agent_toggle()

    def _sync_agent_toggle(self):
        """按当前 bot 是否有 tools 能力显示/隐藏开关，并刷新文案样式。"""
        if not hasattr(self, "agent_toggle"):
            return
        bot = self._cur_bot()
        has = (not self._is_team(bot)) and (CAP_TOOLS in bot.get("capabilities", []))
        self.agent_toggle.setVisible(has)
        if self._agent_auto:
            self.agent_toggle.setText("⚡ 自动执行")
            self.agent_toggle.setStyleSheet(
                f"QPushButton {{ background: {theme.INDIGO_SOFT}; color: {theme.INDIGO};"
                f" border: 1px solid #d8d6fb; border-radius: 9px; padding: 3px 10px;"
                f" font-size: 12px; }} QPushButton:hover {{ background: #ece8fb; }}")
        else:
            self.agent_toggle.setText("✋ 逐条确认")
            self.agent_toggle.setStyleSheet(
                f"QPushButton {{ background: {theme.SUBTLE}; color: {theme.TEXT2};"
                f" border: none; border-radius: 9px; padding: 3px 10px; font-size: 12px; }}"
                f" QPushButton:hover {{ background: #ececef; }}")

    def _on_error(self, gen: int, msg: str):
        if gen != self._gen:
            return
        self._assistant_text += f"\n\n❌ {msg}"
        if self._assistant_row is not None:
            self._assistant_row.set_text(self._assistant_text)
        cur = self._cur()
        if cur is not None:
            cur["messages"].append({"role": "assistant", "content": self._assistant_text})
            _save_store(self.store)
        self._set_streaming(False)
        self._update_action_visibility()

    def _stop(self):
        """中止当前生成：保留已生成的部分并落库。"""
        if not self._streaming:
            return
        self._gen += 1                     # 让在跑的流/成员/工具被丢弃
        self._pending_tool = None          # 中止智能体工具循环
        self._cur_tool = None
        self._clear_tool_approval()
        if self._team_active:
            self._finish_team()            # 把已完成的编排/交付落库、清理打字行
            return
        cur = self._cur()
        if cur is not None and self._assistant_text.strip():
            cur["messages"].append({"role": "assistant", "content": self._assistant_text})
            _save_store(self.store)
        self._set_streaming(False)
        self._load_current()               # 重建：去掉光标/空助手行，固定最新回答按钮
        self._update_action_visibility()

    def _update_action_visibility(self):
        """仅最新一条 AI 回答固定显示操作按钮，其余 hover 才显示。"""
        last_assist = None
        for r in self._msgs:
            if r.role == "assistant":
                last_assist = r
        for r in self._msgs:
            r.set_actions_pinned(r is last_assist)

    def _maybe_title(self, session: dict, first_user_text: str):
        if session["title"] and session["title"] != "新对话":
            return
        t = first_user_text.strip().replace("\n", " ")
        session["title"] = (t[:18] + "…") if len(t) > 18 else t or "新对话"
        self._refresh_session_list()

    def _set_streaming(self, on: bool):
        self._streaming = on
        # 生成中按钮变「停止」（可点击中止）；否则恢复「发送」
        if on:
            self.send_btn.setIcon(icons.qicon("stop", color="#ffffff"))
            self.send_btn.setToolTip("停止生成")
        else:
            self.send_btn.setIcon(icons.qicon("send", color="#ffffff"))
            self.send_btn.setToolTip("发送")
            self._assistant_row = None

    def _on_scroll(self, value):
        """生成期间用户上滚则关闭自动滚；滚回底部则恢复。"""
        if not self._streaming:
            return
        bar = self.scroll.verticalScrollBar()
        self._autoscroll = value >= bar.maximum() - 4

    # ── 杂项 ──────────────────────────────────────────────────────────
    def _scroll_to_bottom(self):
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _scroll_row_to_top(self, row):
        """确保新发的消息完整可见：能滚到底就滚到底（沿用自动跟随）；
        消息太长、滚到底会截掉顶部时，则把它顶部对齐视口顶部。布局稳定后再算。"""
        def go():
            try:
                y = row.mapTo(self.msg_host, QPoint(0, 0)).y()
            except Exception:
                return
            bar = self.scroll.verticalScrollBar()
            if y >= bar.maximum():        # 滚到底时该消息顶部仍可见
                bar.setValue(bar.maximum())
            else:                         # 否则顶部对齐，保证完整可见
                bar.setValue(max(0, y - 12))
        QTimer.singleShot(0, lambda: QTimer.singleShot(0, go))

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        # getattr 兜底：构造早期(self.input 尚未建好)本过滤器可能被提前触发，防 AttributeError
        if obj is getattr(self, "input", None) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False
                self._send()
                return True
        # 双击标题栏：最大化 / 还原
        if obj is self.title_bar and event.type() == QEvent.Type.MouseButtonDblClick:
            self.toggle_max()
            return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self._content_width()
        for m in self._msgs:
            m.set_width(w)
        # 缩放手柄浮层定位到卡片右下角
        g = getattr(self, "size_grip", None)
        if g is not None and g.parent() is self.card:
            g.move(self.card.width() - g.width() - 4,
                   self.card.height() - g.height() - 4)
            g.raise_()

    # ── 外部入口 ──────────────────────────────────────────────────────
    def open(self):
        """供插件调用：无论之前在哪（最小化/被遮挡），都强制置顶到前台并聚焦。"""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        if not self.isVisible():
            self.show_window_centered()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self._force_foreground()
        self.input.setFocus()

    def _force_foreground(self):
        """Win32 AttachThreadInput 强制把本窗口提到最前（绕过 SetForegroundWindow 限制）。"""
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            fg = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg, None)
            cur_tid = kernel32.GetCurrentThreadId()
            attached = False
            if fg_tid and fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, True)
                attached = True
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        except Exception:
            pass

    def send_text(self, text: str, context: dict = None):
        """供 `--` 快捷命令调用：始终走默认 Hamster bot，自动发送。

        context={"q","a"} 时，新开一个会话并预置上一轮一次性问答作为上下文（携带历史）；
        否则复用空会话或新开一个空会话（不带历史）。
        """
        text = (text or "").strip()
        self.open()
        if not text:
            return
        self._gen += 1            # 取消可能在跑的上一条快捷流，避免回答落到新会话
        self._set_streaming(False)
        hb = self.bots[0]                       # 快捷对话固定 Hamster
        self.cur_bot_id = hb["id"]
        self.store["current_bot"] = hb["id"]
        if context and context.get("q") and context.get("a"):
            q = str(context["q"]).strip()
            s = _norm_session({
                "title": (q[:18] + "…") if len(q) > 18 else (q or "新对话"),
                "created": time.time(),
                "messages": [
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": str(context["a"]).strip()},
                ],
            })
            hb["sessions"].insert(0, s)
            self.cur_id = s["id"]
        else:
            empty = next((x for x in hb["sessions"] if not x["messages"]), None)
            if empty:
                self.cur_id = empty["id"]
            else:
                s = _norm_session({"title": "新对话", "created": time.time(), "messages": []})
                hb["sessions"].insert(0, s)
                self.cur_id = s["id"]
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()
        self.input.setPlainText(text)
        QTimer.singleShot(0, self._send)


_brand_cache = {}


def _brand_pixmap(px: int):
    if px in _brand_cache:
        return _brand_cache[px]
    pm = None
    try:
        logo = os.path.join(_base_dir(), "logo.png")
        if os.path.exists(logo):
            src = QPixmap(logo)
            if not src.isNull():
                s = int(px * _SS)
                pm = src.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(_SS)
    except Exception:
        pm = None
    if pm is None:
        pm = icons.qicon("ai").pixmap(QSize(px, px))
    _brand_cache[px] = pm
    return pm
