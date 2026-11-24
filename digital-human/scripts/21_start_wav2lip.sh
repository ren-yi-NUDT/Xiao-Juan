#!/usr/bin/env bash
# 阶段 2：Wav2Lip 真实渲染（8 GB 显存可用）
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
REPO="$HOME/opentalking-workspace/opentalking"
# 从脚本位置推导项目根目录；整个仓库挪位置后这里不用改
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/config/env.scenic"
LOG="$HOME/opentalking.log"

cd "$REPO" || exit 1
echo "== 启动 Wav2Lip local：$(date '+%H:%M:%S')"
setsid nohup bash scripts/start_unified.sh --backend local --model wav2lip --env "$ENV_FILE" \
  --api-port 8210 --web-port 5173 --host 0.0.0.0 \
  > "$LOG" 2>&1 < /dev/null &

for i in $(seq 1 100); do
  sleep 3
  if curl -s -m 2 http://127.0.0.1:8210/health >/dev/null 2>&1; then
    echo "== API 就绪（约 $((i*3))s）"
    break
  fi
done

echo "== /models 状态"
curl -s -m 5 http://127.0.0.1:8210/models; echo
echo "== WebUI: http://localhost:5173"
echo "== 日志: $LOG"
echo "== 显存"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
