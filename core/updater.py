"""应用内增量更新：只更新代码文件，不动 runtime / 依赖 / 用户数据。

机制：
- ECS 上有 version.json（最新版本号 + 代码包地址）和 OpenHam-code.zip（仅源码，几 MB）。
- App 比对本地 version.txt 与线上版本号，不同则下载代码包覆盖安装目录，重启生效。
- 覆盖时跳过 runtime/、.env、user_settings.json 等，保留依赖与用户配置。
"""
import os
import io
import json
import zipfile
import urllib.request

from utils.paths import _base_dir
from core.logging_setup import get_logger

log = get_logger("updater")

# 更新时不覆盖的顶层路径（依赖、密钥、用户数据、正在运行的 exe）
_SKIP_TOP = {"runtime", ".env", "user_settings.json", "openham.log",
             ".git", "OpenHam.exe", "logo.ico", "OpenHam_lite", "OpenHam_send"}


def local_version() -> str:
    try:
        with open(os.path.join(_base_dir(), "version.txt"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def check_update(base_url: str, timeout: int = 8):
    """返回 (有更新, 最新版本, 代码包URL, 说明)。失败返回 (False, ...)。"""
    try:
        url = base_url.rstrip("/") + "/version.json"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8"))
        latest = str(info.get("version", "")).strip()
        code_url = info.get("code_url") or "OpenHam-code.zip"
        if "://" not in code_url:   # 相对地址 → 拼成绝对地址，避免 urlopen 报 unknown url type
            code_url = base_url.rstrip("/") + "/" + code_url.lstrip("/")
        notes = info.get("notes", "")
        has = bool(latest) and latest != local_version()
        return has, latest, code_url, notes
    except Exception as e:
        log.warning("检查更新失败：%s", e)
        return False, "", "", ""


def _safe_join(base: str, rel: str) -> str:
    target = os.path.realpath(os.path.join(base, rel))
    b = os.path.realpath(base)
    if target == b or target.startswith(b + os.sep):
        return target
    raise ValueError(f"非法路径：{rel}")


def apply_update(code_url: str, timeout: int = 120, install_deps: bool = True) -> bool:
    """下载代码包并覆盖到安装目录（保留 runtime/.env/user_settings 等）。
    install_deps=True 时更新后按新 requirements.txt 补装依赖（走阿里镜像，已装的会跳过）。"""
    base = _base_dir()
    with urllib.request.urlopen(code_url, timeout=timeout) as r:
        data = r.read()
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            if member.endswith("/"):
                continue
            # 包内形如 OpenHam/core/xxx.py，去掉顶层目录
            rel = member.split("/", 1)[1] if "/" in member else member
            if not rel:
                continue
            top = rel.split("/", 1)[0]
            if top in _SKIP_TOP:
                continue
            target = _safe_join(base, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(member) as src, open(target, "wb") as out:
                out.write(src.read())
            count += 1
    log.info("增量更新完成，覆盖 %d 个文件", count)
    if install_deps:
        _sync_deps()
    return count > 0


def _sync_deps():
    """按更新后的 requirements.txt 补装新依赖（已满足的会被 pip 跳过，很快）。"""
    import sys
    import subprocess
    req = os.path.join(_base_dir(), "requirements.txt")
    if not os.path.exists(req):
        return
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", req],
            cwd=_base_dir(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags, timeout=900)
        log.info("更新后依赖同步完成")
    except Exception as e:
        log.warning("更新后补装依赖失败：%s", e)
