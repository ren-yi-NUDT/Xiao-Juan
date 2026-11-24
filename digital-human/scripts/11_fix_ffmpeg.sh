#!/usr/bin/env bash
# 把 ffmpeg 变成"任何调用方式都能找到"——给绕过 launcher 的场景兜底。
#
# 背景（2026-11-17 核对）：
#   正常用 scripts/start_unified.sh 启动时，start_opentalking.sh:161 会执行
#       export OPENTALKING_FFMPEG_BIN="$(quickstart_resolve_ffmpeg)"
#   解析顺序是：环境变量 → PATH 里的 ffmpeg → imageio_ffmpeg.get_ffmpeg_exe()
#   所以服务内 STT/TTS 用 ffmpeg 是没问题的。
#
#   但 providers/stt/dashscope/adapter.py::_ffmpeg_bin() 只读环境变量、不回退 imageio：
#       return os.environ.get("OPENTALKING_FFMPEG_BIN", "ffmpeg").strip() or "ffmpeg"
#   绕过 launcher 直接调适配器（自写脚本 / 单测 / CLI）时就会 FileNotFoundError。
#
# 本脚本做法：把 venv 内 imageio-ffmpeg 自带的静态二进制 chmod +x 后软链到 ~/.local/bin/ffmpeg。
# 启动脚本已把 ~/.local/bin 放在 PATH 最前面，所以两种场景都能用。
#
# 可反复执行；系统已有 ffmpeg 时直接退出。
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
REPO="${OPENTALKING_HOME:-$HOME/opentalking-workspace/opentalking}"

if command -v ffmpeg >/dev/null 2>&1; then
  echo "== ffmpeg 已可用：$(command -v ffmpeg)"
  ffmpeg -version 2>&1 | head -1
  exit 0
fi

echo "== PATH 内未找到 ffmpeg，改用 venv 里的 imageio-ffmpeg 二进制"
if [ ! -x "$REPO/.venv/bin/python" ]; then
  echo "!! 找不到 $REPO/.venv/bin/python，请先跑 03_sync.sh" >&2
  exit 1
fi

BIN="$("$REPO/.venv/bin/python" -c 'import imageio_ffmpeg,sys; sys.stdout.write(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null)"

if [ -z "${BIN:-}" ] || [ ! -f "$BIN" ]; then
  echo "!! 无法从 imageio-ffmpeg 取到二进制" >&2
  echo "   在 $REPO 下执行：uv sync --extra models（或 uv pip install imageio-ffmpeg）" >&2
  exit 1
fi

chmod +x "$BIN"
mkdir -p "$HOME/.local/bin"
ln -sf "$BIN" "$HOME/.local/bin/ffmpeg"

echo "== 已链接：$HOME/.local/bin/ffmpeg -> $BIN"
"$HOME/.local/bin/ffmpeg" -version 2>&1 | head -1
