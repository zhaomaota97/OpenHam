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
# Caddy 跑在容器里，只能看到它挂的 /data 卷；下载文件放卷的宿主机路径下（容器内即 /data/dl/openham）
DL="/var/lib/docker/volumes/edge_caddy_data/_data/dl/openham"

VERSION_FILE="$SRC/VERSION"
LOCAL_VER="$(tr -d ' \t\r\n' < "$VERSION_FILE")"
# 以服务器已发布版本为权威下限：发布版本必 > 线上版本，杜绝本地 VERSION 文件漂移
# （WSL /mnt/c 偶发不一致）导致的版本号撞车。本地比服务器新则用本地，否则服务器 +1。
SRV_VER="$(curl -s -m 10 https://openham.focus.beer/version.json 2>/dev/null \
  | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("version",""))
except: print("")' 2>/dev/null || true)"
VERSION="$(python3 - "$LOCAL_VER" "$SRV_VER" <<'PY'
import sys
def key(v):
    p = v.split('.')
    try:
        return tuple(int(x) for x in p[:3]) if len(p) == 3 else None
    except Exception:
        return None
loc, srv = sys.argv[1], sys.argv[2]
lk, sk = key(loc), key(srv)
if lk and sk:
    print(loc if lk > sk else f"{sk[0]}.{sk[1]}.{sk[2] + 1}")
elif lk:
    print(loc)
elif sk:
    print(f"{sk[0]}.{sk[1]}.{sk[2] + 1}")
else:
    print("1.0.0")
PY
)"
echo "[1/4] 生成精简副本（发布 v$VERSION｜本地 $LOCAL_VER · 线上 ${SRV_VER:-?}，排除依赖/敏感/dev 文件）…"
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
               "code_url": "https://openham.focus.beer/OpenHam-code.zip",
               "notes": "增量更新（仅代码）"}, f, ensure_ascii=False)
PY

echo "[3/4] 上传 完整包 + 代码包 + version.json + 下载页 + logo…"
# ECS 出公网链路不稳，scp 常中途掐断；每个文件按退出码多重试，避免发布只传一半。
SCPOPT="-i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=15 -o ServerAliveInterval=5"
put() {  # $1=本地文件  $2=远端文件名
  local i
  for i in $(seq 1 8); do
    if scp $SCPOPT "$1" "$ECS:$DL/$2"; then return 0; fi
    echo "    … $2 第 $i 次上传中断，重试"; sleep 3
  done
  echo "    ✗ $2 上传失败（链路反复中断）"; return 1
}
put "$ZIP" OpenHam-lite.zip
put "$CODEZIP" OpenHam-code.zip
put "$VJSON" version.json
put "$SRC/relay/download.html" index.html
put "$SRC/logo.png" logo.png

# 发布成功后：VERSION 末位 +1 写回，供下次发布自增。
# 注意：故意不改本机 $SRC/version.txt（安装标记），好让维护者用「检查更新」自测更新链路。
NEXT="$(echo "$VERSION" | awk -F. '{printf "%d.%d.%d", $1, $2, ($3+1)}')"
echo "$NEXT" > "$VERSION_FILE"
(cd "$SRC" && git add VERSION && git commit -q -m "chore(release): v$VERSION（下一版预置 v$NEXT）" 2>/dev/null) || true

echo "[4/4] 完成 ✅  版本 v$VERSION → https://openham.focus.beer/   （VERSION 已写回 $NEXT 备下次）"
