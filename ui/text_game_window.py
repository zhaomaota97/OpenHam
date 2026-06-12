"""文字游戏插件窗口：AI 文字冒险 / RPG 引擎。

固定界面 + 常驻 HUD（生命 / 金币 / 背包 / 回合），剧情由 AI 即时生成：
- 开局玩家输入想玩的题材，AI 生成开场场景、初始状态与第一组行动选项；
- 之后玩家**只能点选项推进**（不像聊天那样自由发言）；
- 掷骰 / 抽牌 / 命运转盘 / 撒花 作为随机性事件（见 ui/game_props.py）。

AI 每回合输出：剧情正文 + openham:state（权威全量状态）+ openham:choices（行动选项），
可选 dice/card/wheel 随机块与 confetti 庆祝，结束时用 openham:end(win/lose) 代替 choices。

（注意：本窗口是「文字冒险」插件用的 TextGameWindow，与联机沙箱网页游戏 GameWindow 无关。）
"""
import re
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer, QSize, QRectF
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QLineEdit, QTextBrowser, QStackedWidget, QSizePolicy,
)

from ui.window_base import OpenHamWindowBase
from ui import icons, theme
from ui import game_props as gp
from core.ai_client import call_chat_stream


# ── 协议解析 ──────────────────────────────────────────────────────────
_ALL_RE = re.compile(
    r"```[ \t]*openham:(?:state|choices|end|dice|coin|card|wheel|confetti)[^\n]*\r?\n.*?```",
    re.DOTALL | re.IGNORECASE)
_TRAILING_RE = re.compile(
    r"```[ \t]*openham:(?:state|choices|end|dice|coin|card|wheel|confetti)[^\n]*\r?\n.*$",
    re.DOTALL | re.IGNORECASE)
_STATE_RE = re.compile(
    r"```[ \t]*openham:state[^\n]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
_CHOICES_RE = re.compile(
    r"```[ \t]*openham:choices[^\n]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
_END_RE = re.compile(
    r"```[ \t]*openham:end[^\n]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _strip_blocks(text: str) -> str:
    """去掉所有 openham 协议块（含流式未闭合的尾块），只留剧情正文。"""
    s = _ALL_RE.sub("", text or "")
    s = _TRAILING_RE.sub("", s)
    return s.strip()


def _parse_state(text: str):
    """取最后一个 state 块，解析为 {hp:(cur,max), gold:int, items:[(name,n)], scene:str}。"""
    blocks = _STATE_RE.findall(text or "")
    if not blocks:
        return None
    body = blocks[-1]
    st = {"hp": None, "gold": None, "items": [], "scene": ""}
    for line in body.splitlines():
        s = line.strip()
        if not s or (":" not in s and "：" not in s):
            continue
        sep = "：" if ("：" in s and (":" not in s or s.index("：") < s.index(":"))) else ":"
        key, _, val = s.partition(sep)
        key = key.strip().lower()
        val = val.strip()
        if key in ("hp", "生命", "血量"):
            m = re.search(r"(\d+)\s*/\s*(\d+)", val)
            if m:
                st["hp"] = (int(m.group(1)), max(1, int(m.group(2))))
            else:
                m2 = re.search(r"\d+", val)
                if m2:
                    st["hp"] = (int(m2.group()), max(int(m2.group()), 100))
        elif key in ("gold", "金币", "金钱", "钱"):
            m = re.search(r"-?\d+", val)
            st["gold"] = int(m.group()) if m else 0
        elif key in ("items", "背包", "道具", "装备", "物品"):
            st["items"] = _parse_items(val)
        elif key in ("scene", "场景", "地点", "location", "位置"):
            st["scene"] = val
    return st


def _parse_items(val: str):
    out = []
    for chunk in re.split(r"[|，,、]", val or ""):
        s = chunk.strip().lstrip("-*• ").strip()
        if not s or s in ("无", "空", "（空）", "(空)", "none", "None"):
            continue
        m = re.search(r"(?:x|×|\*)\s*(\d+)\s*$", s)
        if m:
            name = s[:m.start()].strip()
            out.append((name or s, int(m.group(1))))
        else:
            out.append((s, 1))
    return out[:12]


def _parse_choices(text: str):
    blocks = _CHOICES_RE.findall(text or "")
    if not blocks:
        return []
    items = []
    for line in blocks[-1].splitlines():
        s = line.strip().lstrip("-*• ").strip()
        s = re.sub(r"^\d+[\.、\)]\s*", "", s)
        if s:
            items.append(s)
    return items[:4]


def _parse_end(text: str):
    blocks = _END_RE.findall(text or "")
    if not blocks:
        return ""
    s = blocks[-1].strip().lower()
    if "win" in s or "胜" in s or "通关" in s or "成功" in s:
        return "win"
    return "lose"


GM_RULE = (
    "你是一台「文字冒险」游戏引擎兼地下城主(GM)。玩家在固定界面里通过点击选项推进剧情，"
    "你负责生成剧情、维护游戏状态、并用道具制造随机性。请严格遵守输出格式。\n\n"
    "每个回合：先用 2–5 句、第二人称、生动的中文推进剧情，然后【必须】附上两个代码块——\n"
    "1) 游戏状态（权威全量，每回合都给，界面据此刷新）：\n"
    "```openham:state\nhp: 80/100\ngold: 35\nitems: 生锈的剑 x1 | 火把 x2 | 神秘钥匙\nscene: 幽暗洞穴\n```\n"
    "  · hp 写「当前/上限」；gold 整数；items 用「 | 」分隔、可带「 xN」数量，没有就写 items: ；scene 为当前场景名。\n"
    "2) 行动选项（2–4 个，玩家只能从中选择，简短的动词短语）：\n"
    "```openham:choices\n往洞穴深处走\n点燃火把查看石门\n使用神秘钥匙\n```\n\n"
    "需要随机 / 检定时，在揭晓结果【之前】插入对应道具块，结果由你预先决定，块之后再用剧情揭晓：\n"
    "· 掷骰子(1–6)：```openham:dice\n4\n```\n"
    "· 抽牌(花色 ♠♥♦♣，点数 A 2-10 J Q K)：```openham:card\n♥Q\n```\n"
    "· 命运转盘(每行一个选项，最后一行 winner: 指定结果)：```openham:wheel\n宝箱\n陷阱\n空房间\nwinner: 宝箱\n```\n"
    "胜利 / 重大成就时加一行庆祝：```openham:confetti\n```\n"
    "游戏结束(通关或死亡)时，用 end 块代替 choices，并在正文给出结局：\n"
    "```openham:end\nwin\n```（胜利写 win，失败写 lose）\n\n"
    "要点：状态要与上一回合连贯(扣血/给金币/增删道具都体现在 state)；选项要有意义、有后果；"
    "节奏明快，不要长篇大论；不要解释这些代码块本身；除剧情正文与代码块外不要输出多余内容。"
)

_THEMES = [
    "赛博朋克侦探", "武侠江湖恩仇", "魔法学院新生",
    "末日丧尸求生", "深海沉船逃生", "盗墓寻宝奇遇",
]


# ── HUD 控件 ──────────────────────────────────────────────────────────
class _HPBar(QWidget):
    """圆角生命条：按比例红/黄/绿。"""

    def __init__(self):
        super().__init__()
        self._cur, self._max = 0, 1
        self.setFixedHeight(9)

    def set_value(self, cur, mx):
        self._cur, self._max = cur, max(1, mx)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.rect()
        rad = r.height() / 2
        p.setBrush(QColor("#ececef"))
        p.drawRoundedRect(QRectF(r), rad, rad)
        ratio = min(1.0, max(0.0, self._cur / self._max))
        if ratio > 0.001:
            col = "#d23b3b" if ratio < 0.3 else ("#e0a02e" if ratio < 0.6 else "#1f8f43")
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(0, 0, max(rad * 2, r.width() * ratio), r.height()),
                              rad, rad)
        p.end()


class _HUD(QWidget):
    """左侧状态面板：场景 / 生命 / 金币 / 背包 / 回合。"""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(244)
        self.setObjectName("hudPanel")
        self.setStyleSheet(
            f"#hudPanel {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 12px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)

        self.scene_lbl = QLabel("准备开始…")
        self.scene_lbl.setWordWrap(True)
        self.scene_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: 700;"
            " background: transparent;")
        v.addWidget(self.scene_lbl)

        v.addWidget(self._hline())

        # 生命
        hp_head = QHBoxLayout()
        hp_head.setSpacing(6)
        hp_head.addWidget(self._icon("heart"))
        hp_head.addWidget(self._cap("生命"))
        hp_head.addStretch(1)
        self.hp_val = QLabel("—")
        self.hp_val.setStyleSheet(self._val_qss())
        hp_head.addWidget(self.hp_val)
        v.addLayout(hp_head)
        self.hp_bar = _HPBar()
        v.addWidget(self.hp_bar)

        # 金币
        gold_row = QHBoxLayout()
        gold_row.setSpacing(6)
        gold_row.addWidget(self._icon("coin"))
        gold_row.addWidget(self._cap("金币"))
        gold_row.addStretch(1)
        self.gold_val = QLabel("—")
        self.gold_val.setStyleSheet(self._val_qss())
        gold_row.addWidget(self.gold_val)
        v.addLayout(gold_row)

        v.addWidget(self._hline())

        bag_head = QHBoxLayout()
        bag_head.setSpacing(6)
        bag_head.addWidget(self._icon("bag"))
        bag_head.addWidget(self._cap("背包"))
        bag_head.addStretch(1)
        v.addLayout(bag_head)

        self.items_box = QVBoxLayout()
        self.items_box.setSpacing(4)
        self.items_box.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self.items_box)
        self._set_items([])

        v.addStretch(1)
        self.turn_lbl = QLabel("")
        self.turn_lbl.setStyleSheet(
            f"color: {theme.TEXT3}; font-size: 11px; background: transparent;")
        v.addWidget(self.turn_lbl)
        self._turn = 0

    def _hline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.BORDER}; border: none;")
        return line

    def _icon(self, name) -> QLabel:
        lab = QLabel()
        lab.setPixmap(icons.qicon(name).pixmap(QSize(14, 14)))
        lab.setFixedSize(14, 14)
        lab.setStyleSheet("background: transparent;")
        return lab

    def _cap(self, text) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px; background: transparent;")
        return lab

    def _val_qss(self) -> str:
        return (f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;"
                " background: transparent;")

    def reset(self):
        self.scene_lbl.setText("准备开始…")
        self.hp_val.setText("—")
        self.hp_bar.set_value(0, 1)
        self.gold_val.setText("—")
        self._set_items([])
        self._turn = 0
        self.turn_lbl.setText("")

    def bump_turn(self):
        self._turn += 1
        self.turn_lbl.setText(f"回合 {self._turn}")

    def update_state(self, st: dict):
        if st.get("scene"):
            self.scene_lbl.setText(st["scene"])
        if st.get("hp"):
            cur, mx = st["hp"]
            self.hp_val.setText(f"{cur}/{mx}")
            self.hp_bar.set_value(cur, mx)
        if st.get("gold") is not None:
            self.gold_val.setText(str(st["gold"]))
        self._set_items(st.get("items") or [])

    def _set_items(self, items):
        while self.items_box.count():
            w = self.items_box.takeAt(0).widget()
            if w:
                w.setParent(None)        # 立即脱离，避免删除前残影
                w.deleteLater()
        if not items:
            e = QLabel("（空）")
            e.setStyleSheet(f"color: {theme.TEXT3}; font-size: 12px; background: transparent;")
            self.items_box.addWidget(e)
            return
        for name, n in items:
            txt = f"· {name}" + (f"  ×{n}" if n > 1 else "")
            lab = QLabel(txt)
            lab.setWordWrap(True)
            lab.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 13px; background: transparent;")
            self.items_box.addWidget(lab)


# ── 剧情控件 ──────────────────────────────────────────────────────────
class _Narrative(QTextBrowser):
    """一段剧情正文（Markdown 自适应高度）。"""

    def __init__(self):
        super().__init__()
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QTextBrowser { background: transparent; border: none;"
            " color: #2a2a2e; font-size: 15px; }")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_md(self, md: str):
        self.setMarkdown(md or "")
        self.fit()

    def fit(self):
        doc = self.document()
        doc.setTextWidth(self.viewport().width() or self.width())
        self.setFixedHeight(max(20, int(doc.size().height()) + 6))


def _player_chip(text: str) -> QWidget:
    """玩家所选行动：右对齐小标签。"""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(0)
    lab = QLabel("» " + text)
    lab.setWordWrap(True)
    lab.setStyleSheet(
        f"QLabel {{ background: {theme.ACCENT}; color: #ffffff; border-radius: 13px;"
        " padding: 7px 13px; font-size: 14px; }}")
    h.addStretch(1)
    h.addWidget(lab)
    return w


class _GameSignals(QObject):
    chunk = pyqtSignal(int, str)
    done = pyqtSignal(int)
    error = pyqtSignal(int, str)


# ── 主窗口 ────────────────────────────────────────────────────────────
class TextGameWindow(OpenHamWindowBase):
    """文字游戏主窗口（单例，由插件 setup 创建并复用）。"""

    def __init__(self):
        super().__init__(title="文字游戏", min_w=860, min_h=560)
        self.resize(1040, 740)

        self._messages = []          # [{role, content}] 不含 system
        self._gen = 0
        self._streaming = False
        self._cur_text = ""
        self._cur_row = None
        self._roll_row = None
        self._rolled = False
        self._reveal = True
        self._confetti_played = False
        self._narratives = []

        self._sig = _GameSignals()
        self._sig.chunk.connect(self._on_chunk)
        self._sig.done.connect(self._on_done)
        self._sig.error.connect(self._on_error)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_start())
        self._stack.addWidget(self._build_play())
        self.content_layout.addWidget(self._stack)
        self._stack.setCurrentIndex(0)

    # ── 开始页 ────────────────────────────────────────────────────────
    def _build_start(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QWidget()
        box.setMaximumWidth(560)
        bv = QVBoxLayout(box)
        bv.setContentsMargins(40, 30, 40, 30)
        bv.setSpacing(14)

        title = QLabel("文字冒险")
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 30px; font-weight: 800; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bv.addWidget(title)
        sub = QLabel("写下你想玩的故事，AI 即时为你生成专属冒险")
        sub.setStyleSheet(f"color: {theme.TEXT2}; font-size: 14px; background: transparent;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bv.addWidget(sub)
        bv.addSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._theme_input = QLineEdit()
        self._theme_input.setPlaceholderText("例如：在赛博朋克都市当一名落魄侦探…")
        self._theme_input.setFixedHeight(42)
        self._theme_input.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 10px; padding: 0 14px;"
            f" font-size: 15px; }} QLineEdit:focus {{ border: 1px solid {theme.ACCENT}; }}")
        self._theme_input.returnPressed.connect(self._start_from_input)
        row.addWidget(self._theme_input, 1)
        go = QPushButton("开始冒险")
        go.setFixedHeight(42)
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: #fff; border: none;"
            f" border-radius: 10px; padding: 0 20px; font-size: 15px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}")
        go.clicked.connect(self._start_from_input)
        row.addWidget(go)
        bv.addLayout(row)

        bv.addSpacing(4)
        tip = QLabel("或选一个开头")
        tip.setStyleSheet(f"color: {theme.TEXT3}; font-size: 12px; background: transparent;")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bv.addWidget(tip)

        grid = QVBoxLayout()
        grid.setSpacing(8)
        for i in range(0, len(_THEMES), 3):
            r = QHBoxLayout()
            r.setSpacing(8)
            for t in _THEMES[i:i + 3]:
                chip = QPushButton(t)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setFixedHeight(34)
                chip.setStyleSheet(
                    f"QPushButton {{ background: {theme.ACCENT_SOFT}; color: {theme.TEXT};"
                    f" border: 1px solid {theme.BORDER}; border-radius: 17px; padding: 0 14px;"
                    f" font-size: 13px; }} QPushButton:hover {{ background: {theme.SELECT};"
                    f" border-color: {theme.BORDER_IN}; }}")
                chip.clicked.connect(lambda _, x=t: self._start_game(x))
                r.addWidget(chip)
            r.addStretch(1)
            grid.addLayout(r)
        bv.addLayout(grid)

        outer.addStretch(1)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(box)
        wrap.addStretch(1)
        outer.addLayout(wrap)
        outer.addStretch(1)
        return page

    # ── 对局页 ────────────────────────────────────────────────────────
    def _build_play(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        h = QHBoxLayout(page)
        h.setContentsMargins(14, 12, 14, 14)
        h.setSpacing(14)

        self._hud = _HUD()
        h.addWidget(self._hud)

        # 右侧：剧情滚动 + 行动区
        self._right = QWidget()
        self._right.setStyleSheet("background: transparent;")
        rv = QVBoxLayout(self._right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        story = QWidget()
        story.setStyleSheet("background: transparent;")
        self._story_box = QVBoxLayout(story)
        self._story_box.setContentsMargins(6, 4, 12, 4)
        self._story_box.setSpacing(14)
        self._story_box.addStretch(1)
        self._scroll.setWidget(story)
        rv.addWidget(self._scroll, 1)

        # 行动区面板
        self._action_panel = QWidget()
        self._action_panel.setObjectName("actionPanel")
        self._action_panel.setStyleSheet(
            f"#actionPanel {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 12px; }}")
        av = QVBoxLayout(self._action_panel)
        av.setContentsMargins(14, 12, 14, 12)
        av.setSpacing(8)
        self._action_title = QLabel("你要做什么？")
        self._action_title.setStyleSheet(
            f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600; background: transparent;")
        av.addWidget(self._action_title)
        self._action_box = QVBoxLayout()
        self._action_box.setSpacing(7)
        av.addLayout(self._action_box)
        rv.addWidget(self._action_panel)

        # 底部：重新开始
        foot = QHBoxLayout()
        foot.addStretch(1)
        restart = QPushButton("重新开始")
        restart.setCursor(Qt.CursorShape.PointingHandCursor)
        restart.setIcon(icons.qicon("replay", color=theme.TEXT2))
        restart.setIconSize(QSize(12, 12))
        restart.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT2}; border: none;"
            f" font-size: 12px; }} QPushButton:hover {{ color: {theme.TEXT}; }}")
        restart.clicked.connect(self._back_to_menu)
        foot.addWidget(restart)
        rv.addLayout(foot)

        h.addWidget(self._right, 1)

        # 中央动画浮层（覆盖右侧剧情区）
        self._roll_overlay = gp.RollOverlay(self._right)
        self._wheel_overlay = gp.WheelOverlay(self._right)
        self._confetti = gp.ConfettiOverlay(self._right)
        return page

    # ── 开局 ──────────────────────────────────────────────────────────
    def _start_from_input(self):
        self._start_game(self._theme_input.text().strip() or "一场随机的奇幻冒险")

    def _start_game(self, theme_text: str):
        if self._streaming:
            return
        theme_text = (theme_text or "").strip() or "一场随机的奇幻冒险"
        self._messages = [{"role": "user", "content": (
            f"开始一局以「{theme_text}」为主题的文字冒险。请生成开场场景，"
            f"给出合理的初始状态（生命/金币/初始装备），并给出第一组行动选项。")}]
        self._clear_story()
        self._hud.reset()
        self._stack.setCurrentIndex(1)
        self._add_player_chip("开始：" + theme_text)
        self._run_turn()

    def _back_to_menu(self):
        self._gen += 1                 # 作废进行中的生成
        self._streaming = False
        self._stack.setCurrentIndex(0)

    def open(self):
        if not self.isVisible():
            self.show_window_centered()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        self._force_foreground()

    def _force_foreground(self):
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    # ── 剧情 / 行动 渲染 ───────────────────────────────────────────────
    def _clear_story(self):
        self._narratives = []
        while self._story_box.count() > 1:    # 保留末尾 stretch
            it = self._story_box.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._clear_actions()

    def _add_narrative(self, md: str) -> _Narrative:
        n = _Narrative()
        self._story_box.insertWidget(self._story_box.count() - 1, n)
        self._narratives.append(n)
        n.set_md(md)
        return n

    def _add_player_chip(self, text: str):
        chip = _player_chip(text)
        self._story_box.insertWidget(self._story_box.count() - 1, chip)
        self._scroll_bottom()

    def _clear_actions(self):
        while self._action_box.count():
            it = self._action_box.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _action_button(self, text: str, primary=False) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(38)
        if primary:
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.ACCENT}; color: #fff; border: none;"
                f" border-radius: 9px; padding: 8px 14px; font-size: 14px; font-weight: 600;"
                f" text-align: center; }} QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}")
        else:
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.CARD}; color: {theme.TEXT};"
                f" border: 1px solid {theme.BORDER_IN}; border-radius: 9px; padding: 8px 14px;"
                f" font-size: 14px; text-align: left; }}"
                f" QPushButton:hover {{ background: {theme.SELECT}; border-color: {theme.ACCENT}; }}")
        return b

    def _show_choices(self, choices):
        self._clear_actions()
        self._action_title.setText("你要做什么？")
        self._action_panel.setVisible(True)
        if not choices:
            b = self._action_button("继续……")
            b.clicked.connect(lambda: self._send_action("继续"))
            self._action_box.addWidget(b)
            return
        for c in choices:
            b = self._action_button(c)
            b.clicked.connect(lambda _, x=c: self._send_action(x))
            self._action_box.addWidget(b)

    def _show_end(self, result: str):
        self._clear_actions()
        win = result == "win"
        self._action_title.setText("通关！" if win else "游戏结束")
        self._action_title.setStyleSheet(
            f"color: {theme.SUCCESS if win else '#d23b3b'}; font-size: 13px;"
            " font-weight: 700; background: transparent;")
        again = self._action_button("再来一局", primary=True)
        again.clicked.connect(self._back_to_menu)
        self._action_box.addWidget(again)

    def _busy_actions(self):
        self._clear_actions()
        self._action_title.setStyleSheet(
            f"color: {theme.TEXT2}; font-size: 12px; font-weight: 600; background: transparent;")
        self._action_title.setText("剧情生成中…")
        self._action_panel.setVisible(True)

    def _send_action(self, choice: str):
        if self._streaming:
            return
        self._messages.append({"role": "user", "content": "我选择：" + choice})
        self._add_player_chip(choice)
        self._run_turn()

    # ── 流式生成 ───────────────────────────────────────────────────────
    def _run_turn(self):
        self._cur_text = ""
        self._rolled = False
        self._reveal = True
        self._confetti_played = False
        self._roll_row = None
        self._cur_row = self._add_narrative("")
        self._hud.bump_turn()
        self._busy_actions()
        self._scroll_bottom()

        history = [{"role": "system", "content": GM_RULE}] + [
            {"role": m["role"], "content": m["content"]} for m in self._messages]
        self._gen += 1
        gen = self._gen
        self._streaming = True

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

    def _apply(self, final: bool):
        if self._cur_row is None:
            return
        text = self._cur_text
        mt = gp.ROLL_RE.search(text)
        if mt and not self._reveal:
            if not self._rolled:
                self._rolled = True
                self._roll_row = self._cur_row
                self._start_roll(mt.group(1).lower(), mt.group(2))
            self._cur_row.set_md(_strip_blocks(text[:mt.start()]))
            return
        self._cur_row.set_md(_strip_blocks(text))

    def _start_roll(self, kind, body):
        if kind == "wheel":
            opts, winner = gp.parse_wheel(body)
            self._wheel_overlay.spin(opts, winner, on_finish=self._on_revealed)
        elif kind == "card":
            self._roll_overlay.roll("card", gp.parse_card(body), on_finish=self._on_revealed)
        elif kind == "coin":
            self._roll_overlay.roll("coin", gp.coin_result(body), on_finish=self._on_revealed)
        else:
            self._roll_overlay.roll("dice", gp.dice_result(body), on_finish=self._on_revealed)

    def _on_revealed(self):
        self._reveal = True
        row = self._roll_row or self._cur_row
        if row is not None:
            row.set_md(_strip_blocks(self._cur_text))
        self._roll_row = None
        if not self._streaming:          # 流式已结束 → 此刻收尾
            self._finalize_turn()
        self._scroll_bottom()

    def _finalize_turn(self):
        text = self._cur_text
        st = _parse_state(text)
        if st:
            self._hud.update_state(st)
        end = _parse_end(text)
        if not self._confetti_played and gp.CONFETTI_RE.search(text):
            self._confetti_played = True
            self._confetti.burst()
        if end:
            self._show_end(end)
        else:
            self._show_choices(_parse_choices(text))
        self._scroll_bottom()

    def _on_chunk(self, gen: int, piece: str):
        if gen != self._gen or self._cur_row is None:
            return
        self._cur_text += piece
        if not self._rolled and gp.ROLL_RE.search(self._cur_text):
            self._reveal = False
        self._apply(False)
        if self._reveal:
            self._scroll_bottom()

    def _on_done(self, gen: int):
        if gen != self._gen:
            return
        self._apply(True)
        self._messages.append({"role": "assistant", "content": self._cur_text})
        self._streaming = False
        if self._reveal:                 # 没在等动画 → 立即收尾
            self._finalize_turn()

    def _on_error(self, gen: int, msg: str):
        if gen != self._gen:
            return
        self._streaming = False
        if self._cur_row is not None:
            self._cur_row.set_md(f"**生成失败**：{msg}\n\n请点「重新开始」再试。")
        self._clear_actions()
        b = self._action_button("重新开始", primary=True)
        b.clicked.connect(self._back_to_menu)
        self._action_box.addWidget(b)

    # ── 杂项 ──────────────────────────────────────────────────────────
    def _scroll_bottom(self):
        def go():
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(0, go)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for n in self._narratives:
            n.fit()
        if hasattr(self, "_right"):
            rect = self._right.rect()
            for ov in (self._roll_overlay, self._wheel_overlay, self._confetti):
                ov.setGeometry(rect)
