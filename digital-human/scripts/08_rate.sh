#!/usr/bin/env bash
# 检查当前下载速率（两次采样，间隔 30 秒）
set -uo pipefail
a=$(du -sc "$HOME"/.cache/uv/.tmp* 2>/dev/null | tail -1 | cut -f1); a=${a:-0}
sleep 30
b=$(du -sc "$HOME"/.cache/uv/.tmp* 2>/dev/null | tail -1 | cut -f1); b=${b:-0}
echo "tmp: $a KB -> $b KB"
echo "speed: $(( (b-a)/30/1024 )) MB/s"
pgrep -af "uv sync" | head -2
