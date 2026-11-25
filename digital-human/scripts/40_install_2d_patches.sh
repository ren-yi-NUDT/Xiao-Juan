#!/usr/bin/env bash
# 一键安装 2D 形象改造补丁到 OpenTalking 仓库
# 用法：新组员 / 新机器首次配置时跑一次
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${OPENTALKING_HOME:-$HOME/opentalking-workspace/opentalking}"
PATCH_SRC="$PROJECT_DIR/patches/opentalking"
AVATAR_SRC="$PROJECT_DIR/素材/layers"
AVATAR_ROOT="$REPO/examples/avatars/lingshan-guide-2d"
AVATAR_DST="$AVATAR_ROOT/light2d/layers"
CFG_SRC="$PROJECT_DIR/config/avatar-2d"

if [ ! -d "$REPO" ]; then
  echo "!! 找不到 OpenTalking 仓库：$REPO" >&2
  exit 1
fi

echo "== 1) 覆盖 6 个源码补丁 =="
cp -r "$PATCH_SRC/." "$REPO/"
echo "   完成：$(find "$PATCH_SRC" -type f | wc -l) 个文件"

echo
echo "== 2) 安装形象配置与 27 张图层 =="
mkdir -p "$AVATAR_DST"
cp "$CFG_SRC/manifest.json" "$AVATAR_ROOT/manifest.json"
cp "$CFG_SRC/avatar.json" "$AVATAR_ROOT/light2d/avatar.json"
cp "$CFG_SRC/preview.png" "$AVATAR_ROOT/preview.png"
cp "$CFG_SRC/reference.png" "$AVATAR_ROOT/reference.png"
cp "$AVATAR_SRC"/*.png "$AVATAR_DST/"
echo "   完成：$(find "$AVATAR_DST" -name '*.png' | wc -l) 张图层 + 配置 4 件"

echo
echo "== 3) 重新构建前端 =="
cd "$REPO/apps/web" || exit 1
npm test >/dev/null 2>&1 && echo "   单测通过" || echo "   ⚠ 单测未全过（请手动 npm test 查看）"
npx tsc --noEmit -p tsconfig.json >/dev/null 2>&1 && echo "   类型检查通过" || echo "   ⚠ 类型检查失败"
npm run build 2>&1 | tail -3

echo
echo "== 4) 完成。重启服务后生效：=="
echo "   wsl -d Ubuntu -- bash \"$PROJECT_DIR/scripts/98_stop_all.sh\""
echo "   wsl -d Ubuntu -- bash \"$PROJECT_DIR/scripts/00_start.sh\""
echo
echo "   形象目录：$AVATAR_ROOT"
