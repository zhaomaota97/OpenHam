"""文字游戏插件窗口：可操作的 2D 俯视 RPG，世界由 AI 实时生成。

- 俯视、滚动大世界（镜头跟随主角），网格步进移动（方向键 / WASD）。
- 每块区域由 AI 按主题生成：tiles（字符地图 + 图例）+ entities（NPC / 道具 / 敌人 / 出口）。
- 踩到道具自动拾取；踩到出口 → AI 生成下一区域；挨着 NPC 按空格 → AI 生成对话；
  撞上敌人 → 回合制战斗（本地规则 + 骰子动画，见 ui/game_props.py）。
- HUD：生命 / 金币 / 背包。画面为极简程序化绘制（彩色地块 + 简单精灵）。

（窗口类沿用名字 TextGameWindow，与联机沙箱网页游戏 GameWindow 无关。）
"""
import re
import json
import random
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer, QRectF, QPointF, QSize
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QPolygonF
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QStackedWidget,
)

from ui.window_base import OpenHamWindowBase
from ui import icons, theme
from ui import game_props as gp
from core.ai_client import call_deepseek_sync


# ── 地图图例 ──────────────────────────────────────────────────────────
# 字符 → (底色, 装饰类型)；SOLID 中的字符阻挡移动
_TILE = {
    ".": ("#8ec06c", None),     # 草地
    "=": ("#cdb98c", None),     # 道路
    ":": ("#d9c8a4", None),     # 室内地板
    ",": ("#e4d6a2", None),     # 沙地
    "F": ("#8ec06c", "flower"),  # 花丛
    "#": ("#9a8f86", "wall"),   # 石墙
    "~": ("#54a6d6", "water"),  # 水
    "T": ("#8ec06c", "tree"),   # 树
}
_SOLID = {"#", "~", "T"}
_DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

_WORLD_SYS = (
    "你是一个 2D 俯视 RPG 的世界生成器。根据给定主题，生成一块可探索的区域。"
    "只输出一个 JSON 对象，不要任何解释或代码块标记。结构如下：\n"
    '{"name":"区域名","intro":"一句话开场白",'
    '"w":28,"h":20,'
    '"tiles":["每行 w 个字符，共 h 行"],'
    '"entities":[{"type":"npc","x":5,"y":7,"name":"老猎人","brief":"守林人，知道森林的秘密"},'
    '{"type":"item","x":10,"y":3,"name":"治疗草药","effect":"heal","value":25},'
    '{"type":"item","x":4,"y":9,"name":"铁剑","effect":"weapon","value":4},'
    '{"type":"item","x":8,"y":8,"name":"金币袋","effect":"gold","value":15},'
    '{"type":"enemy","x":15,"y":12,"name":"森林狼","hp":24,"atk":6,"gold":12},'
    '{"type":"exit","x":27,"y":10,"name":"通往山洞","to":"幽深山洞"}],'
    '"start":{"x":3,"y":10}}\n'
    "图例（tiles 里每个字符）：. 草地  = 道路  : 室内地板  , 沙地  F 花丛  "
    "# 石墙(不可走)  ~ 水(不可走)  T 树(不可走)。\n"
    "要求：w 在 22–36、h 在 16–26；地图四周尽量用 # 或 T 围出边界；"
    "用墙/树/水分隔出有趣的地形（房间、小路、湖）；entities 4–9 个，坐标必须落在可走地块上、"
    "且不重叠、不在边界墙里；至少 1 个 exit、1–3 个 enemy、1–3 个 item、1–3 个 npc；"
    "start 必须在可走地块。名字用中文、简短。务必输出合法 JSON。"
)


def _extract_json(text: str):
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    chunk = s[i:j + 1]
    for attempt in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk)):
        try:
            return json.loads(attempt)
        except Exception:
            continue
    return None


def _parse_world(raw):
    """把 AI 返回解析成规范化的世界字典；失败返回 None。"""
    d = _extract_json(raw)
    if not isinstance(d, dict):
        return None
    tiles = d.get("tiles")
    if not isinstance(tiles, list) or not tiles:
        return None
    rows = [str(r) for r in tiles if isinstance(r, (str,))]
    if not rows:
        return None
    w = max(len(r) for r in rows)
    w = max(8, min(60, int(d.get("w", w) or w)))
    grid = []
    for r in rows[:40]:
        r = r[:w].ljust(w, ".")
        grid.append([c if c in _TILE else "." for c in r])
    h = len(grid)
    world = {
        "name": str(d.get("name", "未知之地"))[:18],
        "intro": str(d.get("intro", ""))[:80],
        "w": w, "h": h, "tiles": grid, "entities": [],
    }
    nid = 0
    for e in (d.get("entities") or []):
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        try:
            x, y = int(e.get("x", 0)), int(e.get("y", 0))
        except Exception:
            continue
        if not (0 <= x < w and 0 <= y < h):
            continue
        if grid[y][x] in _SOLID:                 # 卡在墙里 → 跳过
            continue
        if t not in ("npc", "item", "enemy", "exit"):
            continue
        ent = {"id": nid, "type": t, "x": x, "y": y,
               "name": str(e.get("name", "?"))[:12]}
        if t == "item":
            ent["effect"] = e.get("effect", "treasure")
            ent["value"] = int(e.get("value", 0) or 0)
        elif t == "enemy":
            hp = max(6, int(e.get("hp", 18) or 18))
            ent["hp"] = ent["max_hp"] = hp
            ent["atk"] = max(2, int(e.get("atk", 5) or 5))
            ent["gold"] = max(0, int(e.get("gold", hp // 2) or 0))
        elif t == "npc":
            ent["brief"] = str(e.get("brief", ""))[:60]
        elif t == "exit":
            ent["to"] = str(e.get("to", "未知之地"))[:18]
        nid += 1
        world["entities"].append(ent)
    st = d.get("start") or {}
    sx, sy = int(st.get("x", 1) or 1), int(st.get("y", 1) or 1)
    if not (0 <= sx < w and 0 <= sy < h) or grid[sy][sx] in _SOLID:
        sx, sy = _first_walkable(world)
    world["start"] = {"x": sx, "y": sy}
    return world


def _first_walkable(world):
    occ = {(e["x"], e["y"]) for e in world["entities"]}
    for y in range(world["h"]):
        for x in range(world["w"]):
            if world["tiles"][y][x] not in _SOLID and (x, y) not in occ:
                return x, y
    return 1, 1


def _fallback_world(theme):
    """AI 不可用 / 解析失败时的兜底世界，保证游戏永远能开。"""
    w, h = 22, 16
    grid = [["." for _ in range(w)] for _ in range(h)]
    for x in range(w):
        grid[0][x] = grid[h - 1][x] = "T"
    for y in range(h):
        grid[y][0] = grid[y][w - 1] = "T"
    for x in range(6, 14):
        grid[8][x] = "#"
    grid[8][10] = "="
    for (x, y) in ((4, 4), (15, 5), (9, 11), (16, 12)):
        grid[y][x] = "F"
    return {
        "name": (theme or "起始草原")[:18], "intro": "你在一片开阔的草原上醒来。",
        "w": w, "h": h, "tiles": grid,
        "entities": [
            {"id": 0, "type": "npc", "x": 5, "y": 4, "name": "旅行商人",
             "brief": "四处游历、见多识广的商人"},
            {"id": 1, "type": "item", "x": 16, "y": 5, "name": "治疗草药",
             "effect": "heal", "value": 25},
            {"id": 2, "type": "item", "x": 4, "y": 12, "name": "旧铁剑",
             "effect": "weapon", "value": 3},
            {"id": 3, "type": "enemy", "x": 15, "y": 12, "name": "野狼",
             "hp": 18, "max_hp": 18, "atk": 5, "gold": 10},
            {"id": 4, "type": "exit", "x": 20, "y": 8, "name": "向东的小径",
             "to": "幽暗森林"},
        ],
        "start": {"x": 3, "y": 8},
    }


# ── 信号 ──────────────────────────────────────────────────────────────
class _Signals(QObject):
    world_ready = pyqtSignal(int, object)     # gen, world dict
    dialog_ready = pyqtSignal(int, str)       # gen, text
    fail = pyqtSignal(int, str)


# ── 对话框 ────────────────────────────────────────────────────────────
class _DialogBox(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("dlgBox")
        self.setStyleSheet(
            "#dlgBox { background: rgba(24,26,32,0.94); border: 1px solid rgba(255,255,255,0.14);"
            " border-radius: 14px; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 12)
        v.setSpacing(6)
        self.speaker = QLabel("")
        self.speaker.setStyleSheet(
            "color: #ffd479; font-size: 14px; font-weight: 700; background: transparent;")
        v.addWidget(self.speaker)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setStyleSheet(
            "color: #f2f2f4; font-size: 15px; background: transparent;")
        v.addWidget(self.text)
        hint = QLabel("空格 / 点击 继续")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        hint.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px; background: transparent;")
        v.addWidget(hint)
        self.hide()

    def show_dialog(self, speaker, text):
        self.speaker.setText(speaker)
        self.text.setText(text)
        self.show()
        self.raise_()

    def mousePressEvent(self, e):
        self.hide()


# ── 战斗浮层 ──────────────────────────────────────────────────────────
class _CombatOverlay(QWidget):
    """回合制战斗：攻击（骰子定伤害）/ 防御 / 用道具 / 逃跑。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._player = None
        self._enemy = None
        self._done = None
        self._busy = False
        self._defending = False
        self._dice = gp.RollOverlay(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)
        panel = QFrame()
        panel.setObjectName("cbtPanel")
        panel.setStyleSheet(
            "#cbtPanel { background: rgba(20,22,28,0.97); border: 1px solid rgba(255,255,255,0.15);"
            " border-radius: 16px; }")
        panel.setFixedWidth(520)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(22, 18, 22, 18)
        pv.setSpacing(12)

        self.enemy_name = QLabel("")
        self.enemy_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.enemy_name.setStyleSheet(
            "color: #ff8a7a; font-size: 18px; font-weight: 800; background: transparent;")
        pv.addWidget(self.enemy_name)
        self.enemy_glyph = _EnemyGlyph()
        gh = QHBoxLayout()
        gh.addStretch(1)
        gh.addWidget(self.enemy_glyph)
        gh.addStretch(1)
        pv.addLayout(gh)
        self.enemy_hp = _Bar("#d23b3b")
        pv.addWidget(self.enemy_hp)

        self.log = QLabel("一场战斗开始了！")
        self.log.setWordWrap(True)
        self.log.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.log.setMinimumHeight(40)
        self.log.setStyleSheet(
            "color: #e8e8ea; font-size: 14px; background: transparent;")
        pv.addWidget(self.log)

        ph = QHBoxLayout()
        ph.setSpacing(8)
        you = QLabel("你")
        you.setStyleSheet("color: #cfe8ff; font-size: 13px; font-weight: 700; background: transparent;")
        ph.addWidget(you)
        self.player_hp = _Bar("#1f9d4d")
        ph.addWidget(self.player_hp, 1)
        pv.addLayout(ph)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._btns = {}
        for key, label in (("attack", "攻击"), ("defend", "防御"),
                           ("item", "用道具"), ("flee", "逃跑")):
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(40)
            b.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.10); color: #fff; border: none;"
                " border-radius: 9px; font-size: 14px; font-weight: 600; padding: 0 6px; }"
                " QPushButton:hover { background: rgba(255,255,255,0.20); }"
                " QPushButton:disabled { color: rgba(255,255,255,0.35); }")
            b.clicked.connect(lambda _, k=key: self._act(k))
            self._btns[key] = b
            btns.addWidget(b)
        pv.addLayout(btns)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(panel)
        wrap.addStretch(1)
        root.addLayout(wrap)
        root.addStretch(1)
        self.hide()

    def start(self, player, enemy, on_done):
        self._player = player
        self._enemy = enemy
        self._done = on_done
        self._busy = False
        self._defending = False
        self.enemy_name.setText(enemy["name"])
        self.enemy_glyph.set_seed(enemy.get("id", 0))
        self._refresh()
        self.log.setText(f"{enemy['name']} 挡住了去路！")
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self._set_enabled(True)

    def _refresh(self):
        e, p = self._enemy, self._player
        self.enemy_hp.set_value(e["hp"], e["max_hp"], f"{e['name']} {max(0,e['hp'])}/{e['max_hp']}")
        self.player_hp.set_value(p["hp"], p["max_hp"], f"你 {max(0,p['hp'])}/{p['max_hp']}")

    def _set_enabled(self, on):
        has_potion = any(it.get("effect") == "heal" for it in self._player["items"])
        for k, b in self._btns.items():
            b.setEnabled(on and (k != "item" or has_potion))

    def _act(self, kind):
        if self._busy:
            return
        if kind == "attack":
            self._busy = True
            self._set_enabled(False)
            val = random.randint(1, 6)
            self._dice.setGeometry(self.rect())
            self._dice.roll("dice", val, on_finish=lambda v=val: self._resolve_attack(v))
        elif kind == "defend":
            self._defending = True
            self.log.setText("你举盾戒备，下次受到的伤害减半。")
            self._enemy_turn()
        elif kind == "item":
            self._use_potion()
        elif kind == "flee":
            self._busy = True
            self._set_enabled(False)
            val = random.randint(1, 6)
            self._dice.setGeometry(self.rect())
            self._dice.roll("dice", val, on_finish=lambda v=val: self._resolve_flee(v))

    def _resolve_attack(self, dice):
        dmg = self._player["atk"] + dice
        self._enemy["hp"] -= dmg
        self.log.setText(f"你掷出 {dice}，挥击造成 {dmg} 点伤害！")
        self._refresh()
        if self._enemy["hp"] <= 0:
            self._win()
            return
        self._enemy_turn()

    def _use_potion(self):
        pot = next((it for it in self._player["items"] if it.get("effect") == "heal"), None)
        if not pot:
            return
        heal = pot.get("value", 20)
        self._player["hp"] = min(self._player["max_hp"], self._player["hp"] + heal)
        self._player["items"].remove(pot)
        self.log.setText(f"你使用了「{pot['name']}」，恢复 {heal} 点生命。")
        self._refresh()
        self._enemy_turn()

    def _resolve_flee(self, dice):
        if dice >= 4:
            self.log.setText(f"你掷出 {dice}，成功脱离了战斗。")
            QTimer.singleShot(700, lambda: self._finish("flee"))
        else:
            self.log.setText(f"你掷出 {dice}，没能逃掉！")
            self._enemy_turn()

    def _enemy_turn(self):
        def go():
            dmg = self._enemy["atk"] + random.randint(0, 3)
            if self._defending:
                dmg = max(1, dmg // 2)
                self._defending = False
            self._player["hp"] -= dmg
            self.log.setText(self.log.text() + f"\n{self._enemy['name']} 反击，对你造成 {dmg} 点伤害。")
            self._refresh()
            if self._player["hp"] <= 0:
                self._lose()
            else:
                self._busy = False
                self._set_enabled(True)
        QTimer.singleShot(650, go)

    def _win(self):
        reward = self._enemy.get("gold", 0)
        self._player["gold"] += reward
        self.log.setText(f"你击败了 {self._enemy['name']}！获得 {reward} 金币。")
        self._set_enabled(False)
        try:
            self._dice.setGeometry(self.rect())
        except Exception:
            pass
        QTimer.singleShot(900, lambda: self._finish("win"))

    def _lose(self):
        self.log.setText("你倒下了……")
        self._set_enabled(False)
        QTimer.singleShot(1000, lambda: self._finish("lose"))

    def _finish(self, result):
        self.hide()
        cb, self._done = self._done, None
        if cb:
            cb(result)


class _EnemyGlyph(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(96, 96)
        self._seed = 0

    def set_seed(self, s):
        self._seed = int(s)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = 48, 50
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#7a2230"))
        p.drawEllipse(QPointF(cx, cy), 34, 34)
        p.setBrush(QColor("#c0392b"))
        p.drawEllipse(QPointF(cx, cy), 30, 30)
        # 角
        p.setBrush(QColor("#3a1018"))
        p.drawPolygon(QPolygonF([QPointF(cx - 22, cy - 18), QPointF(cx - 30, cy - 40),
                                 QPointF(cx - 12, cy - 26)]))
        p.drawPolygon(QPolygonF([QPointF(cx + 22, cy - 18), QPointF(cx + 30, cy - 40),
                                 QPointF(cx + 12, cy - 26)]))
        # 眼
        p.setBrush(QColor("#ffe14d"))
        p.drawEllipse(QPointF(cx - 11, cy - 4), 5, 7)
        p.drawEllipse(QPointF(cx + 11, cy - 4), 5, 7)
        p.setBrush(QColor("#1a0c0c"))
        p.drawEllipse(QPointF(cx - 11, cy - 2), 2.4, 3)
        p.drawEllipse(QPointF(cx + 11, cy - 2), 2.4, 3)
        # 嘴（獠牙）
        p.setPen(QPen(QColor("#2a0d0d"), 2))
        p.drawArc(int(cx - 12), int(cy + 6), 24, 14, 0, -180 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#fff"))
        p.drawPolygon(QPolygonF([QPointF(cx - 6, cy + 12), QPointF(cx - 3, cy + 20), QPointF(cx, cy + 12)]))
        p.drawPolygon(QPolygonF([QPointF(cx + 6, cy + 12), QPointF(cx + 3, cy + 20), QPointF(cx, cy + 12)]))
        p.end()


class _Bar(QFrame):
    """带文字的数值条。"""

    def __init__(self, color):
        super().__init__()
        self._cur, self._max, self._txt, self._col = 0, 1, "", color
        self.setFixedHeight(22)

    def set_value(self, cur, mx, txt=""):
        self._cur, self._max, self._txt = cur, max(1, mx), txt
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.rect()
        rad = r.height() / 2
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawRoundedRect(QRectF(r), rad, rad)
        ratio = min(1.0, max(0.0, self._cur / self._max))
        if ratio > 0.001:
            p.setBrush(QColor(self._col))
            p.drawRoundedRect(QRectF(0, 0, max(rad * 2, r.width() * ratio), r.height()), rad, rad)
        if self._txt:
            p.setPen(QColor("#ffffff"))
            f = QFont()
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._txt)
        p.end()


# ── 世界画布 ──────────────────────────────────────────────────────────
_TS = 46   # 每格像素


class _WorldCanvas(QWidget):
    """俯视地图渲染 + 网格步进移动 + 镜头跟随 + HUD + 交互。"""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background: #6fae5a;")
        self._held = []                # 当前按住的方向（按时间顺序）
        self._toast = ""
        self._toast_t = 0
        self.ptx = self.pty = 1
        self.facing = "down"
        self.moving = False
        self.prog = 0.0
        self.fromx = self.fromy = self.tox = self.toy = 0
        self._paused = False           # 对话/战斗/生成时暂停移动
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def load(self, start):
        self.ptx, self.pty = start["x"], start["y"]
        self.facing = "down"
        self.moving = False
        self._held = []
        self._timer.start(16)
        self.setFocus()

    def set_paused(self, on):
        self._paused = on
        if on:
            self._held = []

    def toast(self, text):
        self._toast = text
        self._toast_t = 150           # 约 2.4s
        self.update()

    # ── 移动 ──────────────────────────────────────────────────────────
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
        if ent and ent["type"] == "enemy":
            self.win.start_combat(ent)
            return
        if ent and ent["type"] == "npc":
            return                     # NPC 挡路，只转向
        if self._solid(nx, ny):
            return
        self.moving = True
        self.fromx, self.fromy = self.ptx, self.pty
        self.tox, self.toy = nx, ny

    def _on_arrive(self):
        ent = self.win.entity_at(self.ptx, self.pty)
        if not ent:
            return
        if ent["type"] == "item":
            self.win.pickup(ent)
        elif ent["type"] == "exit":
            self.win.enter_exit(ent)

    def _solid(self, x, y):
        w = self.win.world
        if not (0 <= x < w["w"] and 0 <= y < w["h"]):
            return True
        return w["tiles"][y][x] in _SOLID

    def _player_px(self):
        if self.moving:
            x = (self.fromx + (self.tox - self.fromx) * self.prog) * _TS
            y = (self.fromy + (self.toy - self.fromy) * self.prog) * _TS
            return x, y
        return self.ptx * _TS, self.pty * _TS

    # ── 键盘 ──────────────────────────────────────────────────────────
    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        k = e.key()
        if self.win.dialog_open():
            if k in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Escape):
                self.win.close_dialog()
            return
        if self._paused:
            return
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
        npc = self._adjacent_npc()
        if npc:
            self.win.talk(npc)

    def _adjacent_npc(self):
        for d in (self.facing, "up", "down", "left", "right"):
            dx, dy = _DIRS[d]
            ent = self.win.entity_at(self.ptx + dx, self.pty + dy)
            if ent and ent["type"] == "npc":
                return ent
        return None

    # ── 绘制 ──────────────────────────────────────────────────────────
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

        x0 = max(0, int(camx // _TS))
        y0 = max(0, int(camy // _TS))
        x1 = min(w["w"], int((camx + vw) // _TS) + 1)
        y1 = min(w["h"], int((camy + vh) // _TS) + 1)
        for ty in range(y0, y1):
            for tx in range(x0, x1):
                self._draw_tile(p, tx * _TS - camx, ty * _TS - camy, w["tiles"][ty][tx])
        for ent in w["entities"]:
            ex = ent["x"] * _TS - camx
            ey = ent["y"] * _TS - camy
            if -_TS <= ex <= vw and -_TS <= ey <= vh:
                self._draw_entity(p, ex, ey, ent)
        self._draw_player(p, ppx - camx, ppy - camy)
        self._draw_hud(p, vw)
        self._draw_hint(p, vw, vh)
        if self._toast:
            self._draw_toast(p, vw, vh)
        p.end()

    def _draw_tile(self, p, x, y, ch):
        base, deco = _TILE.get(ch, _TILE["."])
        r = QRectF(x, y, _TS + 1, _TS + 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(base))
        p.drawRect(r)
        cx, cy = x + _TS / 2, y + _TS / 2
        if deco == "tree":
            p.setBrush(QColor("#6b4a2b"))
            p.drawRect(QRectF(cx - 3, cy + 2, 6, 12))
            p.setBrush(QColor("#3f7d3a"))
            p.drawEllipse(QPointF(cx, cy - 2), 15, 14)
            p.setBrush(QColor("#4f9b48"))
            p.drawEllipse(QPointF(cx - 4, cy - 5), 8, 8)
        elif deco == "wall":
            p.setBrush(QColor("#8a8079"))
            p.drawRoundedRect(QRectF(x + 2, y + 2, _TS - 4, _TS - 4), 4, 4)
            p.setPen(QPen(QColor(0, 0, 0, 28), 1))
            p.drawLine(QPointF(x + 2, cy), QPointF(x + _TS - 2, cy))
            p.setPen(Qt.PenStyle.NoPen)
        elif deco == "water":
            p.setPen(QPen(QColor(255, 255, 255, 60), 2))
            p.drawArc(int(x + 8), int(cy - 4), 14, 10, 0, 180 * 16)
            p.drawArc(int(x + 22), int(cy + 4), 14, 10, 0, 180 * 16)
            p.setPen(Qt.PenStyle.NoPen)
        elif deco == "flower":
            for (ox, oy, col) in ((-8, -6, "#e85d8a"), (9, -2, "#f0c93b"), (-2, 9, "#6fa8ff")):
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(cx + ox, cy + oy), 3, 3)

    def _draw_entity(self, p, x, y, ent):
        cx, cy = x + _TS / 2, y + _TS / 2
        t = ent["type"]
        if t == "npc":
            self._draw_person(p, cx, cy, "#4f7fe0", "#dfeaff")
            self._draw_label(p, cx, y - 4, ent["name"], "#1d2a4a", "#cfe0ff")
        elif t == "enemy":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#7a2230"))
            p.drawEllipse(QPointF(cx, cy), 16, 16)
            p.setBrush(QColor("#c0392b"))
            p.drawEllipse(QPointF(cx, cy), 13, 13)
            p.setBrush(QColor("#ffe14d"))
            p.drawEllipse(QPointF(cx - 5, cy - 2), 2.6, 3.4)
            p.drawEllipse(QPointF(cx + 5, cy - 2), 2.6, 3.4)
            self._draw_label(p, cx, y - 4, ent["name"], "#3a0d14", "#ffd2cc")
        elif t == "item":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f0c93b"))
            p.drawPolygon(QPolygonF([QPointF(cx, cy - 11), QPointF(cx + 9, cy),
                                     QPointF(cx, cy + 11), QPointF(cx - 9, cy)]))
            p.setBrush(QColor("#fff2b0"))
            p.drawPolygon(QPolygonF([QPointF(cx, cy - 6), QPointF(cx + 5, cy),
                                     QPointF(cx, cy + 6), QPointF(cx - 5, cy)]))
        elif t == "exit":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#6e56cf"))
            p.drawRoundedRect(QRectF(cx - 13, cy - 16, 26, 32), 11, 11)
            p.setBrush(QColor("#2b2350"))
            p.drawRoundedRect(QRectF(cx - 8, cy - 8, 16, 24), 7, 7)
            self._draw_label(p, cx, y - 4, ent["name"], "#2b2350", "#e2dcff")

    def _draw_person(self, p, cx, cy, body, face):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QPointF(cx, cy + 15), 13, 5)
        p.setBrush(QColor(body))
        p.drawRoundedRect(QRectF(cx - 11, cy - 14, 22, 28), 9, 9)
        p.setBrush(QColor(face))
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
        # 朝向小三角
        p.setBrush(QColor("#a85515"))
        dx, dy = _DIRS[self.facing]
        tx, ty = cx + dx * 13, cy + 2 + dy * 12
        ang = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[self.facing]
        perp = (-ang[1], ang[0])
        p.drawPolygon(QPolygonF([
            QPointF(tx + ang[0] * 5, ty + ang[1] * 5),
            QPointF(tx + perp[0] * 4, ty + perp[1] * 4),
            QPointF(tx - perp[0] * 4, ty - perp[1] * 4)]))
        p.setBrush(QColor("#1d1d22"))
        p.drawEllipse(QPointF(cx - 3.4, cy - 9), 1.8, 2.2)
        p.drawEllipse(QPointF(cx + 3.4, cy - 9), 1.8, 2.2)

    def _draw_label(self, p, cx, top, text, bg, fg):
        f = QFont()
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text) + 12
        r = QRectF(cx - tw / 2, top - 16, tw, 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.setOpacity(0.82)
        p.drawRoundedRect(r, 6, 6)
        p.setOpacity(1.0)
        p.setPen(QColor(fg))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_hud(self, p, vw):
        pl = self.win.player
        r = QRectF(12, 12, 280, 64)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 28, 165))
        p.drawRoundedRect(r, 12, 12)
        # HP 条
        ratio = max(0.0, min(1.0, pl["hp"] / pl["max_hp"]))
        col = "#d23b3b" if ratio < 0.3 else ("#e0a02e" if ratio < 0.6 else "#3fce6a")
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawRoundedRect(QRectF(54, 22, 226, 12), 6, 6)
        p.setBrush(QColor(col))
        p.drawRoundedRect(QRectF(54, 22, max(12, 226 * ratio), 12), 6, 6)
        f = QFont(); f.setPixelSize(12); f.setBold(True); p.setFont(f)
        p.setPen(QColor("#ff9a9a"))
        p.drawText(QRectF(20, 18, 34, 18), Qt.AlignmentFlag.AlignLeft, "HP")
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(54, 22, 226, 12), Qt.AlignmentFlag.AlignCenter,
                   f"{max(0,pl['hp'])}/{pl['max_hp']}")
        # 金币 + 背包
        f2 = QFont(); f2.setPixelSize(12); p.setFont(f2)
        p.setPen(QColor("#ffd479"))
        p.drawText(QRectF(20, 44, 130, 18), Qt.AlignmentFlag.AlignLeft,
                   f"金币 {pl['gold']}    攻击 {pl['atk']}")
        p.setPen(QColor("#cfe0ff"))
        p.drawText(QRectF(150, 44, 130, 18), Qt.AlignmentFlag.AlignLeft,
                   f"背包 {len(pl['items'])}")
        # 区域名
        name = self.win.world.get("name", "")
        if name:
            p.setPen(QColor(255, 255, 255, 220))
            f3 = QFont(); f3.setPixelSize(14); f3.setBold(True); p.setFont(f3)
            tw = p.fontMetrics().horizontalAdvance(name) + 28
            rr = QRectF(vw - tw - 12, 12, tw, 30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 22, 28, 165))
            p.drawRoundedRect(rr, 10, 10)
            p.setPen(QColor("#ffffff"))
            p.setFont(f3)
            p.drawText(rr, Qt.AlignmentFlag.AlignCenter, name)

    def _draw_hint(self, p, vw, vh):
        if self._paused or self.win.dialog_open():
            return
        npc = self._adjacent_npc()
        if not npc:
            return
        txt = f"按 空格 与「{npc['name']}」交谈"
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
        r = QRectF((vw - tw) / 2, 88, tw, 36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1f9d4d"))
        p.setOpacity(min(1.0, self._toast_t / 30.0))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._toast)
        p.setOpacity(1.0)

    def resizeEvent(self, e):
        self.win.layout_overlays()


# ── 主窗口 ────────────────────────────────────────────────────────────
_THEMES = ["迷雾森林", "幽暗地下城", "沙漠遗迹", "雪山村庄", "海盗港湾", "废土都市"]


class TextGameWindow(OpenHamWindowBase):
    """文字游戏主窗口（单例）：AI 实时生成的 2D 俯视 RPG。"""

    def __init__(self):
        super().__init__(title="文字游戏", min_w=820, min_h=560)
        self.resize(1040, 720)
        self.world = None
        self.player = None
        self._gen = 0
        self._dialog_npc = None
        self._busy_dialog = False

        self._sig = _Signals()
        self._sig.world_ready.connect(self._on_world)
        self._sig.dialog_ready.connect(self._on_dialog)
        self._sig.fail.connect(self._on_fail)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_start())     # 0
        self._stack.addWidget(self._build_loading())    # 1
        self._stack.addWidget(self._build_play())       # 2
        self.content_layout.addWidget(self._stack)
        self._stack.setCurrentIndex(0)

    # ── 页面 ──────────────────────────────────────────────────────────
    def _build_start(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(page)
        box = QWidget()
        box.setMaximumWidth(580)
        bv = QVBoxLayout(box)
        bv.setContentsMargins(40, 28, 40, 28)
        bv.setSpacing(13)
        title = QLabel("AI 冒险世界")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {theme.TEXT}; font-size: 30px; font-weight: 800; background: transparent;")
        bv.addWidget(title)
        sub = QLabel("写下一个主题，AI 即时为你生成一片可探索的世界")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {theme.TEXT2}; font-size: 14px; background: transparent;")
        bv.addWidget(sub)
        bv.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._theme_input = QLineEdit()
        self._theme_input.setPlaceholderText("例如：被诅咒的古堡、霓虹赛博都市、精灵森林…")
        self._theme_input.setFixedHeight(44)
        self._theme_input.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER_IN}; border-radius: 10px; padding: 0 14px;"
            f" font-size: 15px; }} QLineEdit:focus {{ border: 1px solid {theme.ACCENT}; }}")
        self._theme_input.returnPressed.connect(
            lambda: self._start(self._theme_input.text().strip()))
        row.addWidget(self._theme_input, 1)
        go = QPushButton("进入世界")
        go.setFixedHeight(44)
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: #fff; border: none;"
            f" border-radius: 10px; padding: 0 20px; font-size: 15px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {theme.ACCENT_HOV}; }}")
        go.clicked.connect(lambda: self._start(self._theme_input.text().strip()))
        row.addWidget(go)
        bv.addLayout(row)
        tip = QLabel("或选一个开头")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet(f"color: {theme.TEXT3}; font-size: 12px; background: transparent;")
        bv.addWidget(tip)
        for i in range(0, len(_THEMES), 3):
            r = QHBoxLayout()
            r.setSpacing(8)
            for t in _THEMES[i:i + 3]:
                chip = QPushButton(t)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setFixedHeight(34)
                chip.setStyleSheet(
                    f"QPushButton {{ background: {theme.ACCENT_SOFT}; color: {theme.TEXT};"
                    f" border: 1px solid {theme.BORDER}; border-radius: 17px; padding: 0 16px;"
                    f" font-size: 13px; }} QPushButton:hover {{ background: {theme.SELECT};"
                    f" border-color: {theme.BORDER_IN}; }}")
                chip.clicked.connect(lambda _, x=t: self._start(x))
                r.addWidget(chip)
            r.addStretch(1)
            bv.addLayout(r)
        outer.addStretch(1)
        wrap = QHBoxLayout()
        wrap.addStretch(1); wrap.addWidget(box); wrap.addStretch(1)
        outer.addLayout(wrap)
        outer.addStretch(1)
        return page

    def _build_loading(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        v = QVBoxLayout(page)
        v.addStretch(1)
        self._loading_lbl = QLabel("正在生成世界…")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 18px; font-weight: 600; background: transparent;")
        v.addWidget(self._loading_lbl)
        self._loading_sub = QLabel("AI 正在绘制地图、安排 NPC 与敌人")
        self._loading_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_sub.setStyleSheet(
            f"color: {theme.TEXT2}; font-size: 13px; background: transparent;")
        v.addWidget(self._loading_sub)
        v.addStretch(1)
        self._dots = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._anim_loading)
        return page

    def _anim_loading(self):
        self._dots = (self._dots + 1) % 4
        self._loading_lbl.setText(getattr(self, "_loading_base", "正在生成世界")
                                  + "・" * self._dots)

    def _build_play(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = _WorldCanvas(self)
        lay.addWidget(self.canvas)
        self.dialog = _DialogBox(self.canvas)
        self.combat = _CombatOverlay(self.canvas)
        self.confetti = gp.ConfettiOverlay(self.canvas)
        return page

    # ── 流程 ──────────────────────────────────────────────────────────
    def _start(self, theme_text):
        theme_text = (theme_text or "一片神秘的土地").strip()
        self.player = {"hp": 100, "max_hp": 100, "gold": 0, "atk": 5, "items": []}
        self._loading_base = "正在生成世界"
        self._loading_lbl.setText(self._loading_base)
        self._loading_sub.setText("AI 正在绘制地图、安排 NPC 与敌人")
        self._stack.setCurrentIndex(1)
        self._loading_timer.start(350)
        self._gen_world(theme_text, intro=True)

    def _gen_world(self, theme_text, intro=False):
        self._gen += 1
        gen = self._gen

        def work():
            try:
                raw = call_deepseek_sync(
                    f"主题：{theme_text}。请生成这块区域。", None, _WORLD_SYS, max_tokens=2600)
                world = _parse_world(raw) or _fallback_world(theme_text)
            except Exception:
                world = _fallback_world(theme_text)
            self._sig.world_ready.emit(gen, world)

        threading.Thread(target=work, daemon=True).start()

    def _on_world(self, gen, world):
        if gen != self._gen:
            return
        self._loading_timer.stop()
        self.world = world
        self._stack.setCurrentIndex(2)
        self.canvas.load(world["start"])
        self.layout_overlays()
        QTimer.singleShot(0, self.canvas.setFocus)        # 确保画布拿到键盘焦点
        self.canvas.toast("↑↓←→ / WASD 移动 · 空格 交互")
        if world.get("intro"):
            QTimer.singleShot(120, lambda: self._show_dialog(world["name"], world["intro"]))

    def _on_fail(self, gen, msg):
        if gen != self._gen:
            return
        self._loading_timer.stop()
        self.world = _fallback_world("起始草原")
        self._stack.setCurrentIndex(2)
        self.canvas.load(self.world["start"])
        self.layout_overlays()

    # ── 画布回调 ───────────────────────────────────────────────────────
    def entity_at(self, x, y):
        if not self.world:
            return None
        for e in self.world["entities"]:
            if e["x"] == x and e["y"] == y:
                return e
        return None

    def pickup(self, item):
        self.world["entities"].remove(item)
        eff = item.get("effect")
        val = item.get("value", 0)
        if eff == "gold":
            self.player["gold"] += val
            self.canvas.toast(f"拾取 {item['name']}（+{val} 金币）")
        elif eff == "weapon":
            self.player["items"].append(item)
            if val > 0:
                self.player["atk"] += val
            self.canvas.toast(f"装备 {item['name']}（攻击 +{val}）")
        elif eff == "heal":
            self.player["items"].append(item)
            self.canvas.toast(f"获得 {item['name']}（战斗中可用）")
        else:
            self.player["items"].append(item)
            self.canvas.toast(f"拾取 {item['name']}")

    def enter_exit(self, ex):
        self.canvas.set_paused(True)
        self._loading_base = "正在前往 " + ex.get("to", "新的区域")
        self._loading_lbl.setText(self._loading_base)
        self._loading_sub.setText("AI 正在生成下一片世界")
        self._stack.setCurrentIndex(1)
        self._loading_timer.start(350)
        self._gen_world(ex.get("to", "未知之地"))

    def start_combat(self, enemy):
        self.canvas.set_paused(True)
        self.combat.setGeometry(self.canvas.rect())
        self.combat.start(self.player, enemy, self._combat_done)

    def _combat_done(self, result):
        if result == "win":
            try:
                self.world["entities"].remove(self.combat._enemy)
            except (ValueError, AttributeError):
                pass
            self.confetti.setGeometry(self.canvas.rect())
            self.confetti.burst()
            self.canvas.set_paused(False)
            self.canvas.setFocus()
        elif result == "flee":
            self.canvas.set_paused(False)
            self.canvas.setFocus()
        else:                              # lose
            self._game_over()

    def _game_over(self):
        self._show_dialog("游戏结束", "你的冒险到此为止……")
        QTimer.singleShot(1600, lambda: self._stack.setCurrentIndex(0))

    # ── 对话 ──────────────────────────────────────────────────────────
    def dialog_open(self):
        return self.dialog.isVisible()

    def close_dialog(self):
        self.dialog.hide()
        self.canvas.set_paused(False)
        self.canvas.setFocus()

    def _show_dialog(self, speaker, text):
        self.canvas.set_paused(True)
        self.dialog.show_dialog(speaker, text)
        self.layout_overlays()

    def talk(self, npc):
        if self._busy_dialog:
            return
        self._busy_dialog = True
        self._dialog_npc = npc
        self._show_dialog(npc["name"], "……")
        self._gen += 0   # 对话不改世界代数
        gen = self._gen
        brief = npc.get("brief", "")
        wname = self.world.get("name", "")
        sysp = ("你在为一个 2D RPG 扮演一个 NPC。只用这个 NPC 的口吻说 1–3 句中文台词，"
                "可以给点提示、线索或风味，不要旁白、不要引号、不要解释。")
        prompt = (f"区域：{wname}。NPC：{npc['name']}（{brief}）。"
                  f"玩家上前搭话，请说出这个角色会说的话。")

        def work():
            try:
                txt = call_deepseek_sync(prompt, None, sysp, max_tokens=200).strip()
            except Exception:
                txt = "（这个人只是沉默地看着你。）"
            self._sig.dialog_ready.emit(gen, txt or "……")

        threading.Thread(target=work, daemon=True).start()

    def _on_dialog(self, gen, text):
        self._busy_dialog = False
        if self._dialog_npc is None or not self.dialog.isVisible():
            return
        self.dialog.show_dialog(self._dialog_npc["name"], text)

    # 无边框窗口下焦点常落在别处，键盘事件会冒泡到窗口；对局中转交给画布处理，
    # 这样即便画布没拿到焦点也能用方向键移动。
    def keyPressEvent(self, e):
        if self._stack.currentIndex() == 2 and hasattr(self, "canvas"):
            self.canvas.keyPressEvent(e)
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if self._stack.currentIndex() == 2 and hasattr(self, "canvas"):
            self.canvas.keyReleaseEvent(e)
        else:
            super().keyReleaseEvent(e)

    # ── 布局 ──────────────────────────────────────────────────────────
    def layout_overlays(self):
        if not hasattr(self, "canvas"):
            return
        r = self.canvas.rect()
        m = 18
        dh = max(96, self.dialog.sizeHint().height())
        self.dialog.setGeometry(m, r.height() - dh - 16, max(200, r.width() - 2 * m), dh)
        self.combat.setGeometry(r)
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
        if self._stack.currentIndex() == 2:
            self.canvas.setFocus()
