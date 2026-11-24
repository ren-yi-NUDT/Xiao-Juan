#!/usr/bin/env bash
# 阶段 1：Mock 链路（不需要权重，验证 前端/API/LLM/TTS/WebRTC）
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
REPO="$HOME/opentalking-workspace/opentalking"
# 从脚本位置推导项目根目录；整个仓库挪位置后这里不用改
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/config/env.scenic"
LOG="$HOME/opentalking.log"

cd "$REPO" || exit 1
echo "== 启动 Mock：$(date '+%H:%M:%S')"
setsid nohup bash scripts/start_unified.sh --mock --env "$ENV_FILE" \
  --api-port 8210 --web-port 5173 --host 0.0.0.0 \
  > "$LOG" 2>&1 < /dev/null &

for i in $(seq 1 60); do
  sleep 3
  if curl -s -m 2 http://127.0.0.1:8210/health >/dev/null 2>&1; then
    echo "== API 就绪（约 $((i*3))s）"
    break
  fi
done

curl -s -m 3 http://127.0.0.1:8210/health; echo
curl -s -m 3 http://127.0.0.1:8210/models; echo
echo "== WebUI: http://localhost:5173"
echo "== 日志: $LOG   （tail -f $LOG 跟踪）"
