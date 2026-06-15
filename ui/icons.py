"""统一图标助手：用 qtawesome（Font Awesome）替代项目里散落的 emoji。

两种用法：
- 控件（按钮/菜单/标题）：用 `qicon("publish")` 拿 QIcon → setIcon()。
- 富文本（聊天/系统日志/状态标签里的行内文字）：用 `richify(text)` 把字符串中的
  emoji 就地换成行内 <img> 图标；或直接 `img("success")` 取一段行内 HTML。

设计要点：
- qtawesome 缺失（精简包首次安装、依赖未就绪）时全部优雅降级：qicon→空图标，
  img/richify→保持原文，绝不抛异常、绝不崩。
- 行内图标渲染成 PNG 缓存到临时目录，用 file:// 引用，QLabel/QTextEdit 都能显示，
  不依赖把图标字体注册进 QFontDatabase，跨 qtawesome 版本稳定。
"""
import os
import tempfile

# 「精致白」主题：图标多为中性灰，主操作用蓝，AI 用靛，状态用语义色
GOLD = "#86868b"    # （沿用旧名）现为中性灰，作多数图标默认色
TEXT = "#1d1d1f"
MUTED = "#86868b"
GREEN = "#248a3d"
RED = "#d70015"
AMBER = "#b25000"
PURPLE = "#6e56cf"
ACCENT = "#1d1d1f"

# 语义名 -> (Font Awesome 名, 默认颜色)
_MAP = {
    "game": ("fa5s.gamepad", ACCENT),
    "ai": ("mdi6.creation", PURPLE),
    "import": ("fa5s.folder-open", GOLD),
    "publish": ("fa5s.rocket", GOLD),
    "delete": ("fa5s.trash-alt", "#c87a6a"),
    "copy": ("fa5s.copy", GOLD),
    "send": ("fa5s.paper-plane", GOLD),
    "success": ("fa5s.check-circle", GREEN),
    "error": ("fa5s.times-circle", RED),
    "warn": ("fa5s.exclamation-triangle", AMBER),
    "online": ("fa5s.circle", GREEN),
    "offline": ("fa5s.circle", RED),
    "host": ("fa5s.crown", "#d9b23c"),
    "download": ("fa5s.download", GOLD),
    "package": ("fa5s.box-open", GOLD),
    "loading": ("fa5s.hourglass-half", GOLD),
    "timer": ("fa5s.stopwatch", GOLD),
    "tomato": ("fa5s.stopwatch", "#e0584a"),
    "search": ("fa5s.search", MUTED),
    "list": ("fa5s.bars", MUTED),
    "settings": ("fa5s.cog", GOLD),
    "pin": ("fa5s.thumbtack", TEXT),
    "pinned": ("fa5s.thumbtack", GOLD),
    "info": ("fa5s.info-circle", GOLD),
    "refresh": ("fa5s.sync-alt", GOLD),
    "code": ("fa5s.code", GOLD),
    "play": ("fa5s.play", GOLD),
    "user": ("fa5s.user", MUTED),
    "users": ("fa5s.users", MUTED),
    "chat": ("fa5s.comment-dots", GOLD),
    "qrcode": ("fa5s.qrcode", GOLD),
    "image": ("fa5s.image", GOLD),
    "ocr": ("fa5s.font", GOLD),
    "calc": ("fa5s.calculator", GOLD),
    "terminal": ("fa5s.terminal", GOLD),
    "folder": ("fa5s.folder", GOLD),
    "bolt": ("fa5s.bolt", AMBER),
    "link": ("fa5s.link", GOLD),
    "git": ("fa5s.code-branch", GOLD),
    "home": ("fa5s.home", GOLD),
    "plugins": ("fa5s.puzzle-piece", GOLD),
    "quit": ("fa5s.power-off", MUTED),
    "script": ("fa5s.scroll", GOLD),
    "fix": ("fa5s.wrench", "#e0a04a"),
    "history": ("fa5s.history", MUTED),
    "save": ("fa5s.save", GOLD),
    "file": ("fa5s.file-alt", GOLD),
    "python": ("fa5b.python", GOLD),
    "shell": ("fa5s.terminal", GOLD),
    "powershell": ("fa5s.terminal", "#86868b"),
    "batch": ("fa5s.file-code", GOLD),
    "idea": ("fa5s.lightbulb", "#e0c64a"),
    "done": ("fa5s.flag-checkered", GREEN),
    "plug": ("fa5s.plug", GOLD),
    "coffee": ("fa5s.coffee", "#b0884a"),
    "tools": ("fa5s.tools", GOLD),
    "add": ("fa5s.plus-circle", GREEN),
    "edit": ("fa5s.pen", GOLD),
    "lock": ("fa5s.lock", AMBER),
    "signal": ("fa5s.wifi", GOLD),
    "check": ("fa5s.check", GREEN),
    "stop": ("fa5s.stop", RED),
    "close": ("fa5s.times", MUTED),
    "maximize": ("fa5.window-maximize", MUTED),
    "restore": ("fa5.window-restore", MUTED),
    "minimize": ("fa5s.window-minimize", MUTED),
    "robot": ("fa5s.robot", PURPLE),
    "panel": ("fa5s.columns", MUTED),
    "brain": ("fa5s.brain", PURPLE),
    "back": ("fa5s.arrow-left", MUTED),
    "forward": ("fa5s.arrow-right", MUTED),
    "up": ("fa5s.arrow-up", MUTED),
    "down": ("fa5s.arrow-down", MUTED),
    "shift": ("fa5s.long-arrow-alt-up", MUTED),
    "tab": ("fa5s.long-arrow-alt-right", MUTED),
    "enter": ("mdi6.keyboard-return", MUTED),
    "dot_off": ("fa5s.circle", MUTED),
}

# 源码里出现的 emoji -> 语义名（richify 用；含变体选择符 ️ 的放前面先匹配）
_EMOJI = [
    ("⚠️", "warn"), ("⚠", "warn"),
    ("⚙️", "settings"), ("⚙", "settings"),
    ("⏱️", "timer"), ("⏱", "timer"),
    ("🎮", "game"), ("✨", "ai"), ("🧠", "ai"),
    ("📁", "import"), ("🚀", "publish"), ("🗑", "delete"),
    ("📋", "copy"), ("✅", "success"), ("❌", "error"),
    ("🟢", "online"), ("🔴", "offline"), ("👑", "host"),
    ("📥", "download"), ("📦", "package"), ("⏳", "loading"),
    ("🍅", "tomato"), ("🔍", "search"), ("≡", "list"),
    ("📍", "pin"), ("📌", "pinned"),
    ("🔗", "link"), ("💬", "chat"),
    ("📜", "script"), ("💡", "idea"), ("🎉", "done"),
    ("🛠️", "tools"), ("🛠", "tools"), ("🦊", "git"), ("🧩", "plugins"),
    ("🖥️", "shell"), ("🖥", "shell"), ("🐍", "python"), ("🔷", "powershell"),
    ("📄", "file"), ("💾", "save"), ("📂", "folder"), ("🔌", "plug"),
    ("☕", "coffee"), ("⚡", "bolt"), ("🚑", "fix"),
    ("📶", "signal"), ("✏️", "edit"), ("✏", "edit"), ("✚", "add"),
    ("🔒", "lock"), ("📦", "package"),
    # 通用符号字形（非 prose 箭头）→ 图标
    ("✕", "close"), ("✗", "close"), ("✘", "close"),
    ("✓", "check"), ("✔", "check"), ("✔️", "check"),
    ("↻", "refresh"), ("↺", "refresh"), ("⟳", "refresh"),
    ("▶", "play"), ("▶️", "play"), ("◀", "back"),
    ("↵", "enter"), ("↩", "enter"), ("↩️", "enter"),
    ("⇧", "shift"), ("⇥", "tab"),
]

_cache = {}


def _qta():
    try:
        import qtawesome as qta
        return qta
    except Exception:
        return None


def qicon(name: str, color: str = None, size: int = 0):
    """返回 QIcon（控件用）。qtawesome 缺失或图标名无效时返回空 QIcon。"""
    from PyQt6.QtGui import QIcon
    qta = _qta()
    fa, default = _MAP.get(name, (None, GOLD))
    if qta is None or fa is None:
        return QIcon()
    try:
        return qta.icon(fa, color=(color or default))
    except Exception:
        return QIcon()


def _png_path(name: str, color: str, px: int):
    """把图标渲染成 PNG 缓存，返回文件路径；失败返回 None。"""
    fa, default = _MAP.get(name, (None, GOLD))
    if fa is None:
        return None
    col = color or default
    # 缓存键含字形名：改了图标字形也会生成新缓存，不会复用旧 PNG
    key = f"{name}_{fa.replace('.', '-')}_{col.lstrip('#')}_{px}"
    if key in _cache:
        return _cache[key]
    qta = _qta()
    if qta is None:
        return None
    try:
        from PyQt6.QtCore import QSize
        d = os.path.join(tempfile.gettempdir(), "openham_icons")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, key + ".png")
        if not os.path.exists(path):
            pm = qta.icon(fa, color=col).pixmap(QSize(px * 2, px * 2))
            pm.save(path, "PNG")
        _cache[key] = path
        return path
    except Exception:
        return None


def img(name: str, color: str = None, size: int = 14) -> str:
    """返回一段行内 <img> HTML（富文本用）。失败返回空串。"""
    path = _png_path(name, color, size)
    if not path:
        return ""
    try:
        from PyQt6.QtCore import QUrl
        url = QUrl.fromLocalFile(path).toString()
    except Exception:
        url = "file:///" + path.replace("\\", "/")
    return (f'<img src="{url}" width="{size}" height="{size}" '
            f'style="vertical-align:middle;">')


def richify(text: str, size: int = 14) -> str:
    """把字符串里已知的 emoji 就地替换成行内图标 HTML。无 emoji 时原样返回。"""
    if not text:
        return text
    out = text
    for em, name in _EMOJI:
        if em in out:
            html = img(name, size=size)
            if html:                      # 拿不到图标(qtawesome 未就绪)时保留原 emoji，避免空白
                out = out.replace(em, html)
    return out


def strip(text: str) -> str:
    """去掉字符串里已知的 emoji（用于无法承载图标的纯文本场景，如下拉/省略文本）。"""
    if not text:
        return text
    out = text
    for em, _name in _EMOJI:
        if em in out:
            out = out.replace(em, "")
    return out.replace("  ", " ").strip()
