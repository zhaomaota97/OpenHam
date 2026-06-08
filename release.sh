#!/usr/bin/env bash
# 一键发布 OpenHam 精简包到 ECS 下载页。
# 复用工作目录已安装的依赖，只是打包时把它们排除（精简包让用户首次运行从阿里镜像装）。
# 用法：在 WSL 里  bash release.sh
set -e

SRC="/mnt/c/Users/ning/Desktop/OpenHam"
LITE="/mnt/c/Users/ning/Desktop/OpenHam_lite"
ZIP="/mnt/c/Users/ning/Desktop/OpenHam-lite.zip"
KEY="$HOME/.ssh/openham_ecs"
ECS="root@47.102.218.59"
DEST="/opt/openham-dl/OpenHam-lite.zip"

echo "[1/3] 生成精简副本（排除依赖/敏感/dev 文件）…"
rm -rf "$LITE"; mkdir -p "$LITE"
rsync -a \
  --exclude='.git' --exclude='.env' --exclude='user_settings.json' \
  --exclude='openham.log' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='runtime/Lib/site-packages' --exclude='runtime/.deps_ok' \
  --exclude='runtime/Scripts' --exclude='OpenHam_send' --exclude='OpenHam_lite' \
  --exclude='release.sh' \
  "$SRC/" "$LITE/"

echo "[2/3] 打包 zip…"
python3 - "$LITE" "$ZIP" <<'PY'
import sys, os, zipfile
src, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for r, d, fs in os.walk(src):
        for f in fs:
            full = os.path.join(r, f)
            z.write(full, os.path.join("OpenHam", os.path.relpath(full, src)))
print("    zip 大小:", os.path.getsize(out)//1024//1024, "MB")
PY

echo "[3/3] 上传到 ECS（覆盖即生效，无需重启容器）…"
scp -i "$KEY" -o StrictHostKeyChecking=no "$ZIP" "$ECS:$DEST"

echo "✅ 已发布最新版 → http://47.102.218.59/openham/"
