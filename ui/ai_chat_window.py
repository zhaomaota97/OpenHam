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
import math
import time
import uuid
import json
import random
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
)

from ui.window_base import OpenHamWindowBase
from ui import icons, theme
from core import app_config
from core.ai_client import call_chat_stream, _CHAT_SYS


# ── Bot 能力：交互控件（choices 快捷回复 / ask 澄清提问 / game 文字游戏）──
CAP_CHOICES = "choices"
CAP_ASK = "ask"
CAP_GAME = "game"
CAP_DICE = "dice"   # 旧值，载入时迁移为 game

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
_GAME_RULE = (
    "【文字游戏能力】当你主持文字游戏、需要随机/抽签/展示状态/庆祝时，可用这些道具"
    "（独立围栏代码块，块前后照常说话；随机类道具放在「揭晓结果之前」的位置）：\n"
    "· 掷骰子（先随机决定 1–6）：\n```openham:dice\n4\n```\n"
    "· 抛硬币（先随机决定 正/反）：\n```openham:coin\n正\n```\n"
    "· 抽牌（先随机决定一张，花色用 ♠♥♦♣，点数 A 2-10 J Q K）：\n```openham:card\n♠A\n```\n"
    "· 命运转盘（每行一个选项，最后一行 winner: 指定中奖项）：\n"
    "```openham:wheel\n吃火锅\n吃烧烤\n点外卖\nwinner: 吃烧烤\n```\n"
    "· 计分板（每行「名字: 分数」）：\n```openham:score\n小明: 12\n小红: 9\n```\n"
    "· 血条/数值条（每行「名字: 当前/上限」）：\n```openham:bar\n勇者: 70/100\n史莱姆: 20/40\n```\n"
    "· 撒花庆祝（赢了/达成时）：\n```openham:confetti\n```\n"
    "随机类（骰子/硬币/抽牌/转盘）的结果由你预先决定，并在块之后用文字揭晓点评。"
)

# 统一匹配所有道具围栏块（保留出现顺序），以及流式未闭合的尾块
_KINDS = "choices|ask|dice|coin|card|wheel|score|bar|confetti"
_BLOCK_RE = re.compile(
    r"```[ \t]*openham:(" + _KINDS + r")([^\n]*)\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE)
_BLOCK_TRAILING_RE = re.compile(
    r"```[ \t]*openham:(?:" + _KINDS + r")[^\n]*\r?\n.*$",
    re.DOTALL | re.IGNORECASE)
# 「已闭合的 随机动画类（骰子/硬币/抽牌/转盘）块」，用于流式中检测播放动画的时机
_ROLL_RE = re.compile(
    r"```[ \t]*openham:(dice|coin|card|wheel)[^\n]*\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE)
# confetti 块（无需暂存，揭晓后放）
_CONFETTI_RE = re.compile(
    r"```[ \t]*openham:confetti[^\n]*\r?\n.*?```", re.DOTALL | re.IGNORECASE)

_SUITS = "♠♥♦♣"
_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def _dice_result(body: str) -> int:
    m = re.search(r"\d+", body or "")
    n = int(m.group()) if m else 1
    return max(1, min(6, n))


def _coin_result(body: str) -> str:
    s = (body or "")
    return "反" if ("反" in s or "tail" in s.lower()) else "正"


def _parse_card(body: str):
    s = (body or "").strip()
    suit = "♠"
    found = next((c for c in _SUITS if c in s), None)
    if found:
        suit = found
    else:
        low = s.lower()
        for word, sym in (("黑桃", "♠"), ("红桃", "♥"), ("红心", "♥"), ("方块", "♦"),
                          ("方片", "♦"), ("梅花", "♣"), ("spade", "♠"), ("heart", "♥"),
                          ("diamond", "♦"), ("club", "♣")):
            if word in s or word in low:
                suit = sym
                break
    core = re.sub(r"[♠♥♦♣]|黑桃|红桃|红心|方块|方片|梅花", "", s)
    core = re.sub(r"(?i)spade|heart|diamond|club|of|花色|点数|:|：", "", core).strip()
    mr = re.search(r"10|[2-9]|[AJQKajqk]", core)
    rank = mr.group(0).upper() if mr else "A"
    return suit, rank


def _parse_wheel(body: str):
    opts, winner = [], ""
    for line in (body or "").splitlines():
        s = line.strip().lstrip("-*• ").strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("winner") or s.startswith("中奖") or s.startswith("结果"):
            sep = "：" if "：" in s else (":" if ":" in s else None)
            winner = s.split(sep, 1)[1].strip() if sep else ""
        else:
            opts.append(s)
    opts = opts[:8]
    if opts and winner not in opts:
        winner = opts[0]
    return opts, winner


def _parse_score(body: str):
    rows = []
    for line in (body or "").splitlines():
        s = line.strip().lstrip("-*• ").strip()
        if not s:
            continue
        sep = "：" if "：" in s else (":" if ":" in s else None)
        if sep:
            name, _, val = s.partition(sep)
            rows.append((name.strip(), val.strip()))
        else:
            rows.append((s, ""))
    return rows[:8]


def _parse_bar(body: str):
    rows = []
    for line in (body or "").splitlines():
        s = line.strip().lstrip("-*• ").strip()
        if not s:
            continue
        sep = "：" if "：" in s else (":" if ":" in s else None)
        if not sep:
            continue
        name, _, val = s.partition(sep)
        mm = re.search(r"(\d+)\s*/\s*(\d+)", val)
        if mm:
            cur, mx = int(mm.group(1)), int(mm.group(2))
        else:
            m2 = re.search(r"\d+", val)
            cur = int(m2.group()) if m2 else 0
            mx = max(cur, 100)
        rows.append((name.strip(), max(0, cur), max(1, mx)))
    return rows[:6]


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


def _parse_blocks(text: str):
    """提取消息里的 choices / ask 控件块，返回 (去块后的 Markdown, 控件列表)。"""
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
        elif kind == "dice":
            blocks.append({"type": "dice", "result": _dice_result(body)})
        elif kind == "coin":
            blocks.append({"type": "coin", "result": _coin_result(body)})
        elif kind == "card":
            suit, rank = _parse_card(body)
            blocks.append({"type": "card", "suit": suit, "rank": rank})
        elif kind == "wheel":
            opts, winner = _parse_wheel(body)
            if opts:
                blocks.append({"type": "wheel", "options": opts, "winner": winner})
        elif kind == "score":
            rows = _parse_score(body)
            if rows:
                blocks.append({"type": "score", "rows": rows})
        elif kind == "bar":
            rows = _parse_bar(body)
            if rows:
                blocks.append({"type": "bar", "rows": rows})
        elif kind == "confetti":
            blocks.append({"type": "confetti"})
        else:
            q, opts = _parse_ask_body(body)
            if opts:
                blocks.append({"type": "ask", "multi": ("multi" in mods),
                               "question": q, "options": opts})
    stripped = _BLOCK_RE.sub("", text or "")
    stripped = _BLOCK_TRAILING_RE.sub("", stripped)   # 流式未闭合时也先隐藏
    return stripped.strip(), blocks


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


def _make_bot(name: str, system: str, capabilities=None, sessions=None) -> dict:
    return {"id": uuid.uuid4().hex, "name": name or "助手",
            "system": system or "", "capabilities": list(capabilities or []),
            "created": time.time(),
            "sessions": [_norm_session(s) for s in (sessions or [])]}


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
        # 旧的「dice」能力迁移为「game」文字游戏包
        b["capabilities"] = ["game" if c == "dice" else c for c in b["capabilities"]]
        b.setdefault("created", time.time())
        b["sessions"] = [_norm_session(s) for s in b.get("sessions", [])]
    if not bots:
        bots = [_make_bot("Hamster", "")]
    elif bots[0]["name"] == "默认助手":   # 旧默认助手改名为 Hamster
        bots[0]["name"] = "Hamster"
    return {"bots": bots, "current_bot": data.get("current_bot")}


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


# 骰子点数在 3×3 网格里的位置（列,行）∈ {0,1,2}
_DIE_PIPS = {
    1: [(1, 1)],
    2: [(0, 0), (2, 2)],
    3: [(0, 0), (1, 1), (2, 2)],
    4: [(0, 0), (2, 0), (0, 2), (2, 2)],
    5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)],
    6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)],
}


def _draw_die(p: QPainter, x, y, s, value, pip="#1d1d1f", face="#ffffff"):
    """在 (x,y) 处画一个边长 s 的骰子（含点数 value 的点）。"""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(face))
    p.setPen(QPen(QColor(0, 0, 0, 38), max(1.0, s * 0.02)))
    p.drawRoundedRect(QRectF(x, y, s, s), s * 0.18, s * 0.18)
    p.setBrush(QColor(pip))
    p.setPen(Qt.PenStyle.NoPen)
    pr = s * 0.13
    cols = [x + s * 0.28, x + s * 0.5, x + s * 0.72]
    rows = [y + s * 0.28, y + s * 0.5, y + s * 0.72]
    for (c, r) in _DIE_PIPS.get(int(value), _DIE_PIPS[1]):
        p.drawEllipse(QPointF(cols[c], rows[r]), pr, pr)


def _die_pixmap(value: int, px: int = 38) -> QPixmap:
    s = int(px * _SS)
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    _draw_die(p, 1, 1, s - 2, value)
    p.end()
    pm.setDevicePixelRatio(_SS)
    return pm


def _draw_coin(p: QPainter, cx, cy, w, h, side):
    """画一枚金币（中心 cx,cy，宽 w 高 h）；w<h 时呈翻转中的椭圆。"""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(cx - w / 2, cy - h / 2, max(2.0, w), h)
    p.setBrush(QColor("#ecc34d"))
    p.setPen(QPen(QColor("#b8881f"), max(1.0, h * 0.045)))
    p.drawEllipse(rect)
    if w > h * 0.45:                       # 够宽才画字
        p.setPen(QColor("#6e4f10"))
        f = QFont()
        f.setPixelSize(int(h * 0.44))
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, side)


def _coin_pixmap(side: str, px: int = 34) -> QPixmap:
    s = int(px * _SS)
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    _draw_coin(p, s / 2, s / 2, s - 2, s - 2, side)
    p.end()
    pm.setDevicePixelRatio(_SS)
    return pm


def _draw_card(p: QPainter, cx, cy, w, h, suit, rank):
    """画一张扑克牌（中心 cx,cy）。"""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(cx - w / 2, cy - h / 2, w, h)
    p.setBrush(QColor("#ffffff"))
    p.setPen(QPen(QColor(0, 0, 0, 45), max(1.0, w * 0.02)))
    p.drawRoundedRect(rect, w * 0.10, w * 0.10)
    color = "#d23b3b" if suit in "♥♦" else "#1d1d1f"
    p.setPen(QColor(color))
    fr = QFont()
    fr.setPixelSize(int(h * 0.15))
    fr.setBold(True)
    p.setFont(fr)
    p.drawText(QRectF(rect.x() + w * 0.08, rect.y() + h * 0.04, w * 0.6, h * 0.3),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, str(rank))
    fs = QFont()
    fs.setPixelSize(int(h * 0.12))
    p.setFont(fs)
    p.drawText(QRectF(rect.x() + w * 0.08, rect.y() + h * 0.2, w * 0.6, h * 0.3),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, suit)
    fc = QFont()
    fc.setPixelSize(int(h * 0.4))
    fc.setBold(True)
    p.setFont(fc)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, suit)


def _card_pixmap(suit, rank, px: int = 30) -> QPixmap:
    w = int(px * _SS)
    h = int(px * 1.4 * _SS)
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    _draw_card(p, w / 2, h / 2, w - 2, h - 2, suit, rank)
    p.end()
    pm.setDevicePixelRatio(_SS)
    return pm


class _RollOverlay(QWidget):
    """界面中央的随机动画浮层（掷骰/抛硬币/抽牌）：滚动若干帧后落定到结果，再揭晓。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._mode = "dice"
        self._face = 1
        self._result = 1
        self._ticks = 0
        self._on_finish = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def roll(self, mode: str, result, on_finish=None):
        self._mode = mode if mode in ("coin", "card") else "dice"
        self._on_finish = on_finish
        self._ticks = 0
        if self._mode == "coin":
            self._result = "反" if str(result) == "反" else "正"
            self._face = random.choice(["正", "反"])
        elif self._mode == "card":
            self._result = result                  # (suit, rank)
            self._face = (random.choice(_SUITS), random.choice(_RANKS))
        else:
            self._result = max(1, min(6, int(result)))
            self._face = random.randint(1, 6)
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self._timer.start(70)

    def _tick(self):
        self._ticks += 1
        if self._ticks < 16:                       # 约 1.1s 滚动
            if self._mode == "coin":
                self._face = "反" if self._face == "正" else "正"
            elif self._mode == "card":
                self._face = (random.choice(_SUITS), random.choice(_RANKS))
            else:
                f = random.randint(1, 6)
                while f == self._face:
                    f = random.randint(1, 6)
                self._face = f
            self.update()
        else:
            self._timer.stop()
            self._face = self._result              # 落定到结果
            self.update()
            QTimer.singleShot(650, self._finish)

    def _finish(self):
        self.hide()
        cb, self._on_finish = self._on_finish, None
        if cb:
            cb()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(20, 22, 28, 90))   # 半透明遮罩
        s = 116.0
        cx, cy = self.width() / 2, self.height() / 2
        rolling = self._timer.isActive()
        if self._mode == "coin":
            if rolling:                            # 翻转中：横向挤压模拟立起来转
                t = self._ticks % 6
                scale = abs(t / 3.0 - 1.0)
                _draw_coin(p, cx, cy, s * max(0.14, scale), s, self._face)
            else:
                _draw_coin(p, cx, cy, s, s, self._face)
        elif self._mode == "card":
            _draw_card(p, cx, cy, 100, 140, self._face[0], self._face[1])
        else:
            _draw_die(p, cx - s / 2, cy - s / 2, s, self._face)
        p.end()


_WHEEL_PALETTE = ["#6e56cf", "#1f8f43", "#c79a2e", "#0a7ea4",
                  "#c0392b", "#7d3c98", "#2d6cdf", "#0f9b8e"]


class _WheelOverlay(QWidget):
    """命运转盘浮层：旋转减速后让指针落在中奖项上。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._options = []
        self._angle = 0.0
        self._final = 0.0
        self._total = 0.0
        self._t = 0
        self._dur = 46
        self._on_finish = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def spin(self, options, winner, on_finish=None):
        self._options = options[:8] or ["?"]
        try:
            widx = self._options.index(winner)
        except ValueError:
            widx = 0
        n = len(self._options)
        seg = 360.0 / n
        self._final = (90 - (widx + 0.5) * seg) % 360    # 中奖项中心转到正上方
        self._total = 5 * 360 + self._final
        self._t = 0
        self._angle = 0.0
        self._on_finish = on_finish
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self._timer.start(40)

    def _tick(self):
        self._t += 1
        prog = self._t / self._dur
        if prog >= 1:
            self._angle = self._final
            self._timer.stop()
            self.update()
            QTimer.singleShot(700, self._finish)
        else:
            ease = 1 - (1 - prog) ** 3               # ease-out 减速
            self._angle = ease * self._total
            self.update()

    def _finish(self):
        self.hide()
        cb, self._on_finish = self._on_finish, None
        if cb:
            cb()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(20, 22, 28, 90))
        cx, cy = self.width() / 2, self.height() / 2
        R = min(150.0, min(self.width(), self.height()) * 0.26)
        n = len(self._options)
        seg = 360.0 / n
        rect = QRectF(cx - R, cy - R, 2 * R, 2 * R)
        for i in range(n):
            p.setBrush(QColor(_WHEEL_PALETTE[i % len(_WHEEL_PALETTE)]))
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawPie(rect, int((self._angle + i * seg) * 16), int(seg * 16) + 1)
        p.setPen(QColor("#ffffff"))
        f = QFont()
        f.setPixelSize(int(max(11, R * 0.13)))
        f.setBold(True)
        p.setFont(f)
        for i, opt in enumerate(self._options):
            mid = math.radians(self._angle + (i + 0.5) * seg)
            lx = cx + math.cos(mid) * R * 0.6
            ly = cy - math.sin(mid) * R * 0.6
            p.drawText(QRectF(lx - R * 0.55, ly - 12, R * 1.1, 24),
                       Qt.AlignmentFlag.AlignCenter, str(opt)[:6])
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), R * 0.12, R * 0.12)
        p.setBrush(QColor("#1d1d1f"))                # 顶部指针（朝下）
        tip = QPolygonF([QPointF(cx, cy - R + 4),
                         QPointF(cx - 13, cy - R - 18),
                         QPointF(cx + 13, cy - R - 18)])
        p.drawPolygon(tip)
        p.end()


class _ConfettiOverlay(QWidget):
    """撒花庆祝：彩色碎片落下，约 1.7s 后自动消失（不挡点击、无遮罩）。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._parts = []
        self._t = 0
        self._on_finish = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def burst(self, on_finish=None):
        self.setGeometry(self.parent().rect())
        w = self.width() or 600
        h = self.height() or 400
        cols = ["#6e56cf", "#1f8f43", "#e0a02e", "#c0392b",
                "#2d6cdf", "#0f9b8e", "#d23b8c"]
        self._parts = []
        for _ in range(90):
            self._parts.append({
                "x": random.uniform(0, w), "y": random.uniform(-h * 0.4, 0),
                "vx": random.uniform(-1.6, 1.6), "vy": random.uniform(2.5, 7.0),
                "c": random.choice(cols), "s": random.uniform(5, 11),
                "a": random.uniform(0, 360), "va": random.uniform(-13, 13)})
        self._t = 0
        self._on_finish = on_finish
        self.show()
        self.raise_()
        self._timer.start(30)

    def _tick(self):
        self._t += 1
        for q in self._parts:
            q["x"] += q["vx"]
            q["y"] += q["vy"]
            q["vy"] += 0.18
            q["a"] += q["va"]
        self.update()
        if self._t > 56:
            self._timer.stop()
            self.hide()
            cb, self._on_finish = self._on_finish, None
            if cb:
                cb()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for q in self._parts:
            if q["y"] > self.height() + 20:
                continue
            p.save()
            p.translate(q["x"], q["y"])
            p.rotate(q["a"])
            p.setBrush(QColor(q["c"]))
            p.drawRect(QRectF(-q["s"] / 2, -q["s"] * 0.3, q["s"], q["s"] * 0.6))
            p.restore()
        p.end()


class _BotDialog(QDialog):
    """新建 / 编辑 bot：名称 + system prompt。"""

    def __init__(self, parent=None, name="", system="", capabilities=None):
        super().__init__(parent)
        self.setWindowTitle("新建 Bot" if not name else "编辑 Bot")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)

        lay.addWidget(self._lbl("名称"))
        self.name_in = QLineEdit(name)
        self.name_in.setPlaceholderText("例如：翻译官、代码助手、营养师…")
        lay.addWidget(self.name_in)

        lay.addSpacing(4)
        lay.addWidget(self._lbl("System Prompt（人设 / 指令，可留空用默认）"))
        self.sys_in = QPlainTextEdit(system)
        self.sys_in.setPlaceholderText(
            "例如：你是一名专业英汉翻译，只输出译文，不加解释。")
        self.sys_in.setFixedHeight(140)
        lay.addWidget(self.sys_in)

        lay.addSpacing(4)
        lay.addWidget(self._lbl("能力"))
        from PyQt6.QtWidgets import QCheckBox
        caps = capabilities or []
        self.cap_choices = QCheckBox("快捷回复按钮（AI 给出可点击的追问选项）")
        self.cap_ask = QCheckBox("澄清提问（AI 主动用单选/多选问清你的需求）")
        self.cap_game = QCheckBox("文字游戏（掷骰子 / 抛硬币 / 计分板，让 AI 当游戏主持人）")
        game_on = (CAP_GAME in caps) or (CAP_DICE in caps)
        for cb, on in ((self.cap_choices, CAP_CHOICES in caps),
                       (self.cap_ask, CAP_ASK in caps), (self.cap_game, game_on)):
            cb.setChecked(on)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.setStyleSheet(_checkbox_style())
            lay.addWidget(cb)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _lbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600;")
        return l

    def values(self):
        caps = []
        if self.cap_choices.isChecked():
            caps.append(CAP_CHOICES)
        if self.cap_ask.isChecked():
            caps.append(CAP_ASK)
        if self.cap_game.isChecked():
            caps.append(CAP_GAME)
        return (self.name_in.text().strip(),
                self.sys_in.toPlainText().strip(), caps)


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
                f" border-radius: 14px; padding: 10px 14px; font-size: 15px; }}")
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

            self.browser = QTextBrowser()
            self.browser.setOpenExternalLinks(True)
            self.browser.setFrameShape(QFrame.Shape.NoFrame)
            self.browser.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.browser.setStyleSheet(
                "QTextBrowser { background: transparent; border: none;"
                " color: #1d1d1f; font-size: 15px; }")
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
        menu = QMenu(self)
        a1 = menu.addAction("复制为 Markdown")
        a2 = menu.addAction("复制为纯文本")
        chosen = menu.exec(self.copy_btn.mapToGlobal(
            self.copy_btn.rect().bottomLeft()))
        if chosen == a1:
            self.host._copy_markdown(self)
        elif chosen == a2:
            self.host._copy_plain(self)

    def _set_buttons(self, vis: bool):
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

    def set_text(self, text: str, final: bool = False):
        self._raw = text
        if self.role == "user":
            self.bubble.setText(text)
        else:
            md, blocks = _parse_blocks(text)       # 去掉控件块再渲染 Markdown
            self.browser.setMarkdown(md)
            self._improve_typography()
            self._style_tables()
            self._fit_height()
            if final:                              # 仅在回答完成时渲染交互控件
                self._render_blocks(blocks)

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
            elif b["type"] == "dice":
                self.blocks_layout.addWidget(self._make_dice_widget(b["result"]))
            elif b["type"] == "coin":
                self.blocks_layout.addWidget(self._make_coin_widget(b["result"]))
            elif b["type"] == "card":
                self.blocks_layout.addWidget(self._make_card_widget(b["suit"], b["rank"]))
            elif b["type"] == "wheel":
                self.blocks_layout.addWidget(self._make_wheel_widget(b["winner"]))
            elif b["type"] == "score":
                self.blocks_layout.addWidget(self._make_score_widget(b["rows"]))
            elif b["type"] == "bar":
                self.blocks_layout.addWidget(self._make_bar_widget(b["rows"]))
            elif b["type"] == "confetti":
                continue                           # 撒花仅是浮层动画，无内联控件
            else:
                self.blocks_layout.addWidget(self._make_ask_widget(b))
        # 全是 confetti 时容器可能为空
        self.blocks_host.setVisible(self.blocks_layout.count() > 0)

    def _make_card_widget(self, suit, rank) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        card = QLabel()
        card.setPixmap(_card_pixmap(suit, rank, 30))
        card.setFixedSize(30, 42)
        h.addWidget(card)
        lbl = QLabel(f"抽到 {rank}{suit}")
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;"
                          " background: transparent;")
        h.addWidget(lbl)
        h.addStretch(1)
        return w

    def _make_wheel_widget(self, winner) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        pill = QLabel(f"转盘选中：{winner}")
        pill.setStyleSheet(
            f"QLabel {{ color: {theme.INDIGO}; background: {theme.INDIGO_SOFT};"
            f" border: 1px solid #d8d6fb; border-radius: 13px;"
            f" padding: 5px 14px; font-size: 14px; font-weight: 600; }}")
        h.addWidget(pill)
        h.addStretch(1)
        return w

    def _make_bar_widget(self, rows) -> QWidget:
        card = QFrame()
        card.setObjectName("barCard")
        card.setStyleSheet(
            f"#barCard {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 12px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(7)
        for name, cur, mx in rows:
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            n = QLabel(str(name))
            n.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;"
                            " background: transparent; border: none;")
            head.addWidget(n)
            head.addStretch(1)
            val = QLabel(f"{cur}/{mx}")
            val.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;"
                              " background: transparent; border: none;")
            head.addWidget(val)
            v.addLayout(head)
            from PyQt6.QtWidgets import QProgressBar
            pb = QProgressBar()
            pb.setRange(0, mx)
            pb.setValue(min(cur, mx))
            pb.setTextVisible(False)
            pb.setFixedHeight(10)
            ratio = cur / mx if mx else 0
            fill = "#1f8f43" if ratio > 0.5 else ("#c79a2e" if ratio > 0.25 else "#c0392b")
            pb.setStyleSheet(
                f"QProgressBar {{ background: {theme.BORDER_IN}; border: none;"
                f" border-radius: 5px; }}"
                f"QProgressBar::chunk {{ background: {fill}; border-radius: 5px; }}")
            v.addWidget(pb)
        return card

    def _make_coin_widget(self, side) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        coin = QLabel()
        coin.setPixmap(_coin_pixmap(str(side), 32))
        coin.setFixedSize(32, 32)
        h.addWidget(coin)
        lbl = QLabel(f"{side}面朝上")
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;"
                          " background: transparent;")
        h.addWidget(lbl)
        h.addStretch(1)
        return w

    def _make_score_widget(self, rows) -> QWidget:
        card = QFrame()
        card.setObjectName("scoreCard")
        card.setStyleSheet(
            f"#scoreCard {{ background: {theme.SUBTLE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 12px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(5)
        title = QLabel("计分板")
        title.setStyleSheet(f"color: {theme.TEXT3}; font-size: 12px; font-weight: 600;"
                            " background: transparent; border: none;")
        v.addWidget(title)
        for name, val in rows:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            n = QLabel(str(name))
            n.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; background: transparent;"
                            " border: none;")
            row.addWidget(n)
            row.addStretch(1)
            s = QLabel(str(val))
            s.setStyleSheet(f"color: {theme.INDIGO}; font-size: 15px; font-weight: 700;"
                            " background: transparent; border: none;")
            row.addWidget(s)
            v.addLayout(row)
        return card

    def _make_dice_widget(self, result) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        die = QLabel()
        die.setPixmap(_die_pixmap(int(result), 34))
        die.setFixedSize(34, 34)
        h.addWidget(die)
        lbl = QLabel(f"掷出 {int(result)} 点")
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;"
                          " background: transparent;")
        h.addWidget(lbl)
        h.addStretch(1)
        return w

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
        else:
            self.browser.setFixedWidth(max(160, content_px))
            self._fit_height()

    def _fit_height(self):
        if self.role != "user" and self.browser is not None:
            doc = self.browser.document()
            doc.setTextWidth(self.browser.viewport().width() or self.browser.width())
            self.browser.setFixedHeight(max(24, int(doc.size().height()) + 6))


class _ChatSignals(QObject):
    chunk = pyqtSignal(int, str)
    done = pyqtSignal(int)
    error = pyqtSignal(int, str)


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
        self._filter = ""

        self._sig = _ChatSignals()
        self._sig.chunk.connect(self._on_chunk)
        self._sig.done.connect(self._on_done)
        self._sig.error.connect(self._on_error)

        self._dice_rolled = False         # 本轮是否已触发随机动画
        self._dice_reveal = True          # 是否已揭晓（无随机动画时默认 True）
        self._dice_row = None             # 动画所在的消息行（不随 _assistant_row 置空而丢）
        self._confetti_played = False     # 本轮是否已撒花

        self._build_ui()
        self._roll_overlay = _RollOverlay(self._chat_area)
        self._wheel_overlay = _WheelOverlay(self._chat_area)
        self._confetti_overlay = _ConfettiOverlay(self._chat_area)
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
    def _add_sidebar_toggle(self):
        self.sidebar_btn = QPushButton()
        self.sidebar_btn.setIcon(icons.qicon("panel", color=theme.TEXT2))
        self.sidebar_btn.setFixedSize(28, 28)
        self.sidebar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar_btn.setToolTip("折叠 / 展开会话面板")
        self.sidebar_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 7px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        self.sidebar_btn.clicked.connect(self._toggle_sidebar)
        self.header_tools_layout.addWidget(self.sidebar_btn)

    def _toggle_sidebar(self):
        self._sidebar.setVisible(not self._sidebar.isVisible())
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
        add.setToolTip("新建 Bot")
        add.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px dashed {theme.BORDER_IN};"
            f" border-radius: 12px; }}"
            f"QPushButton:hover {{ background: {theme.HOVER}; }}")
        add.clicked.connect(self._create_bot)
        v.addWidget(add, 0, Qt.AlignmentFlag.AlignHCenter)
        return rail

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
        v.addWidget(self.bot_title)

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

    def _clear_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _bot_avatar(self, bot, px):
        """默认 bot（Hamster，bots[0]）用 logo 头像；其余用字母头像。"""
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
        name, system, caps = dlg.values()
        if not name:
            name = "新 Bot"
        bot = _make_bot(name, system, capabilities=caps)
        self.bots.append(bot)
        self.cur_bot_id = bot["id"]
        self.store["current_bot"] = bot["id"]
        self.cur_id = None
        _save_store(self.store)
        self._refresh_bots()
        self._refresh_session_list()
        self._load_current()

    def _bot_menu(self, bot_id: str, anchor: QWidget, pos):
        menu = QMenu(self)
        act_edit = menu.addAction(icons.qicon("edit"), "编辑 Bot")
        act_del = menu.addAction(icons.qicon("delete"), "删除 Bot")
        is_def = bool(self.bots) and bot_id == self.bots[0]["id"]
        if is_def or len(self.bots) <= 1:   # 默认 Hamster 不可删
            act_del.setEnabled(False)
        chosen = menu.exec(anchor.mapToGlobal(pos))
        if chosen == act_edit:
            self._edit_bot(bot_id)
        elif chosen == act_del:
            self._delete_bot(bot_id)

    def _edit_bot(self, bot_id: str):
        bot = next((b for b in self.bots if b["id"] == bot_id), None)
        if not bot:
            return
        dlg = _BotDialog(self, bot["name"], bot["system"],
                         bot.get("capabilities"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, system, caps = dlg.values()
        bot["name"] = name or bot["name"]
        bot["system"] = system
        bot["capabilities"] = caps
        _save_store(self.store)
        self._refresh_bots()
        if bot_id == self.cur_bot_id:
            self.bot_title.setText(bot["name"])
            self._load_current()   # 助手头像/名称随之刷新

    def _delete_bot(self, bot_id: str):
        if len(self.bots) <= 1 or bot_id == self.bots[0]["id"]:   # 默认 Hamster 不可删
            return
        self.bots = [b for b in self.bots if b["id"] != bot_id]
        self.store["bots"] = self.bots
        if self.cur_bot_id == bot_id:
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
        menu = QMenu(self)
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
        for w in self._rows:
            w.setParent(None)
            w.deleteLater()
        self._rows = []
        self._msgs = []

    def _add_message(self, role: str, text: str, final: bool = False) -> _MessageRow:
        bot = self._cur_bot()
        msg = _MessageRow(role, bot_name=bot["name"],
                          bot_avatar=self._bot_avatar(bot, 22), host=self)
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
            for m in cur["messages"]:
                self._add_message(m["role"], m["content"], final=True)
        self._update_action_visibility()
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
        hint = QLabel(f"我是「{bot['name']}」，有什么可以帮你的？")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {theme.TEXT2}; font-size: 16px;"
                           " font-weight: 600; background: transparent;")
        bl.addWidget(hint)
        sub = QLabel("在下方输入开始对话")
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
        self._autoscroll = True            # 新一轮生成：恢复自动滚到底
        self._dice_rolled = False          # 本轮随机动画状态复位
        self._dice_reveal = True
        self._dice_row = None
        self._confetti_played = False
        self._assistant_text = ""
        self._assistant_row = self._add_message("assistant", "▍")
        self._scroll_to_bottom()

        history = []
        bot = self._cur_bot()
        caps = bot.get("capabilities", [])
        sys_prompt = (bot.get("system") or "").strip()
        extras = []
        if CAP_ASK in caps:
            extras.append(_ASK_RULE)
        if CAP_GAME in caps or CAP_DICE in caps:
            extras.append(_GAME_RULE)
        if CAP_CHOICES in caps:
            extras.append(_CHOICES_RULE)
        if extras:                                       # 绑定能力则并入规则
            sys_prompt = (sys_prompt or _CHAT_SYS).strip() + "\n\n" + "\n\n".join(extras)
        if sys_prompt:
            history.append({"role": "system", "content": sys_prompt})
        history += [{"role": m["role"], "content": m["content"]}
                    for m in cur["messages"]]
        self._gen += 1
        gen = self._gen
        self._set_streaming(True)

        def work():
            try:
                for piece in call_chat_stream(history):
                    if gen != self._gen:
                        return
                    self._sig.chunk.emit(gen, piece)
                if gen == self._gen:
                    self._sig.done.emit(gen)
            except Exception as e:
                if gen == self._gen:
                    self._sig.error.emit(gen, str(e))

        threading.Thread(target=work, daemon=True).start()

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

    def _apply_stream_text(self, final: bool):
        """渲染当前助手文本；遇到掷骰则先播动画、暂不揭晓骰子之后的内容。"""
        if self._assistant_row is None:
            return
        text = self._assistant_text
        mt = _ROLL_RE.search(text)
        if mt and not self._dice_reveal:
            if not self._dice_rolled:                     # 首次遇到完整 随机动画块 → 触发动画
                self._dice_rolled = True
                self._dice_row = self._assistant_row      # 存住行引用，揭晓时用
                self._start_roll(mt.group(1).lower(), mt.group(2))
            visible = text[:mt.start()].rstrip()          # 只显示动画块之前的内容
            self._assistant_row.set_text(visible + ("" if final else " ▍"), final=False)
            return
        self._assistant_row.set_text(text + ("" if final else " ▍"), final=final)

    def _start_roll(self, kind, body):
        """按类型启动对应动画（骰子/硬币/抽牌 → 滚动浮层；转盘 → 转盘浮层）。"""
        if kind == "wheel":
            opts, winner = _parse_wheel(body)
            self._wheel_overlay.spin(opts, winner, on_finish=self._on_dice_revealed)
        elif kind == "card":
            self._roll_overlay.roll("card", _parse_card(body), on_finish=self._on_dice_revealed)
        elif kind == "coin":
            self._roll_overlay.roll("coin", _coin_result(body), on_finish=self._on_dice_revealed)
        else:
            self._roll_overlay.roll("dice", _dice_result(body), on_finish=self._on_dice_revealed)

    def _maybe_confetti(self):
        """消息完整揭晓后，若含 confetti 块则放一次撒花。"""
        if self._confetti_played:
            return
        if _CONFETTI_RE.search(self._assistant_text or ""):
            self._confetti_played = True
            self._confetti_overlay.burst()

    def _on_dice_revealed(self):
        """随机动画结束：揭晓结果及其之后的内容。

        注意：流式可能已结束(_on_done 把 _assistant_row 置空)，所以用单独存的 _dice_row。
        """
        self._dice_reveal = True
        row = self._dice_row or self._assistant_row
        if row is not None:
            # 流式已结束(行已落库) → final=True 渲染内联结果；否则仍带光标，待 _on_done 收尾
            row.set_text(self._assistant_text, final=not self._streaming)
        self._dice_row = None
        self._maybe_confetti()
        if self._autoscroll:
            self._scroll_to_bottom()

    def _on_chunk(self, gen: int, piece: str):
        if gen != self._gen or self._assistant_row is None:
            return
        self._assistant_text += piece
        # 出现完整 掷骰/抛硬币 块时进入「先动画后揭晓」模式
        if not self._dice_rolled and _ROLL_RE.search(self._assistant_text):
            self._dice_reveal = False
        self._apply_stream_text(False)
        if self._autoscroll and self._dice_reveal:
            self._scroll_to_bottom()

    def _on_done(self, gen: int):
        if gen != self._gen:
            return
        self._apply_stream_text(True)
        cur = self._cur()
        if cur is not None:
            cur["messages"].append({"role": "assistant", "content": self._assistant_text})
            _save_store(self.store)
        self._set_streaming(False)
        self._update_action_visibility()
        if self._dice_reveal:              # 未在等动画揭晓时，此刻消息已完整 → 可撒花
            self._maybe_confetti()
        if self._autoscroll and self._dice_reveal:
            self._scroll_to_bottom()

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
        """中止当前流式生成：保留已生成的部分并落库。"""
        if not self._streaming:
            return
        self._gen += 1                     # 让在跑的流被丢弃
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
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
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
        for name in ("_roll_overlay", "_wheel_overlay", "_confetti_overlay"):
            ov = getattr(self, name, None)
            if ov is not None and ov.isVisible():
                ov.setGeometry(self._chat_area.rect())

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
