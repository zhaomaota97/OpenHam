"""游戏库：管理用户自己的游戏（AI 发明的 + 导入的），统一存放、列出、删除。

存放在 安装目录/my_games/<游戏名_时间>/（index.html + manifest.json）。
向后兼容：也会列出旧的 invented_games/ 里的游戏。
"""
import os
import re
import json
import time
import shutil

from utils.paths import _base_dir
from core import game_package

_LIB = "my_games"
_LEGACY = "invented_games"
_BUILTIN = "games"          # 安装包自带的游戏（井字棋等），首次运行导入到用户库
_MARKER = ".builtins_v1"


def _lib_dir() -> str:
    d = os.path.join(_base_dir(), _LIB)
    os.makedirs(d, exist_ok=True)
    return d


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip()) or "游戏"


def ensure_builtins():
    """首次运行时，把安装包自带的游戏（games/）导入到用户游戏库，只做一次。
    用户之后删了也不会再被导入（靠 marker 标记）。"""
    marker = os.path.join(_lib_dir(), _MARKER)
    if os.path.exists(marker):
        return
    src_root = os.path.join(_base_dir(), _BUILTIN)
    if os.path.isdir(src_root):
        for fn in sorted(os.listdir(src_root)):
            folder = os.path.join(src_root, fn)
            if os.path.isdir(folder) and os.path.isfile(os.path.join(folder, "index.html")):
                try:
                    import_folder(folder)
                except Exception:
                    pass
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write("1")
    except Exception:
        pass


def list_games() -> list:
    """返回 [{'name', 'folder'}]，按时间倒序（新的在前）。"""
    ensure_builtins()
    games = []
    for base in (_lib_dir(), os.path.join(_base_dir(), _LEGACY)):
        if not os.path.isdir(base):
            continue
        for fn in os.listdir(base):
            folder = os.path.join(base, fn)
            if not os.path.isdir(folder) or not os.path.isfile(os.path.join(folder, "index.html")):
                continue
            title = fn
            mf = os.path.join(folder, "manifest.json")
            if os.path.isfile(mf):
                try:
                    with open(mf, "r", encoding="utf-8") as f:
                        title = json.load(f).get("name", fn)
                except Exception:
                    pass
            games.append({"name": title, "folder": folder, "_mtime": os.path.getmtime(folder)})
    games.sort(key=lambda g: g["_mtime"], reverse=True)
    return games


def save_html(name: str, html: str) -> str:
    """保存一个 AI 生成的单文件游戏到库，返回其文件夹。"""
    folder = os.path.join(_lib_dir(), f"{_safe(name)}_{time.strftime('%m%d_%H%M%S')}")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "entry": "index.html"}, f, ensure_ascii=False)
    return folder


def import_folder(src: str) -> str:
    """把一个外部游戏文件夹导入到库（校验有入口），返回库内文件夹。"""
    game_package.pack_folder(src)  # 校验：没有 index.html / 超限会抛 GamePackageError
    name = os.path.basename(src.rstrip("/\\")) or "导入游戏"
    dest = os.path.join(_lib_dir(), f"{_safe(name)}_{time.strftime('%m%d_%H%M%S')}")
    shutil.copytree(src, dest)
    return dest


def delete_game(folder: str) -> bool:
    """删除库内游戏（限制在 my_games / invented_games 内，防误删）。"""
    real = os.path.realpath(folder)
    allowed = (os.path.realpath(_lib_dir()), os.path.realpath(os.path.join(_base_dir(), _LEGACY)))
    if not any(real.startswith(a + os.sep) for a in allowed):
        return False
    shutil.rmtree(real, ignore_errors=True)
    return True
