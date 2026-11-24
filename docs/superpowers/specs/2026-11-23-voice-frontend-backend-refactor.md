# 设计：lmam 语音前端与 rag_backend 前后端分离

日期：2026-11-23
状态：已实施

## 1. 背景

原 `lmam` 分支是 ROS 时代的博物馆讲解机器人语音本体：内置 langchain FAISS +
`museum.txt`，带 A 类导航指令（`/move_to`、`/NG`、`/manipulate`、`/leave`、`/start`）
和 `command_bus` 实机控制桩。SRS V1.1 面向灵山胜境景区数字人，问答由服务端 RAG/LLM
提供，语音端只负责采集与播报。

本次改造目标：

1. 前后端分离：问答统一走 `rag_backend` 的 `/api/public/ask/stream`（SSE）；
2. 删除 ROS/机器人控制残留与博物馆话术，业务语义对齐景区导览；
3. 保留 funasr KWS + faster-whisper + MeloTTS，并做可移植化（相对路径、CPU/GPU auto）；
4. 保留讲解 mp3 的打断/断点续播（对应 SRS UC-02 暂停/继续讲解）。

## 2. 目标数据流

```
[IDLE] KWS "小娟小娟" → 唤醒（暂停讲解 mp3）
[ACTIVE] ASR → 过滤 → RagClient.ask(text)
   POST /api/public/ask/stream {"area_id","q","session_id"}
   ← meta(citations) / delta(text) / done(answer,session_id,model,took_ms)
→ MeloTTS 播报 → 保持 ACTIVE 多轮；静默 idle_timeout_sec 回 IDLE
讲解 mp3：唤醒打断暂停 → 静默 auto_resume_silence_sec → 从断点续播
```

## 3. 模块变更

| 模块 | 变更 |
| --- | --- |
| `scripts/rag_client.py` | 新增：requests SSE 客户端；`RagAnswer` / `RagError`；session_id 复用/清洗；连接失败重试 1 次；超时/断流/error 事件统一抛错 |
| `lmam/app.py` | `assistant` → `rag`；`_handle_text` 直接问后端，按标点切句边收边播（`on_delta`），`done.answer` 补播尾部；唤醒/stop 可打断后续句子；失败播固定致歉语；新增 `text_ask()` 文本调试；删除 dispatch/指令解析/landmark |
| `scripts/config.py` | 相对路径按 config 目录解析；`resolve_device(auto)`；REQUIRED_KEYS/PATH_KEYS 更新 |
| `scripts/wakeup.py` | 删除硬编码模型路径；device auto；CUDA 失败回退 CPU |
| `scripts/local_listener.py` | `audioop` 兼容 3.13；faster-whisper cuda→cpu 重试；空 mic 名=系统默认；`__main__` argparse |
| `scripts/tts_local_player.py` | device auto；MeloTTS CUDA 失败回退 CPU |
| `main.py` | `--check` 增加后端 `/health` 探测；stdin 新增 `text <问题>` |
| `text_to_mp3/batch_text_to_mp3.py` | 参数化（COSYVOICE 路径/模型/参考音频/输入输出），加 `__main__` 守卫 |
| 删除 | `scripts/llm.py`、`command_bus.py`、`matcher.py`、`test_llm.py`、`prompts/`、`create_faiss_database_vector.py` 及对应测试 |

## 4. 后端接口契约（依赖 rag_backend 分支）

- `POST /api/public/ask/stream`，body `area_id`（`lingshan`）、`q`（≤500 字）、可选 `session_id`；
- SSE：`meta`（qa_id、session_id、citations）、`delta`（text）、`done`（answer、model、took_ms）、`error`（detail）；
- 无 `[DONE]` 哨兵，以 `done`/`error` 或 EOF 结束；
- `GET /health` 用于探活；
- 公共接口无鉴权；跨机部署 uvicorn 需 `--host 0.0.0.0`。

## 5. 降级与错误

- 连接失败（没连上）自动重试 1 次；已发出请求后的读超时不重试，避免后端重复记 `qa_log`；
- 后端不可达/超时/断流/error 事件：播报"抱歉，知识库服务暂时不可用，请稍后再试。"，主循环继续；
- 流式播报中若被唤醒/stop 打断，`_speak_cancel` 置位，后续句子不再送 TTS；
- 前端不再有 A/B/C 意图分类；闲聊与超范围问题也交给后端 LLM 兜底；
- CUDA 不可用：KWS/ASR/TTS 自动回退 CPU。

## 6. 与 SRS 的对应

| SRS | 本实现 |
| --- | --- |
| FE-1/FR-01 语音+文本交互 | 语音闭环 + `text` 调试输入（文本入口仅调试用） |
| FE-2/FR-02 RAG 问答、多轮 | 后端 `/ask/stream` + session_id 多轮 |
| FE-15 语音唤醒 | funasr KWS "小娟小娟" |
| SI-1 SSE 流式 | RagClient 消费 SSE，按 delta 累计 |
| PF-1 延迟 | 前端只做 ASR+TTS；按句边收边播降低首音延迟；后端 `took_ms` 与前端总耗时均记录日志 |
| UC-02 讲解暂停/继续 | audio_player 断点续播 |

未实现（属于交互端/后端其他模块）：数字人渲染与口型、路由规划、管理端、情感标签。

## 7. 测试策略

- 无模型/麦克风/后端：`python -m pytest tests/ -q`（42 用例）；
- `test_rag_client.py` 用 fake `requests` 响应验证 SSE 解析、error、断流、session 复用、500 字截断；
- `test_app.py` 用 `FakeRag` 验证问答播报、后端失败致歉、`text_ask` 状态切换、打断/续播回归；
- `test_config.py` 验证相对路径与 `resolve_device`。
