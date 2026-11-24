#!/usr/bin/env bash
# 对比 PyPI 镜像下载速度（下载 50 MB 后断开）
for m in "https://pypi.tuna.tsinghua.edu.cn/simple/torch/" "https://mirrors.aliyun.com/pypi/simple/torch/" "https://mirrors.ustc.edu.cn/pypi/simple/torch/"; do
  echo "== $m"
  curl -s -o /dev/null -m 30 -w "  speed: %{speed_download} B/s  http: %{http_code}\n" "$m"
done
