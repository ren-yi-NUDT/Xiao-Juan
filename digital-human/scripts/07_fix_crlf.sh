#!/usr/bin/env bash
# 把 config/ 与 scripts/ 下的文本文件统一转成 LF（Windows 编辑器容易写成 CRLF）
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for f in "$ROOT"/config/* "$ROOT"/scripts/*.sh; do
  [ -f "$f" ] || continue
  if grep -q $'\r' "$f"; then
    sed -i 's/\r$//' "$f"
    echo "fixed: $f"
  fi
done
echo "== done"
