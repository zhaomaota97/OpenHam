"""文字游戏道具：骰子 / 硬币 / 扑克牌的绘制，命运转盘 / 撒花 的浮层动画。

供「文字游戏」插件窗口复用——把随机性事件渲染成界面中央的动画与内联控件。
所有绘制按物理像素超采样后再标 DPR，保证高分屏清晰。
"""
import re
import math
import random

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import QColor, QPixmap, QPainter, QFont, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

_SS = 3   # 超采样倍率

_SUITS = "♠♥♦♣"
_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

# 已闭合的随机动画块（骰子/硬币/抽牌/转盘）——窗口据此判断何时播放动画
ROLL_RE = re.compile(
    r"```[ \t]*openham:(dice|coin|card|wheel)[^\n]*\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE)
CONFETTI_RE = re.compile(
    r"```[ \t]*openham:confetti[^\n]*\r?\n.*?```", re.DOTALL | re.IGNORECASE)


# ── 解析 ──────────────────────────────────────────────────────────────
def dice_result(body: str) -> int:
    m = re.search(r"\d+", body or "")
    n = int(m.group()) if m else 1
    return max(1, min(6, n))


def coin_result(body: str) -> str:
    s = (body or "")
    return "反" if ("反" in s or "tail" in s.lower()) else "正"


def parse_card(body: str):
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


def parse_wheel(body: str):
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


# ── 绘制 ──────────────────────────────────────────────────────────────
_DIE_PIPS = {
    1: [(1, 1)],
    2: [(0, 0), (2, 2)],
    3: [(0, 0), (1, 1), (2, 2)],
    4: [(0, 0), (2, 0), (0, 2), (2, 2)],
    5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)],
    6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)],
}


def draw_die(p: QPainter, x, y, s, value, pip="#1d1d1f", face="#ffffff"):
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


def die_pixmap(value: int, px: int = 38) -> QPixmap:
    s = int(px * _SS)
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_die(p, 1, 1, s - 2, value)
    p.end()
    pm.setDevicePixelRatio(_SS)
    return pm


def draw_coin(p: QPainter, cx, cy, w, h, side):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(cx - w / 2, cy - h / 2, max(2.0, w), h)
    p.setBrush(QColor("#ecc34d"))
    p.setPen(QPen(QColor("#b8881f"), max(1.0, h * 0.045)))
    p.drawEllipse(rect)
    if w > h * 0.45:
        p.setPen(QColor("#6e4f10"))
        f = QFont()
        f.setPixelSize(int(h * 0.44))
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, side)


def coin_pixmap(side: str, px: int = 34) -> QPixmap:
    s = int(px * _SS)
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_coin(p, s / 2, s / 2, s - 2, s - 2, side)
    p.end()
    pm.setDevicePixelRatio(_SS)
    return pm


def draw_card(p: QPainter, cx, cy, w, h, suit, rank):
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


def card_pixmap(suit, rank, px: int = 30) -> QPixmap:
    w = int(px * _SS)
    h = int(px * 1.4 * _SS)
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_card(p, w / 2, h / 2, w - 2, h - 2, suit, rank)
    p.end()
    pm.setDevicePixelRatio(_SS)
    return pm


# ── 浮层动画 ──────────────────────────────────────────────────────────
class RollOverlay(QWidget):
    """界面中央随机动画浮层（掷骰/抛硬币/抽牌）：滚动若干帧后落定到结果，再揭晓。"""

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
        if self._ticks < 16:
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
            self._face = self._result
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
        p.fillRect(self.rect(), QColor(20, 22, 28, 90))
        s = 116.0
        cx, cy = self.width() / 2, self.height() / 2
        rolling = self._timer.isActive()
        if self._mode == "coin":
            if rolling:
                t = self._ticks % 6
                scale = abs(t / 3.0 - 1.0)
                draw_coin(p, cx, cy, s * max(0.14, scale), s, self._face)
            else:
                draw_coin(p, cx, cy, s, s, self._face)
        elif self._mode == "card":
            draw_card(p, cx, cy, 100, 140, self._face[0], self._face[1])
        else:
            draw_die(p, cx - s / 2, cy - s / 2, s, self._face)
        p.end()


_WHEEL_PALETTE = ["#6e56cf", "#1f8f43", "#c79a2e", "#0a7ea4",
                  "#c0392b", "#7d3c98", "#2d6cdf", "#0f9b8e"]


class WheelOverlay(QWidget):
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
        self._final = (90 - (widx + 0.5) * seg) % 360
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
            ease = 1 - (1 - prog) ** 3
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
        p.setBrush(QColor("#1d1d1f"))
        tip = QPolygonF([QPointF(cx, cy - R + 4),
                         QPointF(cx - 13, cy - R - 18),
                         QPointF(cx + 13, cy - R - 18)])
        p.drawPolygon(tip)
        p.end()


class ConfettiOverlay(QWidget):
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
