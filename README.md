# 小娟 — 灵山景区数字人语音前端（本机 / 跨机）

语音前端负责 **唤醒 → ASR → 问答 → TTS** 的本机闭环；知识库检索与大模型回答由
`rag_backend`（FastAPI）通过 HTTP/SSE 提供，可部署在本机或另一台机器。
回答按标点切句、边收边播（降低首音延迟）；讲解 mp3 在本机播放，支持唤醒打断、静默后从断点续播。

对应 SRS：FE-1/FR-01（语音交互）、FE-2/FR-02（RAG 问答、多轮）、FE-15（语音唤醒）、
SI-1（SSE 流式回答）、PF-1（端到端延迟）。不含导航/机械臂等实机控制。

## 本仓库内容

| 目录 | 内容 | 说明 |
| --- | --- | --- |
| 根目录 / `lmam/` / `scripts/` / `tests/` | 小卷机器人主程序 | 原有内容 |
| `rag_backend/` | 独立 RAG 后端（FastAPI + SQLite） | 在 `rag_backend` 分支 |
| [`digital-human/`](digital-human/README.md) | 景区讲解数字人（OpenTalking + Wav2Lip） | 本地部署工作台，含 27 篇灵山胜境讲解词、人设包与一键重建脚本 |

`digital-human/` 有独立的 README 和操作手册，路径自包含；API Key 等本地配置不会入库。

## 目录结构

    main.py                  入口（--check 自检；stdin 调试 CLI）
    config.yaml              全部可调配置（模型/设备/后端地址/提示语）
    lmam/app.py              主应用：状态机 + mic 线程 + ASR→问答→TTS 消费线程
    scripts/
      config.py              配置加载（相对路径解析、device=auto）
      rag_client.py          问答后端客户端（/api/public/ask/stream，SSE）
      audio_player.py        讲解 mp3 播放（pygame，打断/断点续播）
      tts_local_player.py    MeloTTS 合成 + sounddevice 本机播放
      local_listener.py      麦克风 ASR（faster-whisper）
      wakeup.py              KWS 唤醒（funasr，"小娟小娟"）+ 状态机
    text_to_mp3/             讲解音频生成工具（CosyVoice2，可选）
    tests/                   pytest 单测（无模型/麦克风也能跑）

## 部署形态

```
┌────────────── 语音前端（本机） ──────────────┐        ┌──── rag_backend（本机/跨机） ────┐
│ 麦克风 → KWS 唤醒 → faster-whisper ASR       │  HTTP  │ FastAPI + SQLite                 │
│        → RagClient ──────────────────────────┼───────→│ /api/public/ask/stream (SSE)      │
│        ← 回答文本 ←───────────────────────────┼───────│ 灵山胜境知识库 + LLM（可选）      │
│ MeloTTS → 本机扬声器；讲解 mp3 播放/续播       │        └──────────────────────────────────┘
└───────────────────────────────────────────────┘
```

### 1. 启动问答后端（另一终端）

```bash
cd rag_backend            # 该目录在 rag_backend 分支上
python scripts/seed.py    # 首次导入（已有 data/xiaojuan.db 则跳过）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

- 跨机访问必须 `--host 0.0.0.0`，并放通防火墙 8765；
- 公共接口无需鉴权，仅限内网使用；
- 未配置 `llm.api_base/model` 时返回抽取式答案；配置云模型见 `rag_backend/config.yaml` 注释。

### 2. 启动语音前端（本机）

```bash
pip install -r requirements.txt
pip install git+https://github.com/myshell-ai/MeloTTS.git   # MeloTTS 无 PyPI 包
python main.py --check      # 配置 + 导入 + 后端可达性
python main.py              # 真机运行；说"小娟小娟"唤醒
```

模型放 `models/` 下（相对路径按本文件目录解析），也可填绝对路径：

    models/speech_charctc_kws_phone-xiaoyun/
    models/faster-whisper-large-v3/
    models/melo/ZH/{config.json,checkpoint.pth}

`kws_device / asr_device / tts_device` 支持 `auto|cpu|cuda`；CUDA 初始化失败会自动回退 CPU。
Python 3.13 下 `audioop` 缺失，会自动使用 `audioop-lts`（requirements 已按版本声明）。

## 配置要点（config.yaml）

| 键 | 说明 |
| --- | --- |
| `rag_api_base` | 后端地址；跨机改为 `http://<后端IP>:8765` |
| `rag_area_id` | 景区 id：`lingshan`（灵山胜境）/ `nianhuawan`（拈花湾） |
| `rag_timeout_sec` | 单次问答读超时，默认 15s |
| `rag_session_id` | 空 = 启动时生成，运行期复用（多轮上下文在后端） |
| `mic_device_name` | 空 = 系统默认输入；也可填设备名关键字 |
| `auto_resume_silence_sec` | 唤醒打断讲解后，静默多久自动续播 |
| `idle_timeout_sec` | ACTIVE 静默超时回 IDLE |

## 调试 CLI（stdin）

    text 灵山大佛有多高      # 无麦克风：走 后端问答 → TTS 完整链路，并打印回答
    audio_start <mp3路径>    # 播放讲解；唤醒可打断，静默后自动续播
    stop                     # 打断全部播放
    quit                     # 退出

## 测试

```bash
python -m pytest tests/ -q     # 42 个用例；临时依赖由 conftest 打桩
```

## 单独验证问答后端（无需模型/麦克风）

```bash
python -m scripts.rag_client --health
python -m scripts.rag_client --ask "灵山大佛有多高" --ask "九龙灌浴几点开始"
# 跨机：--base http://<后端IP>:8765
```

覆盖：RAG SSE 解析/异常、状态机与打断续播、配置路径与设备解析、音频播放/TTS 播放器。

## 常见问题

- **`--check` 提示后端不可达**：确认后端已启动、`rag_api_base` 正确、跨机时 `--host 0.0.0.0`。
- **backend 未配置 LLM**：仍可问答（抽取式答案），但多轮/口语化效果有限。
- **MeloTTS 安装失败**：按官方 README 先装系统依赖（phonemizer/espeak 等），再 `pip install git+...`。
- **无 GPU**：把三个 `*_device` 设为 `auto` 或 `cpu` 即可，首次加载会慢一些。
