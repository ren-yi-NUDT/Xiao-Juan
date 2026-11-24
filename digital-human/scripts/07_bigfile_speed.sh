#!/usr/bin/env bash
# 取一个真实的大 wheel，比较两个镜像上的实际下载速度（各下 30 MB）
IDX_ALI="https://mirrors.aliyun.com/pypi/simple/torch/"
IDX_TUNA="https://pypi.tuna.tsinghua.edu.cn/simple/torch/"

href_from() {
  curl -s "$1" | grep -o 'href="[^"]*cp311[^"]*manylinux[^"]*x86_64.whl' | head -1 | cut -d'"' -f2
}

A=$(href_from "$IDX_ALI")
echo "wheel path: $A"

if [ -n "$A" ]; then
  case "$A" in
    http*) ;;
    *) A_PATH="$A" ;;
  esac
  echo "== aliyun"
  curl -s -r 0-31457280 -o /dev/null -m 60 -w "  %{speed_download} B/s\n" "https://mirrors.aliyun.com${A_PATH}"
  echo "== tuna"
  curl -s -r 0-31457280 -o /dev/null -m 60 -w "  %{speed_download} B/s\n" "https://pypi.tuna.tsinghua.edu.cn${A_PATH}"
fi
