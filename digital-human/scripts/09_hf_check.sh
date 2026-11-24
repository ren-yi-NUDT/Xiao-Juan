#!/usr/bin/env bash
# 检查 HF 镜像可达性（权重是否可以下载）
for h in https://hf-mirror.com https://huggingface.co; do
  echo "== $h"
  curl -s -m 15 -o /dev/null -w "  api/models status=%{http_code}\n" "$h/api/models/Pypa/wav2lip384"
done
echo "== 镜像返回的文件列表"
curl -s -m 15 "https://hf-mirror.com/api/models/Pypa/wav2lip384" | head -c 400
echo
curl -s -m 15 "https://hf-mirror.com/api/models/rippertnt/wav2lip" | head -c 400
echo
