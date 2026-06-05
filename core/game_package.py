"""游戏包：把一个 html 游戏目录打包成 zip 字节，并安全解包运行。

包结构（甲准备的目录）：
    mygame/
      index.html        # 入口（默认）
      manifest.json     # 可选：{"name": "...", "entry": "index.html"}
      *.js / *.css / 图片 / 音频 ...

设计：
- 仅 html/js/css/资源 在沙箱网页视图中渲染，不执行本地可执行文件 → 风险受限。
- 解包做 zip-slip 防护（拒绝跳出目标目录的路径）。
- 体积上限，避免误传超大目录。
"""
import os
import io
import json
import zipfile

MANIFEST_NAME = "manifest.json"
DEFAULT_ENTRY = "index.html"
MAX_PACK_BYTES = 30 * 1024 * 1024   # 单个游戏包上限 30MB

# 不打包进去的垃圾/危险目录与文件
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".idea", ".vscode"}


class GamePackageError(Exception):
    pass


def _read_manifest_from_dir(folder: str) -> dict:
    path = os.path.join(folder, MANIFEST_NAME)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict):
                return m
        except Exception:
            pass
    return {}


def pack_folder(folder: str) -> bytes:
    """把游戏目录打包成 zip 字节。校验入口存在、体积不超限。"""
    if not os.path.isdir(folder):
        raise GamePackageError(f"目录不存在：{folder}")

    manifest = _read_manifest_from_dir(folder)
    entry = manifest.get("entry", DEFAULT_ENTRY)
    if not os.path.isfile(os.path.join(folder, entry)):
        raise GamePackageError(f"找不到入口文件 {entry}（请放一个 index.html 或在 manifest.json 指定 entry）")

    # 没有 manifest 时，自动补一个，便于对端识别
    if not manifest:
        manifest = {"name": os.path.basename(folder.rstrip("/\\")) or "游戏", "entry": entry}

    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # 始终写入（可能是补的）manifest
        z.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False))
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, folder).replace("\\", "/")
                if rel == MANIFEST_NAME:
                    continue  # 已单独写入
                total += os.path.getsize(full)
                if total > MAX_PACK_BYTES:
                    raise GamePackageError(f"游戏包超过 {MAX_PACK_BYTES // 1024 // 1024}MB 上限")
                z.write(full, rel)
    return buf.getvalue()


def package_name(data: bytes) -> str:
    """从包字节里读出游戏名（不解包到磁盘）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            with z.open(MANIFEST_NAME) as f:
                return json.load(f).get("name", "游戏")
    except Exception:
        return "游戏"


def _safe_join(dest: str, member: str) -> str:
    """防 zip-slip：拼出的路径必须仍在 dest 内。"""
    target = os.path.realpath(os.path.join(dest, member))
    base = os.path.realpath(dest)
    if not (target == base or target.startswith(base + os.sep)):
        raise GamePackageError(f"非法路径（疑似 zip-slip）：{member}")
    return target


def extract_package(data: bytes, dest_dir: str) -> dict:
    """把包字节安全解压到 dest_dir，返回 {name, entry, entry_path}。"""
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            if member.endswith("/"):
                continue
            target = _safe_join(dest_dir, member)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(member) as src, open(target, "wb") as out:
                out.write(src.read())
        try:
            with z.open(MANIFEST_NAME) as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    name = manifest.get("name", "游戏")
    entry = manifest.get("entry", DEFAULT_ENTRY)
    entry_path = os.path.join(dest_dir, entry)
    if not os.path.isfile(entry_path):
        raise GamePackageError(f"包内缺少入口文件 {entry}")
    return {"name": name, "entry": entry, "entry_path": entry_path}


if __name__ == "__main__":
    import tempfile, shutil
    # 自测：建临时游戏目录 → 打包 → 解包 → 校验
    src = tempfile.mkdtemp(prefix="game_src_")
    dst = tempfile.mkdtemp(prefix="game_dst_")
    try:
        with open(os.path.join(src, "index.html"), "w", encoding="utf-8") as f:
            f.write("<h1>Hi 喵</h1><script src='g.js'></script>")
        os.makedirs(os.path.join(src, "assets"))
        with open(os.path.join(src, "assets", "g.js"), "w") as f:
            f.write("console.log('game')")

        data = pack_folder(src)
        print(f"打包大小: {len(data)} 字节, 名称={package_name(data)!r}")
        info = extract_package(data, dst)
        print(f"解包: {info}")
        assert os.path.isfile(info["entry_path"])
        assert os.path.isfile(os.path.join(dst, "assets", "g.js"))

        # 缺入口应报错
        bad = tempfile.mkdtemp(prefix="game_bad_")
        try:
            pack_folder(bad); print("❌ 缺入口未报错")
        except GamePackageError:
            print("缺入口正确报错 ✓")
        finally:
            shutil.rmtree(bad, ignore_errors=True)

        print("\nGAME PACKAGE SELFTEST PASS")
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)
