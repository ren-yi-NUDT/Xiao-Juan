#!/usr/bin/env bash
# 前台安装/续传依赖（中断后重复执行即可，uv 会用本地缓存续传）
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
REPO="$HOME/opentalking-workspace/opentalking"
cd "$REPO" || exit 1
echo "== cwd: $(pwd)  $(date '+%H:%M:%S')"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11.9
echo "== uv sync 退出码: $?  $(date '+%H:%M:%S')"
