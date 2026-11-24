#!/usr/bin/env bash
# 重建「灵山胜境」知识库并等索引完成，最后跑 4 条验收提问。
#
# 什么时候用：
#   * 首次导入（knowledge/灵山胜境/*.md 已存在）
#   * 索引失败后重试（例如 DashScope 欠费充值后、批量参数调整后）
#
# 前置条件：
#   * 服务已启动：scripts/21_start_wav2lip.sh
#   * config/env.scenic 里 OPENTALKING_KNOWLEDGE_EMBEDDING_BATCH_SIZE=8
#     （DashScope text-embedding-v4 单请求上限 10 条）
#   * Key 有余额（欠费时 chat/embedding 都返回 Arrearage）
set -uo pipefail

API="${OPENTALKING_API:-http://127.0.0.1:8210}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${1:-$PROJECT_DIR/knowledge/灵山胜境}"
KB_NAME="灵山胜境"

if [ ! -d "$DIR" ]; then
  echo "!! 找不到知识库目录：$DIR" >&2
  exit 1
fi

FILE_COUNT=$(find "$DIR" -maxdepth 1 -name '*.md' | wc -l)
echo "== 本地 md 文件：$FILE_COUNT 个（$DIR）"

echo
echo "== 1) 服务健康检查"
if ! curl -s -m 10 "$API/health" >/dev/null; then
  echo "!! API 未就绪，先跑 scripts/21_start_wav2lip.sh" >&2
  exit 1
fi
curl -s -m 10 "$API/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   status=%s llm_key_set=%s stt=%s" % (d.get("status"), d.get("llm_key_set"), d.get("stt_default_provider")))'

echo
echo "== 2) 删除同名旧库（若有）"
python3 - "$API" "$KB_NAME" <<'PY'
import json, sys, urllib.request
api, name = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(api + "/agent/knowledge-bases", timeout=30) as r:
    data = json.load(r)
for kb in data.get("knowledge_base_summaries", []):
    if kb.get("name") == name:
        req = urllib.request.Request(api + "/agent/knowledge-bases/" + kb["id"], method="DELETE")
        with urllib.request.urlopen(req, timeout=60) as rr:
            print("   已删除", kb["id"], rr.read().decode()[:80])
PY

echo
echo "== 3) 建库并上传"
ARGS=()
while IFS= read -r f; do ARGS+=(-F "files=@$f"); done < <(find "$DIR" -maxdepth 1 -name '*.md' | sort)
RESP=$(curl -s -m 900 -X POST "$API/agent/knowledge-bases" -F "name=$KB_NAME" "${ARGS[@]}")
KB=$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null)
if [ -z "$KB" ]; then
  echo "!! 建库失败：$RESP" >&2
  exit 1
fi
echo "   KB_ID=$KB"

echo
echo "== 4) 等待索引（每 20s 检查一次，最多约 20 分钟）"
DONE=0
for i in $(seq 1 60); do
  sleep 20
  LINE=$(python3 - "$API" "$KB" <<'PY'
import json, sys, urllib.request, urllib.error
api, kb_id = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(api + "/agent/knowledge-bases", timeout=30) as r:
        data = json.load(r)
except Exception as e:
    print("list_error", e); raise SystemExit
item = next((x for x in data.get("knowledge_base_summaries", []) if x.get("id") == kb_id), None)
if not item:
    print("gone"); raise SystemExit
body = json.dumps({"query": "迎客松", "limit": 1}).encode()
req = urllib.request.Request(api + f"/agent/knowledge-bases/{kb_id}/lightrag/query", data=body,
                             headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=90) as r:
        q = json.load(r)
    idx, reason = q.get("indexed"), q.get("reason") or ""
except Exception as e:
    idx, reason = None, str(e)[:60]
print("docs=%s ready=%s error=%s indexed=%s reason=%s" % (
    item.get("document_count"), item.get("ready_document_count"),
    item.get("error_document_count"), idx, reason))
PY
)
  echo "   [$((i*20))s] $LINE"
  case "$LINE" in
    *"indexed=True"*) DONE=1; break ;;
  esac
  case "$LINE" in
    *"reason=index_failed"*)
      # 前 3 分钟可能只是还在跑，之后仍失败就报错退出
      if [ "$i" -ge 9 ]; then
        echo "!! 索引持续失败。查因："
        echo "   grep -n Arrearage ~/logs/opentalking-api-8210.log | tail -3"
        echo "   python3 - <<'P'"
        echo "   import json,pathlib,collections"
        echo "   p=pathlib.Path('/home/hw/opentalking-workspace/opentalking/data/knowledge/_lightrag/$KB/kv_store_doc_status.json')"
        echo "   d=json.loads(p.read_text(encoding='utf-8'))"
        echo "   print(collections.Counter(v.get('status') for v in d.values()))"
        echo "   print(str(next(iter(d.values())).get('error_msg'))[:400])"
        echo "   P"
        exit 2
      fi ;;
  esac
done

if [ "$DONE" != "1" ]; then
  echo "!! 超时未完成，请按上面提示检查日志" >&2
  exit 3
fi

echo
echo "== 5) 验收提问"
ask() {
  echo
  echo "--- 问：$1"
  python3 - "$API" "$KB" "$1" <<'PY'
import json, sys, urllib.request
api, kb_id, q = sys.argv[1], sys.argv[2], sys.argv[3]
body = json.dumps({"query": q, "limit": 3}).encode()
req = urllib.request.Request(api + f"/agent/knowledge-bases/{kb_id}/lightrag/query", data=body,
                             headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=120) as r:
    d = json.load(r)
print("   available=%s indexed=%s reason=%r" % (d.get("available"), d.get("indexed"), d.get("reason")))
for i, res in enumerate(d.get("results", [])[:2], 1):
    text = " ".join(res.get("text", "").split())
    print(f"   [{i}] {text[:200]}")
PY
}

ask "灵山大佛有多高？用了多少吨铜？"
ask "九龙灌浴每天几点表演，一场多久？"
ask "带小孩玩三个小时怎么走？"
ask "门票多少钱，老人有优惠吗？"

echo
echo "== 完成。KB_ID=$KB"
echo "   在 WebUI 的会话设置里把这个知识库勾上即可生效。"
