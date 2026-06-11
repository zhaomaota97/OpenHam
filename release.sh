#!/usr/bin/env bash
# 一键发布 OpenHam 到 ECS：完整精简包（新用户）+ 代码包（老用户增量更新）+ version.json。
# 复用工作目录已安装的依赖，打包时排除；代码包还额外排除 runtime（增量更新只换代码）。
# 用法：在 WSL 里  bash release.sh
set -e

SRC="/mnt/c/Users/ning/Desktop/OpenHam"
LITE="/mnt/c/Users/ning/Desktop/OpenHam_lite"
ZIP="/mnt/c/Users/ning/Desktop/OpenHam-lite.zip"
CODEZIP="/mnt/c/Users/ning/Desktop/OpenHam-code.zip"
VJSON="/mnt/c/Users/ning/Desktop/version.json"
KEY="$HOME/.ssh/openham_ecs"
ECS="root@47.102.218.59"
DL="/opt/openham-dl"

VERSION_FILE="$SRC/VERSION"
VERSION="$(tr -d ' \t\r\n' < "$VERSION_FILE")"
echo "[1/4] 生成精简副本（版本 v$VERSION，排除依赖/敏感/dev 文件）…"
rm -rf "$LITE"; mkdir -p "$LITE"
rsync -a \
  --exclude='.git' --exclude='.env' --exclude='user_settings.json' \
  --exclude='openham.log' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='runtime/Lib/site-packages' --exclude='runtime/.deps_ok' \
  --exclude='runtime/Scripts' --exclude='OpenHam_send' --exclude='OpenHam_lite' \
  --exclude='release.sh' --exclude='invented_games' --exclude='my_games' \
  --exclude='ai_chat' --exclude='ui/script_manager/workspace' \
  "$SRC/" "$LITE/"
echo "$VERSION" > "$LITE/version.txt"   # 安装包内记录版本，供日后比对

echo "[2/4] 打包 完整精简包 + 代码包…"
python3 - "$LITE" "$ZIP" "$CODEZIP" "$VJSON" "$VERSION" <<'PY'
import sys, os, zipfile, json
src, out_lite, out_code, vjson, version = sys.argv[1:6]
# 增量代码包不含的用户状态文件（避免更新覆盖用户配置/脚本）
SKIP_CODE = {"config.json", "config/plugins.json",
             "script_manager/scripts.json", "ui/script_manager/history.json"}
def build(out, skip_runtime):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for r, d, fs in os.walk(src):
            for f in fs:
                full = os.path.join(r, f)
                rel = os.path.relpath(full, src)
                reln = rel.replace("\\", "/")
                if skip_runtime and (reln.split("/", 1)[0] == "runtime" or reln in SKIP_CODE):
                    continue
                z.write(full, os.path.join("OpenHam", rel))
    return os.path.getsize(out)
print("    完整包:", build(out_lite, False)//1024//1024, "MB")
print("    代码包:", build(out_code, True)//1024, "KB")
with open(vjson, "w", encoding="utf-8") as f:
    json.dump({"version": version,
               "code_url": "http://47.102.218.59/openham/OpenHam-code.zip",
               "notes": "增量更新（仅代码）"}, f, ensure_ascii=False)
PY

echo "[3/4] 上传 完整包 + 代码包 + version.json + 下载页 + logo…"
SCPOPT="-i $KEY -o StrictHostKeyChecking=no"
scp $SCPOPT "$ZIP" "$ECS:$DL/OpenHam-lite.zip"
scp $SCPOPT "$CODEZIP" "$ECS:$DL/OpenHam-code.zip"
scp $SCPOPT "$VJSON" "$ECS:$DL/version.json"
scp $SCPOPT "$SRC/relay/download.html" "$ECS:$DL/index.html"
scp $SCPOPT "$SRC/logo.png" "$ECS:$DL/logo.png"

# 发布成功后：把本机安装标记对齐到本次版本；VERSION 末位 +1 写回，供下次发布自增
echo "$VERSION" > "$SRC/version.txt"
NEXT="$(echo "$VERSION" | awk -F. '{printf "%d.%d.%d", $1, $2, ($3+1)}')"
echo "$NEXT" > "$VERSION_FILE"
(cd "$SRC" && git add VERSION && git commit -q -m "chore(release): v$VERSION（下一版预置 v$NEXT）" 2>/dev/null) || true

echo "[4/4] 完成 ✅  版本 v$VERSION → http://47.102.218.59/openham/   （VERSION 已写回 $NEXT 备下次）"
