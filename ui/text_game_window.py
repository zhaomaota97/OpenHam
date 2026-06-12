"""文字游戏插件窗口：AI 小镇（星露谷式治愈小镇）。

核心是「活村民」：几位性格鲜明的村民，能**实时自由对话**、并**持久记得你**——
聊过什么、你提过的事、送过的礼、关系到哪一步都会存档，越聊越懂你。
靠聊天/送礼升好感，熟了会跟你说更多心里话。

- 俯视小镇（代码生成，固定好看），方向键 / WASD 走动（复用画布与镜头跟随）。
- 走到村民旁按空格 → 打开聊天面板，可打字自由交谈（AI 实时扮演该角色，带记忆与好感）。
- 在镇上捡花果，聊天里送礼，村民按各自喜好与记忆反应。
- 睡觉进入下一天，刷新当日礼物。

（窗口类沿用名字 TextGameWindow，与联机沙箱网页游戏 GameWindow 无关。）
"""
import os
import json
import time
import random
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QPolygonF
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QStackedWidget, QScrollArea, QMenu,
)

from ui.window_base import OpenHamWindowBase
from ui import theme
from ui import game_props as gp
from core.ai_client import call_chat_stream, call_deepseek_sync


def _base_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _save_path():
    return os.path.join(_base_dir(), "text_game", "save.json")


# ── 村民人设（手写，保证鲜明；台词由 AI 实时生成）─────────────────────────
VILLAGERS = [
    {"id": "axing", "name": "阿杏", "role": "面包师", "color": "#e08a3a",
     "persona": "开朗热情、爱笑，说话甜，把烤面包当幸福",
     "likes": "鲜花、鸡蛋、甜的东西",
     "loves": ["花"], "good": ["蛋", "果"], "bad": ["鱼"],
     "backstory": "梦想开一家全镇最香的面包坊，清晨四点就起来揉面"},
    {"id": "laozhou", "name": "老周", "role": "渔夫", "color": "#3f7d8e",
     "persona": "话不多、外冷内热，嘴硬心软，常望着海发呆",
     "likes": "鱼、海货，不爱花里胡哨的东西",
     "loves": ["鱼"], "good": ["菌"], "bad": ["花", "甜"],
     "backstory": "年轻时在海上遇过险，从此敬畏大海，却离不开它"},
    {"id": "linyi", "name": "林医生", "role": "诊所医生", "color": "#4f9b6e",
     "persona": "温和、博学、细心，喜欢讲点小道理，关心人",
     "likes": "草药、蘑菇、书",
     "loves": ["菌"], "good": ["草药"], "bad": [],
     "backstory": "城里来的医生，想守护这个小镇每个人的健康"},
    {"id": "xiaoman", "name": "小满", "role": "花农", "color": "#d56a9a",
     "persona": "害羞、温柔、心思细腻，说话轻轻的，容易脸红",
     "likes": "各种花、草莓",
     "loves": ["花"], "good": ["果"], "bad": [],
     "backstory": "在镇边种满了花，偷偷喜欢把最好看的花留给来串门的人"},
    {"id": "daniu", "name": "大牛", "role": "铁匠", "color": "#9a7b5a",
     "persona": "豪爽、嗓门大、爱较劲，讲义气，憨直",
     "likes": "矿石、肉，最烦磨磨唧唧",
     "loves": ["矿"], "good": ["蛋"], "bad": ["花"],
     "backstory": "想打出全镇最好的工具，手上全是老茧也乐呵呵"},
]
_VMAP = {v["id"]: v for v in VILLAGERS}

# ── 礼物（撒在镇上捡，分类用于村民喜好判断）────────────────────────────
GIFTS = [
    {"name": "野花", "cat": "花"}, {"name": "草莓", "cat": "果"},
    {"name": "蘑菇", "cat": "菌"}, {"name": "小鱼", "cat": "鱼"},
    {"name": "鸡蛋", "cat": "蛋"}, {"name": "草药", "cat": "草药"},
    {"name": "铁矿石", "cat": "矿"},
]
_GIFT_SPOTS = [(9, 8), (19, 8), (8, 13), (25, 12), (17, 6), (11, 19), (24, 7)]

# ── 地块 ──────────────────────────────────────────────────────────────
_TILE = {
    "g": "#8ec06c",   # 草地
    "p": "#cdb98c",   # 土路
    "w": "#54a6d6",   # 水
    "t": "#8ec06c",   # 树（底草）
    "f": "#8ec06c",   # 花丛（底草）
    "F": "#caa46a",   # 田地
}
_SOLID_TILES = {"w", "t"}
_DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_TS = 46

BUILDINGS = [
    {"name": "你的家", "x": 4, "y": 3, "w": 4, "h": 3, "roof": "#c98a5a"},
    {"name": "面包坊", "x": 12, "y": 3, "w": 4, "h": 3, "roof": "#e0a93b"},
    {"name": "诊所", "x": 21, "y": 3, "w": 4, "h": 3, "roof": "#5aa0c0"},
    {"name": "铁匠铺", "x": 4, "y": 15, "w": 4, "h": 3, "roof": "#8a8f96"},
    {"name": "花圃小屋", "x": 12, "y": 15, "w": 4, "h": 3, "roof": "#d56a9a"},
    {"name": "渔屋", "x": 21, "y": 15, "w": 4, "h": 3, "roof": "#4f9b8e"},
]
# 村民站位（各自小屋门前）+ 床
_VSPOT = {"axing": (13, 6), "linyi": (22, 6), "daniu": (5, 18),
          "xiaoman": (13, 18), "laozhou": (22, 18)}
_BED = (5, 6)


def _build_town():
    W, H = 30, 22
    g = [["g" for _ in range(W)] for _ in range(H)]
    for x in range(W):
        g[0][x] = g[H - 1][x] = "t"
    for y in range(H):
        g[y][0] = g[y][W - 1] = "t"
    # 主路十字
    for x in range(1, W - 1):
        g[10][x] = "p"
    for y in range(1, H - 1):
        g[y][14] = "p"
    # 水塘（右中）
    for y in range(8, 13):
        for x in range(26, 29):
            g[y][x] = "w"
    # 田地（左下角一小片）
    for y in range(12, 14):
        for x in range(2, 6):
            g[y][x] = "F"
    # 树丛与花丛点缀
    for (x, y) in [(8, 6), (18, 5), (26, 5), (9, 16), (18, 19), (26, 18),
                   (3, 8), (10, 12), (20, 12)]:
        if g[y][x] == "g":
            g[y][x] = "t"
    for (x, y) in [(10, 8), (17, 8), (8, 19), (19, 16), (11, 6), (24, 16),
                   (16, 12), (7, 9), (22, 9)]:
        if g[y][x] == "g":
            g[y][x] = "f"
    # 建筑脚下清成草、保证村民可站
    cells = set()
    for b in BUILDINGS:
        for yy in range(b["y"], b["y"] + b["h"]):
            for xx in range(b["x"], b["x"] + b["w"]):
                if 0 <= yy < H and 0 <= xx < W:
                    cells.add((xx, yy))
                    g[yy][xx] = "g"
    for (x, y) in list(_VSPOT.values()) + [_BED, (15, 11)]:
        g[y][x] = "g"
    world = {"w": W, "h": H, "tiles": g, "buildings": BUILDINGS,
             "building_cells": cells, "spawn": {"x": 15, "y": 11}}
    return world


def _spawn_gifts():
    ents = []
    spots = list(_GIFT_SPOTS)
    random.shuffle(spots)
    picks = random.sample(GIFTS, k=min(5, len(GIFTS)))
    for (x, y), gift in zip(spots, picks):
        ents.append({"type": "item", "x": x, "y": y,
                     "name": gift["name"], "cat": gift["cat"]})
    return ents


# ── 好感 / 关系 ───────────────────────────────────────────────────────
def _hearts(aff):
    return max(0, min(10, aff // 10))


def _relation(aff):
    if aff < 10:
        return "刚认识、还很陌生"
    if aff < 30:
        return "脸熟了、算点头之交"
    if aff < 55:
        return "聊得来的朋友"
    if aff < 80:
        return "挺要好的朋友"
    return "无话不谈的知己"


def _hearts_html(aff):
    h = _hearts(aff)
    return ("<span style='color:#e8638c;'>" + "♥" * h + "</span>"
            + "<span style='color:#d8d8dc;'>" + "♡" * (10 - h) + "</span>")


# ── 信号 ──────────────────────────────────────────────────────────────
class _Signals(QObject):
    chunk = pyqtSignal(int, str)        # 流式台词
    done = pyqtSignal(int)
    gift_done = pyqtSignal(str, int, str)   # 反应台词, 好感增量, 记忆
    mem_done = pyqtSignal(str, int, str)    # villager_id, 好感增量, 记忆


# ── 聊天面板 ──────────────────────────────────────────────────────────
class _ChatPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setStyleSheet("background: transparent;")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)
        panel = QFrame()
        panel.setObjectName("chatP")
        panel.setStyleSheet(
            "#chatP { background: rgba(28,26,32,0.97); border: 1px solid rgba(255,255,255,0.14);"
            " border-radius: 16px; }")
        panel.setFixedWidth(560)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(20, 16, 20, 16)
        pv.setSpacing(10)
        # 头部
        head = QHBoxLayout()
        self.avatar = QLabel()
        self.avatar.setFixedSize(40, 40)
        head.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.name_lbl = QLabel("")
        self.name_lbl.setStyleSheet("color: #fff; font-size: 16px; font-weight: 700; background: transparent;")
        col.addWidget(self.name_lbl)
        self.hearts_lbl = QLabel("")
        self.hearts_lbl.setStyleSheet("font-size: 14px; background: transparent;")
        col.addWidget(self.hearts_lbl)
        head.addLayout(col)
        head.addStretch(1)
        pv.addLayout(head)
        # 对话区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(280)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self.box = QVBoxLayout(body)
        self.box.setContentsMargins(2, 2, 8, 2)
        self.box.setSpacing(8)
        self.box.addStretch(1)
        self.scroll.setWidget(body)
        pv.addWidget(self.scroll)
        # 输入区
        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("说点什么……")
        self.input.setFixedHeight(40)
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,0.10); color: #fff; border: none;"
            " border-radius: 10px; padding: 0 14px; font-size: 14px; }"
            " QLineEdit:focus { background: rgba(255,255,255,0.16); }")
        self.input.returnPressed.connect(self.win.chat_send)
        row.addWidget(self.input, 1)
        self.send_btn = self._btn("发送", "#3f8f5a")
        self.send_btn.clicked.connect(self.win.chat_send)
        row.addWidget(self.send_btn)
        self.gift_btn = self._btn("送礼", "#b06a3a")
        self.gift_btn.clicked.connect(self.win.chat_gift)
        row.addWidget(self.gift_btn)
        self.leave_btn = self._btn("离开", "rgba(255,255,255,0.14)")
        self.leave_btn.clicked.connect(self.win.chat_leave)
        row.addWidget(self.leave_btn)
        pv.addLayout(row)

        wrap = QHBoxLayout()
        wrap.addStretch(1); wrap.addWidget(panel); wrap.addStretch(1)
        root.addLayout(wrap)
        root.addStretch(1)
        self.hide()

    def _btn(self, text, color):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedHeight(40)
        b.setStyleSheet(
            f"QPushButton {{ background: {color}; color: #fff; border: none; border-radius: 10px;"
            f" padding: 0 16px; font-size: 14px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {color}; }}"
            f" QPushButton:disabled {{ color: rgba(255,255,255,0.4); }}")
        return b

    def reset(self, v, aff):
        from PyQt6.QtGui import QPixmap
        pm = QPixmap(40, 40)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(v["color"]))
        p.drawEllipse(2, 2, 36, 36)
        p.setBrush(QColor("#ffe7cf"))
        p.drawEllipse(11, 9, 18, 18)
        p.setBrush(QColor("#1d1d22"))
        p.drawEllipse(16, 16, 3, 4)
        p.drawEllipse(22, 16, 3, 4)
        p.end()
        self.avatar.setPixmap(pm)
        self.name_lbl.setText(f"{v['name']}  ·  {v['role']}")
        self.hearts_lbl.setText(_hearts_html(aff))
        while self.box.count() > 1:
            it = self.box.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def set_hearts(self, aff):
        self.hearts_lbl.setText(_hearts_html(aff))

    def _bubble(self, text, mine):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setMaximumWidth(380)
        if mine:
            lab.setStyleSheet(
                "QLabel { background: #3f8f5a; color: #fff; border-radius: 12px;"
                " padding: 8px 12px; font-size: 14px; }")
            h.addStretch(1)
            h.addWidget(lab)
        else:
            lab.setStyleSheet(
                "QLabel { background: rgba(255,255,255,0.12); color: #f2f2f4; border-radius: 12px;"
                " padding: 8px 12px; font-size: 14px; }")
            h.addWidget(lab)
            h.addStretch(1)
        self.box.insertWidget(self.box.count() - 1, w)
        QTimer.singleShot(0, self._to_bottom)
        return lab

    def add_mine(self, text):
        return self._bubble(text, True)

    def add_their(self, text):
        return self._bubble(text, False)

    def _to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_busy(self, busy):
        self.send_btn.setEnabled(not busy)
        self.gift_btn.setEnabled(not busy)
        self.input.setEnabled(not busy)
        if not busy:
            self.input.setFocus()


# ── 世界画布 ──────────────────────────────────────────────────────────
class _WorldCanvas(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background: #6fae5a;")
        self._held = []
        self._toast = ""
        self._toast_t = 0
        self.ptx = self.pty = 15
        self.facing = "down"
        self.moving = False
        self.prog = 0.0
        self.fromx = self.fromy = self.tox = self.toy = 0
        self._paused = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def load(self, start):
        self.ptx, self.pty = start["x"], start["y"]
        self.facing = "down"
        self.moving = False
        self._held = []
        self._timer.start(16)
        QTimer.singleShot(0, self.grab_kb)

    def grab_kb(self):
        try:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.grabKeyboard()
        except Exception:
            pass

    def release_kb(self):
        try:
            self.releaseKeyboard()
        except Exception:
            pass

    def mousePressEvent(self, e):
        if not self._paused:
            self.grab_kb()
        super().mousePressEvent(e)

    def set_paused(self, on):
        self._paused = on
        if on:
            self._held = []
            self.release_kb()
        else:
            self.grab_kb()

    def toast(self, text):
        self._toast = text
        self._toast_t = 150
        self.update()

    # ── 移动 ──
    def _tick(self):
        if self._toast_t > 0:
            self._toast_t -= 1
            if self._toast_t == 0:
                self._toast = ""
        if self._paused:
            self.update()
            return
        if self.moving:
            self.prog += 1 / 7.0
            if self.prog >= 1.0:
                self.prog = 0.0
                self.moving = False
                self.ptx, self.pty = self.tox, self.toy
                self._on_arrive()
        if not self.moving and self._held and not self._paused:
            self._try_step(self._held[-1])
        self.update()

    def _try_step(self, d):
        self.facing = d
        dx, dy = _DIRS[d]
        nx, ny = self.ptx + dx, self.pty + dy
        ent = self.win.entity_at(nx, ny)
        if ent and ent["type"] in ("villager", "bed"):
            return                 # 挡路，只转向（靠空格交互）
        if self._solid(nx, ny):
            return
        self.moving = True
        self.fromx, self.fromy = self.ptx, self.pty
        self.tox, self.toy = nx, ny

    def _on_arrive(self):
        ent = self.win.entity_at(self.ptx, self.pty)
        if ent and ent["type"] == "item":
            self.win.pickup(ent)

    def _solid(self, x, y):
        w = self.win.world
        if not (0 <= x < w["w"] and 0 <= y < w["h"]):
            return True
        if (x, y) in w["building_cells"]:
            return True
        return w["tiles"][y][x] in _SOLID_TILES

    def _player_px(self):
        if self.moving:
            x = (self.fromx + (self.tox - self.fromx) * self.prog) * _TS
            y = (self.fromy + (self.toy - self.fromy) * self.prog) * _TS
            return x, y
        return self.ptx * _TS, self.pty * _TS

    # ── 键盘 ──
    def keyPressEvent(self, e):
        if e.isAutoRepeat() or self._paused:
            return
        k = e.key()
        d = self._key_dir(k)
        if d:
            if d in self._held:
                self._held.remove(d)
            self._held.append(d)
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self._interact()

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        d = self._key_dir(e.key())
        if d and d in self._held:
            self._held.remove(d)

    def _key_dir(self, k):
        if k in (Qt.Key.Key_Up, Qt.Key.Key_W):
            return "up"
        if k in (Qt.Key.Key_Down, Qt.Key.Key_S):
            return "down"
        if k in (Qt.Key.Key_Left, Qt.Key.Key_A):
            return "left"
        if k in (Qt.Key.Key_Right, Qt.Key.Key_D):
            return "right"
        return None

    def _interact(self):
        ent = self._adjacent(("villager", "bed"))
        if not ent:
            return
        if ent["type"] == "villager":
            self.win.open_chat(ent)
        elif ent["type"] == "bed":
            self.win.sleep()

    def _adjacent(self, types):
        for d in (self.facing, "up", "down", "left", "right"):
            dx, dy = _DIRS[d]
            ent = self.win.entity_at(self.ptx + dx, self.pty + dy)
            if ent and ent["type"] in types:
                return ent
        return None

    # ── 绘制 ──
    def paintEvent(self, event):
        w = self.win.world
        if not w:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        vw, vh = self.width(), self.height()
        wpx, hpx = w["w"] * _TS, w["h"] * _TS
        ppx, ppy = self._player_px()
        camx = ppx + _TS / 2 - vw / 2
        camy = ppy + _TS / 2 - vh / 2
        camx = (wpx - vw) / 2 if wpx < vw else min(max(0, camx), wpx - vw)
        camy = (hpx - vh) / 2 if hpx < vh else min(max(0, camy), hpx - vh)
        x0, y0 = max(0, int(camx // _TS)), max(0, int(camy // _TS))
        x1 = min(w["w"], int((camx + vw) // _TS) + 1)
        y1 = min(w["h"], int((camy + vh) // _TS) + 1)
        for ty in range(y0, y1):
            for tx in range(x0, x1):
                self._draw_tile(p, tx * _TS - camx, ty * _TS - camy, w["tiles"][ty][tx])
        for b in w["buildings"]:
            self._draw_building(p, b, camx, camy)
        for ent in w["entities"]:
            ex, ey = ent["x"] * _TS - camx, ent["y"] * _TS - camy
            if -_TS <= ex <= vw and -_TS <= ey <= vh:
                self._draw_entity(p, ex, ey, ent)
        self._draw_player(p, ppx - camx, ppy - camy)
        self._draw_hud(p, vw)
        self._draw_hint(p, vw, vh)
        if self._toast:
            self._draw_toast(p, vw, vh)
        p.end()

    def _draw_tile(self, p, x, y, ch):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_TILE.get(ch, "#8ec06c")))
        p.drawRect(QRectF(x, y, _TS + 1, _TS + 1))
        cx, cy = x + _TS / 2, y + _TS / 2
        if ch == "t":
            p.setBrush(QColor("#6b4a2b"))
            p.drawRect(QRectF(cx - 3, cy + 2, 6, 12))
            p.setBrush(QColor("#3f7d3a"))
            p.drawEllipse(QPointF(cx, cy - 2), 15, 14)
            p.setBrush(QColor("#4f9b48"))
            p.drawEllipse(QPointF(cx - 4, cy - 5), 8, 8)
        elif ch == "w":
            p.setPen(QPen(QColor(255, 255, 255, 55), 2))
            p.drawArc(int(x + 8), int(cy - 4), 14, 10, 0, 180 * 16)
            p.setPen(Qt.PenStyle.NoPen)
        elif ch == "f":
            for (ox, oy, col) in ((-8, -6, "#e85d8a"), (9, -2, "#f0c93b"), (-2, 9, "#6fa8ff")):
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(cx + ox, cy + oy), 3, 3)
        elif ch == "F":
            p.setPen(QPen(QColor("#9c7a44"), 2))
            for i in range(1, 3):
                p.drawLine(QPointF(x, y + i * _TS / 3), QPointF(x + _TS, y + i * _TS / 3))
            p.setPen(Qt.PenStyle.NoPen)

    def _draw_building(self, p, b, camx, camy):
        x = b["x"] * _TS - camx
        y = b["y"] * _TS - camy
        w = b["w"] * _TS
        h = b["h"] * _TS
        # 墙
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#efe3cf"))
        p.drawRoundedRect(QRectF(x + 3, y + h * 0.42, w - 6, h * 0.58 - 3), 6, 6)
        # 屋顶
        p.setBrush(QColor(b["roof"]))
        roof = QPolygonF([QPointF(x, y + h * 0.5), QPointF(x + w / 2, y + 4),
                          QPointF(x + w, y + h * 0.5)])
        p.drawPolygon(roof)
        # 门
        p.setBrush(QColor("#7a5230"))
        dw, dh = w * 0.18, h * 0.32
        p.drawRoundedRect(QRectF(x + w / 2 - dw / 2, y + h - dh - 3, dw, dh), 4, 4)
        # 窗
        p.setBrush(QColor("#bfe2f0"))
        p.drawRoundedRect(QRectF(x + w * 0.2, y + h * 0.56, w * 0.16, h * 0.18), 3, 3)
        p.drawRoundedRect(QRectF(x + w * 0.64, y + h * 0.56, w * 0.16, h * 0.18), 3, 3)
        # 招牌
        f = QFont(); f.setPixelSize(12); f.setBold(True); p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(b["name"]) + 14
        r = QRectF(x + w / 2 - tw / 2, y - 8, tw, 18)
        p.setBrush(QColor(30, 26, 22, 200))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor("#fff"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, b["name"])
        p.setPen(Qt.PenStyle.NoPen)

    def _draw_entity(self, p, x, y, ent):
        cx, cy = x + _TS / 2, y + _TS / 2
        t = ent["type"]
        if t == "villager":
            v = _VMAP.get(ent["vid"], {"color": "#5b8def"})
            self._draw_person(p, cx, cy, v["color"])
            self._label(p, cx, y - 4, ent["name"], "#1d2a4a", "#cfe0ff")
        elif t == "item":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f0c93b"))
            p.drawPolygon(QPolygonF([QPointF(cx, cy - 10), QPointF(cx + 8, cy),
                                     QPointF(cx, cy + 10), QPointF(cx - 8, cy)]))
            p.setBrush(QColor("#fff2b0"))
            p.drawEllipse(QPointF(cx, cy), 3, 3)
        elif t == "bed":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#b5651d"))
            p.drawRoundedRect(QRectF(cx - 15, cy - 9, 30, 20), 4, 4)
            p.setBrush(QColor("#fafafa"))
            p.drawRoundedRect(QRectF(cx - 13, cy - 7, 12, 16), 3, 3)
            p.setBrush(QColor("#7fb0e0"))
            p.drawRoundedRect(QRectF(cx - 1, cy - 7, 14, 16), 3, 3)

    def _draw_person(self, p, cx, cy, body):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QPointF(cx, cy + 15), 13, 5)
        p.setBrush(QColor(body))
        p.drawRoundedRect(QRectF(cx - 11, cy - 14, 22, 28), 9, 9)
        p.setBrush(QColor("#ffe7cf"))
        p.drawEllipse(QPointF(cx, cy - 8), 9, 9)
        p.setBrush(QColor("#1d1d22"))
        p.drawEllipse(QPointF(cx - 3.4, cy - 9), 1.7, 2.1)
        p.drawEllipse(QPointF(cx + 3.4, cy - 9), 1.7, 2.1)

    def _draw_player(self, p, x, y):
        cx, cy = x + _TS / 2, y + _TS / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QPointF(cx, cy + 15), 13, 5)
        p.setBrush(QColor("#ef8e3a"))
        p.drawRoundedRect(QRectF(cx - 11, cy - 14, 22, 28), 9, 9)
        p.setBrush(QColor("#ffe0c2"))
        p.drawEllipse(QPointF(cx, cy - 8), 9, 9)
        ang = _DIRS[self.facing]
        perp = (-ang[1], ang[0])
        tx, ty = cx + ang[0] * 13, cy + 2 + ang[1] * 12
        p.setBrush(QColor("#a85515"))
        p.drawPolygon(QPolygonF([
            QPointF(tx + ang[0] * 5, ty + ang[1] * 5),
            QPointF(tx + perp[0] * 4, ty + perp[1] * 4),
            QPointF(tx - perp[0] * 4, ty - perp[1] * 4)]))
        p.setBrush(QColor("#1d1d22"))
        p.drawEllipse(QPointF(cx - 3.4, cy - 9), 1.8, 2.2)
        p.drawEllipse(QPointF(cx + 3.4, cy - 9), 1.8, 2.2)

    def _label(self, p, cx, top, text, bg, fg):
        f = QFont(); f.setPixelSize(11); f.setBold(True); p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(text) + 12
        r = QRectF(cx - tw / 2, top - 16, tw, 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg)); p.setOpacity(0.82)
        p.drawRoundedRect(r, 6, 6); p.setOpacity(1.0)
        p.setPen(QColor(fg))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_hud(self, p, vw):
        s = self.win.state
        txt = f"第 {s.get('day',1)} 天    {s.get('name','你')}    背包 {len(s.get('bag',[]))}"
        f = QFont(); f.setPixelSize(13); f.setBold(True); p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(txt) + 28
        r = QRectF(12, 12, tw, 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 28, 170))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)

    def _draw_hint(self, p, vw, vh):
        if self._paused:
            return
        ent = self._adjacent(("villager", "bed"))
        if not ent:
            return
        txt = (f"按 空格 和「{ent['name']}」聊天" if ent["type"] == "villager"
               else "按 空格 睡觉（进入下一天）")
        f = QFont(); f.setPixelSize(13); f.setBold(True); p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(txt) + 28
        r = QRectF((vw - tw) / 2, vh - 52, tw, 34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 28, 190))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)

    def _draw_toast(self, p, vw, vh):
        f = QFont(); f.setPixelSize(14); f.setBold(True); p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(self._toast) + 32
        r = QRectF((vw - tw) / 2, 84, tw, 36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3f8f5a")); p.setOpacity(min(1.0, self._toast_t / 30.0))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._toast)
        p.setOpacity(1.0)

    def resizeEvent(self, e):
        self.win.layout_overlays()


# ── 主窗口 ────────────────────────────────────────────────────────────
class TextGameWindow(OpenHamWindowBase):
    def __init__(self):
        super().__init__(title="文字游戏", min_w=860, min_h=580)
        self.resize(1060, 740)
        self.world = None
        self.state = None
        self._cur_v = None           # 当前对话村民 entity
        self._cur_vobj = None        # 人设
        self._convo = []             # [{role,content}]
        self._gen = 0
        self._busy = False
        self._reply_lbl = None
        self._reply_text = ""

        self._sig = _Signals()
        self._sig.chunk.connect(self._on_chunk)
        self._sig.done.connect(self._on_done)
        self._sig.gift_done.connect(self._on_gift_done)
        self._sig.mem_done.connect(self._on_mem_done)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_start())   # 0
        self._stack.addWidget(self._build_play())     # 1
        self.content_layout.addWidget(self._stack)
        self._stack.setCurrentIndex(0)

    # ── 开始页 ──
    def _build_start(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(page)
        outer.addStretch(1)
        box = QWidget(); box.setMaximumWidth(520)
        bv = QVBoxLayout(box)
        bv.setContentsMargins(40, 26, 40, 26)
        bv.setSpacing(12)
        title = QLabel("AI 小镇")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {theme.TEXT}; font-size: 30px; font-weight: 800; background: transparent;")
        bv.addWidget(title)
        self._start_sub = QLabel("住进一个温馨小镇，认识几位会聊天、记得你的村民")
        self._start_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._start_sub.setWordWrap(True)
        self._start_sub.setStyleSheet(f"color: {theme.TEXT2}; font-size: 14px; background: transparent;")
        bv.addWidget(self._start_sub)
        bv.addSpacing(6)
        self._name_in = QLineEdit()
        self._name_in.setPlaceholderText("你叫什么名字？")
        self._name_in.setFixedHeight(44)
        self._name_in.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 10px; padding: 0 14px;"
            f" font-size: 15px; }} QLineEdit:focus {{ border: 1px solid {theme.ACCENT}; }}")
        self._name_in.returnPressed.connect(self._enter_town)
        bv.addWidget(self._name_in)
        self._enter_btn = QPushButton("进入小镇")
        self._enter_btn.setFixedHeight(44)
        self._enter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enter_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: #fff; border: none;"
            f" border-radius: 10px; font-size: 15px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}")
        self._enter_btn.clicked.connect(self._enter_town)
        bv.addWidget(self._enter_btn)
        self._reset_btn = QPushButton("清空存档、重新开始")
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT3}; border: none;"
            f" font-size: 12px; }} QPushButton:hover {{ color: {theme.TEXT2}; }}")
        self._reset_btn.clicked.connect(self._reset_save)
        self._reset_btn.hide()
        bv.addWidget(self._reset_btn)
        wrap = QHBoxLayout(); wrap.addStretch(1); wrap.addWidget(box); wrap.addStretch(1)
        outer.addLayout(wrap)
        outer.addStretch(1)
        return page

    def _build_play(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = _WorldCanvas(self)
        lay.addWidget(self.canvas)
        self.chat = _ChatPanel(self)
        self.chat.setParent(self.canvas)
        self.confetti = gp.ConfettiOverlay(self.canvas)
        return page

    # ── 存档 ──
    def _load_save(self):
        try:
            with open(_save_path(), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write_save(self):
        try:
            os.makedirs(os.path.dirname(_save_path()), exist_ok=True)
            with open(_save_path(), "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"[text_game] 存档失败: {e}")

    def _new_state(self, name):
        return {"name": name or "我", "day": 1, "bag": [],
                "villagers": {v["id"]: {"aff": 0, "mem": [], "talked_day": 0}
                              for v in VILLAGERS}}

    def _refresh_start(self):
        sv = self._load_save()
        if sv:
            self._name_in.setText(sv.get("name", ""))
            self._start_sub.setText(
                f"欢迎回来，{sv.get('name','你')}（第 {sv.get('day',1)} 天）")
            self._enter_btn.setText("继续")
            self._reset_btn.show()
        else:
            self._enter_btn.setText("进入小镇")
            self._reset_btn.hide()

    def _reset_save(self):
        try:
            os.remove(_save_path())
        except Exception:
            pass
        self._name_in.clear()
        self._refresh_start()

    def _enter_town(self):
        sv = self._load_save()
        if sv:
            self.state = sv
            if self._name_in.text().strip():
                self.state["name"] = self._name_in.text().strip()
        else:
            self.state = self._new_state(self._name_in.text().strip())
        self.state.setdefault("bag", [])
        for v in VILLAGERS:                       # 兼容旧档
            self.state["villagers"].setdefault(v["id"], {"aff": 0, "mem": [], "talked_day": 0})
        self._build_world()
        self._write_save()
        self._stack.setCurrentIndex(1)
        self.canvas.load(self.world["spawn"])
        self.layout_overlays()
        QTimer.singleShot(30, self.canvas.grab_kb)
        self.canvas.toast("↑↓←→ / WASD 走动 · 空格 交互")

    def _build_world(self):
        self.world = _build_town()
        ents = []
        for v in VILLAGERS:
            x, y = _VSPOT[v["id"]]
            ents.append({"type": "villager", "vid": v["id"], "name": v["name"], "x": x, "y": y})
        ents.append({"type": "bed", "name": "床", "x": _BED[0], "y": _BED[1]})
        ents += _spawn_gifts()
        self.world["entities"] = ents

    # ── 画布回调 ──
    def entity_at(self, x, y):
        if not self.world:
            return None
        for e in self.world["entities"]:
            if e["x"] == x and e["y"] == y:
                return e
        return None

    def pickup(self, item):
        self.world["entities"].remove(item)
        self.state["bag"].append({"name": item["name"], "cat": item["cat"]})
        self.canvas.toast(f"捡到了 {item['name']}")
        self._write_save()

    def sleep(self):
        self.state["day"] = self.state.get("day", 1) + 1
        # 刷新当日礼物
        self.world["entities"] = [e for e in self.world["entities"] if e["type"] != "item"]
        self.world["entities"] += _spawn_gifts()
        self._write_save()
        self.canvas.toast(f"睡了一觉……第 {self.state['day']} 天")

    # ── 聊天 ──
    def open_chat(self, vent):
        v = _VMAP[vent["vid"]]
        vs = self.state["villagers"][v["id"]]
        self._cur_v = vent
        self._cur_vobj = v
        self._convo = []
        self.canvas.set_paused(True)
        self.chat.reset(v, vs["aff"])
        self.chat.show()
        self.chat.raise_()
        self.layout_overlays()
        # 开场问候（流式）——会自然提到记得你的事，凸显记忆
        self._stream(intro=True)

    def _villager_sys(self):
        v = self._cur_vobj
        vs = self.state["villagers"][v["id"]]
        notes = "；".join(vs["mem"][-8:]) if vs["mem"] else "（你对 ta 还不太了解）"
        return (
            f"你在扮演治愈小镇里的村民「{v['name']}」（{v['role']}）。"
            f"性格：{v['persona']}。喜欢：{v['likes']}。你的故事：{v['backstory']}。\n"
            f"你正在和镇上的居民「{self.state['name']}」聊天。你们的关系：{_relation(vs['aff'])}"
            f"（好感 {vs['aff']}/100）。\n"
            f"你记得关于 ta 的事：{notes}。\n"
            "请始终用第一人称、贴合这个性格说话：温暖、生活化、口语、简短（一般 1-3 句）。"
            "可以主动问候、提起你记得的事、分享日常或心情。关系越好越热络、越愿意说心里话。"
            "不要旁白，不要写括号里的动作，不要替对方说话，不要复述这些设定。")

    def _stream(self, intro=False, user_text=None):
        self._busy = True
        self.chat.set_busy(True)
        msgs = [{"role": "system", "content": self._villager_sys()}]
        msgs += self._convo
        if intro:
            msgs.append({"role": "user",
                         "content": f"（{self.state['name']} 走过来，和你打招呼。请你先开口。）"})
        elif user_text is not None:
            msgs.append({"role": "user", "content": user_text})
        self._gen += 1
        gen = self._gen
        self._reply_text = ""
        self._reply_lbl = self.chat.add_their("…")

        def work():
            try:
                for piece in call_chat_stream(msgs, max_tokens=400):
                    if gen != self._gen:
                        return
                    self._sig.chunk.emit(gen, piece)
                if gen == self._gen:
                    self._sig.done.emit(gen)
            except Exception as e:
                if gen == self._gen:
                    self._sig.chunk.emit(gen, f"（……）")
                    self._sig.done.emit(gen)
        threading.Thread(target=work, daemon=True).start()

    def _on_chunk(self, gen, piece):
        if gen != self._gen or self._reply_lbl is None:
            return
        self._reply_text += piece
        self._reply_lbl.setText(self._reply_text)

    def _on_done(self, gen):
        if gen != self._gen:
            return
        txt = self._reply_text.strip() or "……"
        self._reply_lbl.setText(txt)
        # 记录这轮（开场问候也算一条 assistant）
        if not self._convo or self._convo[-1].get("content") != txt:
            self._convo.append({"role": "assistant", "content": txt})
        self._busy = False
        self.chat.set_busy(False)

    def chat_send(self):
        if self._busy:
            return
        text = self.chat.input.text().strip()
        if not text:
            return
        self.chat.input.clear()
        self.chat.add_mine(text)
        self._convo.append({"role": "user", "content": text})
        self._stream(user_text=text)

    def chat_gift(self):
        if self._busy:
            return
        bag = self.state.get("bag", [])
        if not bag:
            self.chat.add_their("（你包里还没有可以送的东西，去镇上捡点花果吧～）")
            return
        menu = QMenu(self)
        for i, it in enumerate(bag):
            menu.addAction(it["name"]).setData(i)
        act = menu.exec(self.chat.gift_btn.mapToGlobal(self.chat.gift_btn.rect().topLeft()))
        if not act:
            return
        idx = act.data()
        item = bag.pop(idx)
        self._write_save()
        self.chat.add_mine(f"（送出 {item['name']}）")
        self._gift_react(item)

    def _gift_react(self, item):
        self._busy = True
        self.chat.set_busy(True)
        v = self._cur_vobj
        cat = item.get("cat", "")
        if cat in v.get("loves", []):
            tier, taste = 8, "非常喜欢"
        elif cat in v.get("good", []):
            tier, taste = 4, "挺喜欢"
        elif cat in v.get("bad", []):
            tier, taste = -3, "不太喜欢"
        else:
            tier, taste = 1, "觉得还行"
        gen = self._gen
        sysp = self._villager_sys()
        prompt = (f"{self.state['name']} 送了你一份「{item['name']}」。你对这种礼物{taste}。"
                  "请用 1-2 句、贴合性格地当面回应（第一人称、口语，不要括号动作）。")

        def work():
            try:
                line = call_deepseek_sync(prompt, None, sysp, max_tokens=160).strip()
            except Exception:
                line = "谢谢你～"
            note = f"{self.state['name']}送了我{item['name']}，我{taste}"
            self._sig.gift_done.emit(line or "谢谢你～", tier, note)
        threading.Thread(target=work, daemon=True).start()

    def _on_gift_done(self, line, delta, note):
        self.chat.add_their(line)
        self._convo.append({"role": "assistant", "content": line})
        self._apply_aff(delta, note)
        self._busy = False
        self.chat.set_busy(False)

    def _apply_aff(self, delta, note):
        v = self._cur_vobj
        vs = self.state["villagers"][v["id"]]
        before = _hearts(vs["aff"])
        vs["aff"] = max(0, min(100, vs["aff"] + delta))
        if note:
            vs["mem"].append(note)
            vs["mem"] = vs["mem"][-16:]
        self.chat.set_hearts(vs["aff"])
        self._write_save()
        if _hearts(vs["aff"]) > before:               # 升一颗心 → 撒花
            self.confetti.setGeometry(self.canvas.rect())
            self.confetti.burst()

    def chat_leave(self):
        if self._busy:
            # 仍允许离开，但不提炼这轮记忆
            pass
        self.chat.hide()
        self.canvas.set_paused(False)
        self.canvas.setFocus()
        v = self._cur_vobj
        if v is None or len([m for m in self._convo if m["role"] == "user"]) == 0:
            return
        # 提炼记忆 + 好感（后台）
        vs = self.state["villagers"][v["id"]]
        transcript = "\n".join(
            (f"{self.state['name']}：{m['content']}" if m["role"] == "user"
             else f"{v['name']}：{m['content']}") for m in self._convo)
        vid = v["id"]

        def work():
            note, delta, mood = "", 2, ""
            try:
                raw = call_deepseek_sync(
                    f"这是你（{v['name']}）和 {self.state['name']} 刚才的聊天：\n{transcript}\n\n"
                    "请以 JSON 回复，记下你从这次聊天里记住的、关于 ta 或你们关系的一句话，"
                    "并按聊得是否愉快投机给出好感变化："
                    '{"note":"一句话(第一人称，比如：ta说ta喜欢钓鱼)","delta":整数 -3到8,"mood":"心情2-4字"}'
                    "。只输出 JSON。",
                    None, "你是对话记忆提炼器，只输出 JSON。", max_tokens=200)
                import re
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    d = json.loads(re.sub(r",\s*}", "}", m.group()))
                    note = str(d.get("note", ""))[:60]
                    delta = int(d.get("delta", 2))
            except Exception:
                note = ""
            self._sig.mem_done.emit(vid, max(-3, min(8, delta)), note)
        threading.Thread(target=work, daemon=True).start()
        self._cur_v = None
        self._cur_vobj = None

    def _on_mem_done(self, vid, delta, note):
        vs = self.state["villagers"].get(vid)
        if vs is None:
            return
        v = _VMAP[vid]
        before = _hearts(vs["aff"])
        vs["aff"] = max(0, min(100, vs["aff"] + delta))
        if note:
            vs["mem"].append(note)
            vs["mem"] = vs["mem"][-16:]
        self._write_save()
        tip = f"{v['name']} 记住了这次聊天"
        if _hearts(vs["aff"]) != before:
            tip += f"（好感{'+' if delta>=0 else ''}{delta}）"
        self.canvas.toast(tip)

    # ── 布局 / 入口 ──
    def layout_overlays(self):
        if not hasattr(self, "canvas"):
            return
        r = self.canvas.rect()
        self.chat.setGeometry(r)
        self.confetti.setGeometry(r)

    def open(self):
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        if not self.isVisible():
            self.show_window_centered()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass
        if self._stack.currentIndex() == 0:
            self._refresh_start()
            self._name_in.setFocus()
        else:
            QTimer.singleShot(0, self.canvas.grab_kb)

    def hideEvent(self, e):
        if hasattr(self, "canvas"):
            self.canvas.release_kb()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        if self._stack.currentIndex() == 1 and hasattr(self, "canvas") and not self.chat.isVisible():
            self.canvas.keyPressEvent(e)
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if self._stack.currentIndex() == 1 and hasattr(self, "canvas") and not self.chat.isVisible():
            self.canvas.keyReleaseEvent(e)
        else:
            super().keyReleaseEvent(e)
