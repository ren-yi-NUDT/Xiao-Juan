#!/usr/bin/env bash
# 当前默认启动方式：Mock 链路 + Light2D 分层形象
#
# 为什么是 mock：
#   新形象「讲解员小景（2D）」用 Light2D 在浏览器里画图层，不占 GPU；
#   LLM / 语音识别 / 声音 / 知识库全部照常工作，只是画面渲染不加载 Wav2Lip 权重。
#   显存从约 5.5 GB 降到约 1.6 GB，启动更快。
#
# 想切回神经口型：把 config/env.scenic 的 OPENTALKING_DEFAULT_MODEL 改回 wav2lip，
# 然后用 21_start_wav2lip.sh 启动（旧形象仍可用）。
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
REPO="${OPENTALKING_HOME:-$HOME/opentalking-workspace/opentalking}"
# 从脚本位置推导项目根目录；整个仓库挪位置后这里不用改
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/config/env.scenic"
LOG="$HOME/opentalking.log"

cd "$REPO" || exit 1
echo "== 启动 Mock + Light2D 2D 形象：$(date '+%H:%M:%S')"
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

echo "== /models 状态"
curl -s -m 5 http://127.0.0.1:8210/models; echo
echo "== WebUI: http://localhost:5173"
echo "== 日志: $LOG   （tail -f $LOG 跟踪）"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null || true
