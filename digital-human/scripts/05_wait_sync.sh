#!/usr/bin/env bash
# 等待依赖装完（最多 N 秒），每 20 秒打印一次进度
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
MAX="${1:-240}"
REPO="$HOME/opentalking-workspace/opentalking"
WAITED=0

while [ "$WAITED" -lt "$MAX" ]; do
  if [ -x "$REPO/.venv/bin/python" ] && "$REPO/.venv/bin/python" -c "import torch" >/dev/null 2>&1; then
    echo "== torch 已就绪（等待 $WAITED s）"
    break
  fi
  if ! pgrep -f "uv sync" >/dev/null 2>&1; then
    echo "== uv sync 进程已退出（等待 $WAITED s），检查结果"
    break
  fi
  TMP=$(du -sc "$HOME"/.cache/uv/.tmp* 2>/dev/null | tail -1 | cut -f1)
  VENV=$(du -sh "$REPO/.venv" 2>/dev/null | cut -f1)
  echo "[$WAITED s] 临时下载 ${TMP:-0} KB / .venv ${VENV:-0}"
  sleep 20
  WAITED=$((WAITED + 20))
done

echo "== 最终状态"
du -sh "$REPO/.venv" 2>/dev/null
"$REPO/.venv/bin/python" -c "import torch; print('torch', torch.__version__, '| cuda', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no-gpu')" 2>&1 | tail -3
