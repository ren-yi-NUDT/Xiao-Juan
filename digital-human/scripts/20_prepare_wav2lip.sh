#!/usr/bin/env bash
# 阶段 2 前置：下载 Wav2Lip 权重（约 400 MB）
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
REPO="$HOME/opentalking-workspace/opentalking"
MODELS="$HOME/opentalking-workspace/models/wav2lip"

cd "$REPO" || exit 1
mkdir -p "$MODELS"

echo "== 下载 wav2lip384.pth"
uv run hf download Pypa/wav2lip384 wav2lip384.pth --local-dir "$MODELS"

echo "== 下载 s3fd.pth（人脸检测）"
uv run hf download rippertnt/wav2lip s3fd.pth --local-dir "$MODELS"

echo "== 结果"
ls -lh "$MODELS"
echo "== 权重目录: $MODELS （对应 OPENTALKING_WAV2LIP_MODEL_ROOT）"
