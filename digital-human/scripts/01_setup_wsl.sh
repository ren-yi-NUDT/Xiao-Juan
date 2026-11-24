#!/usr/bin/env bash
# OpenTalking 景区讲解数字人 —— WSL2 环境初始化（在 WSL Ubuntu 内执行）
# 用法: wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/01_setup_wsl.sh
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

WORK_ROOT="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
REPO="$WORK_ROOT/opentalking"
PYVER="${PYVER:-3.11.9}"

echo "==> 工作根目录: $WORK_ROOT"

# 1) uv
if ! command -v uv >/dev/null 2>&1; then
  echo "==> 安装 uv 到 ~/.local/bin"
  mkdir -p "$HOME/.local/bin"
  curl -LsSf https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz -o /tmp/uv.tar.gz
  tar -xzf /tmp/uv.tar.gz -C /tmp
  cp /tmp/uv-x86_64-unknown-linux-gnu/uv "$HOME/.local/bin/uv"
fi
echo "==> uv: $(uv --version)"

# 2) 源码
if [ ! -d "$REPO/.git" ]; then
  echo "==> 克隆 OpenTalking"
  mkdir -p "$WORK_ROOT"
  git clone --depth 1 https://github.com/datascale-ai/opentalking.git "$REPO"
fi
cd "$REPO"

# 3) 上游 requires-python >=3.10 会让 uv 在 3.10 分支上解析失败（onnxruntime-gpu 需 >=3.11）
sed -i 's/requires-python = ">=3.10"/requires-python = ">=3.11"/' pyproject.toml
grep -n 'requires-python' pyproject.toml

# 4) 后台安装依赖（含 torch + onnxruntime-gpu，下载量约 5-8 GB）
rm -rf .venv
setsid nohup uv sync --extra dev --extra models --extra quicktalk-cuda --python "$PYVER" \
  > "$HOME/uv_sync.log" 2>&1 < /dev/null &
echo "==> uv sync 已在后台启动，日志: $HOME/uv_sync.log"
echo "==> 查看进度: wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/99_status.sh"
