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
        code_url = info.get("code_url") or (base_url.rstrip("/") + "/OpenHam-code.zip")
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


def apply_update(code_url: str, timeout: int = 120) -> bool:
    """下载代码包并覆盖到安装目录（保留 runtime/.env/user_settings 等）。"""
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
    return count > 0
