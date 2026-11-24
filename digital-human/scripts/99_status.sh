#!/usr/bin/env bash
# 状态检查：依赖安装进度 / 服务健康 / GPU
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
REPO="${OPENTALKING_HOME:-$HOME/opentalking-workspace/opentalking}"

echo "=== uv sync 日志尾部 ==="
tail -n 12 "$HOME/uv_sync.log" 2>/dev/null || echo "(无日志)"

echo
echo "=== 进程 ==="
pgrep -af "uv sync" || echo "uv sync 未在运行"
pgrep -af "start_unified|opentalking" | head -5 || true

echo
echo "=== .venv ==="
if [ -x "$REPO/.venv/bin/python" ]; then
  du -sh "$REPO/.venv" 2>/dev/null
  "$REPO/.venv/bin/python" -c "import sys; print('python', sys.version.split()[0])" 2>/dev/null
  "$REPO/.venv/bin/python" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')" 2>/dev/null || echo "torch 尚未安装完成"
else
  echo ".venv 尚未创建"
fi

echo
echo "=== 服务健康 ==="
curl -s -m 3 http://127.0.0.1:8210/health || echo "API(8210) 未响应"
echo
curl -s -m 3 -o /dev/null -w "web(5173) http_code=%{http_code}\n" http://127.0.0.1:5173/ || echo "Web(5173) 未响应"

echo
echo "=== GPU ==="
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
