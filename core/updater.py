"""应用内增量更新：只更新代码文件，不动 runtime / 依赖 / 用户数据。

机制：
- ECS 上有 version.json（最新版本号 + 代码包地址）和 OpenHam-code.zip（仅源码，几 MB）。
- App 比对本地 version.txt 与线上版本号，不同则下载代码包覆盖安装目录，重启生效。
- 覆盖时跳过 runtime/、.env、user_settings.json 等，保留依赖与用户配置。
"""
import os
import io
import json
import shutil
import zipfile
import urllib.request

from utils.paths import _base_dir
from core.logging_setup import get_logger

log = get_logger("updater")

# 更新时不覆盖的路径（依赖、密钥、用户配置/脚本/游戏、正在运行的 exe）
_SKIP = ["runtime", ".env", "user_settings.json", "openham.log",
         ".git", "OpenHam.exe", "logo.ico", "OpenHam_lite", "OpenHam_send",
         "config.json", "config/plugins.json",
         "script_manager/scripts.json", "ui/script_manager/history.json",
         "ui/script_manager/workspace", "ai_chat",
         "invented_games", "my_games"]


# 旧版遗留、新版已删除的路径：增量更新只会覆盖/新增文件，不会删文件，
# 这里在更新时主动清理它们，避免安装目录残留旧目录。
_OBSOLETE = ["examples", "plugins/translate.py",
             "games/pong", "games/neon", "games/moba", "games/arena"]


def _cleanup_obsolete(base: str):
    for rel in _OBSOLETE:
        try:
            target = _safe_join(base, rel)
        except ValueError:
            continue
        try:
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            elif os.path.exists(target):
                os.remove(target)
        except Exception as e:
            log.warning("清理旧路径 %s 失败：%s", rel, e)


def _should_skip(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    for s in _SKIP:
        if rel == s or rel.startswith(s + "/"):
            return True
    return False


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


def _download_resumable(url: str, timeout: int = 120, progress_cb=None,
                        max_attempts: int = 60) -> bytes:
    """带断点续传 + 重试的下载，专治不稳定链路（连接常在传输中途被掐断）。

    服务器支持 Range（Accept-Ranges: bytes）时，每次断流就用 Range 从断点续传，
    分多段拼成完整文件；不支持 Range 的服务器则整包重下。下载完成后由调用方校验
    总大小与 zip 合法性，避免把半截数据当成更新包。"""
    # 先探总大小（HEAD）；失败则等首个 GET 响应里再取
    total = 0
    try:
        head = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(head, timeout=timeout) as r:
            total = int(r.headers.get("Content-Length", 0) or 0)
    except Exception:
        total = 0

    buf = bytearray()
    attempts = 0
    stagnant = 0
    while True:
        if total and len(buf) >= total:
            break
        have = len(buf)
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                # 服务器忽略 Range、返回 200 整包：丢弃已收、从头接收
                if have and r.getcode() == 200:
                    buf = bytearray()
                if not total:
                    cl = int(r.headers.get("Content-Length", 0) or 0)
                    if cl:
                        total = len(buf) + cl
                while True:
                    chunk = r.read(1 << 15)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    if progress_cb and total:
                        progress_cb(len(buf), total)
        except Exception as e:
            log.warning("下载分段中断（已收 %d/%s）：%s", len(buf), total or "?", e)

        attempts += 1
        stagnant = stagnant + 1 if len(buf) == have else 0
        if total and len(buf) >= total:
            break
        # 无总大小可判：拿到过数据且本轮再没新增，视为已下完
        if not total and len(buf) and stagnant >= 1:
            break
        if attempts >= max_attempts or stagnant >= 8:
            raise Exception(
                f"下载反复中断，仅取得 {len(buf)}/{total or '?'} 字节；"
                "网络到更新服务器的连接不稳定，请稍后重试。")
    if progress_cb and total:
        progress_cb(len(buf), total)
    return bytes(buf)


def apply_update(code_url: str, timeout: int = 120, install_deps: bool = True,
                 progress_cb=None) -> bool:
    """下载代码包并覆盖到安装目录（保留 runtime/.env/user_settings 等）。
    progress_cb(done_bytes, total_bytes) 在下载中被回调。
    install_deps=True 时更新后按新 requirements.txt 补装依赖（走阿里镜像，已装的会跳过）。"""
    base = _base_dir()
    data = _download_resumable(code_url, timeout=timeout, progress_cb=progress_cb)
    # 安装前校验：必须是完整、合法的 zip，杜绝把被截断的半截数据当更新包（旧版「不是zip」根因）
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise Exception("下载的更新包不是有效的 zip（可能仍被网络截断），请重试更新。")
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            if member.endswith("/"):
                continue
            # 包内形如 OpenHam/core/xxx.py，去掉顶层目录
            rel = member.split("/", 1)[1] if "/" in member else member
            if not rel or _should_skip(rel):
                continue
            target = _safe_join(base, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(member) as src, open(target, "wb") as out:
                out.write(src.read())
            count += 1
    _cleanup_obsolete(base)
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
