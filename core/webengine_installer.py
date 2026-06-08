"""下载并安装游戏组件（PyQt6-WebEngine / Chromium），带真实下载进度。

pip 在非终端下不输出可解析的字节进度，所以这里自己从阿里镜像解析轮子地址、
用 urllib 分块下载并统计字节（总大小 / 已下载），最后用 pip 安装本地轮子。
"""
import os
import re
import sys
import tempfile
import subprocess
import urllib.parse
import urllib.request

from core.logging_setup import get_logger

log = get_logger("we_install")

MIRROR = "https://mirrors.aliyun.com/pypi/simple"
# 基础 PyQt6/sip 已在安装时装好；这里只需补这两个（大头是 -Qt6 的 ~300MB Chromium）
PKGS = ["pyqt6-webengine", "pyqt6-webengine-qt6"]
_CHUNK = 1 << 16


def _resolve(pkg: str) -> str:
    """从镜像的 simple 索引里挑出最高版本的 win_amd64 轮子地址。"""
    idx = f"{MIRROR}/{pkg}/"
    page = urllib.request.urlopen(idx, timeout=20).read().decode("utf-8", "replace")
    best, bestv = None, ()
    for href in re.findall(r'href=["\']([^"\']+)["\']', page):
        clean = href.split("#")[0]
        fn = clean.rsplit("/", 1)[-1]
        if not fn.endswith("win_amd64.whl"):
            continue
        m = re.search(r"-(\d+(?:\.\d+)+)-", fn)
        if not m:
            continue
        v = tuple(int(x) for x in m.group(1).split("."))
        if v > bestv:
            bestv, best = v, urllib.parse.urljoin(idx, clean)
    if not best:
        raise Exception(f"未在镜像找到 {pkg} 的 win_amd64 轮子")
    return best


def _size(url: str) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length", 0))
    except Exception:
        return 0


def install(progress_cb=None) -> bool:
    """progress_cb(done_bytes, total_bytes) 在下载过程中被回调。装好返回 True。"""
    tmp = tempfile.mkdtemp(prefix="openham_we_")
    items = []  # (url, dest)
    total = 0
    for pkg in PKGS:
        url = _resolve(pkg)
        dest = os.path.join(tmp, url.rsplit("/", 1)[-1])
        total += _size(url)
        items.append((url, dest))

    done = 0
    last = 0
    for url, dest in items:
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and done - last >= 512 * 1024:
                    last = done
                    progress_cb(done, total)
    if progress_cb:
        progress_cb(done, total)

    log.info("游戏组件已下载，开始安装本地轮子")
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    files = [d for _, d in items]
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", *files],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=flags, timeout=600)
    return True
