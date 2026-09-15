# 设计文档：lmam 脱离 ROS2 的本地纯 Python 改造

日期：2026-09-15
状态：已与需求方确认
分支策略：在 `local` 分支开发，完成后合并回 `lmam`

## 1. 背景与目标

`lmam` 原是 ROS2 包（ament_cmake + rclpy），作为博物馆讲解机器人的语音交互前端，
通过 ROS 话题/动作与 agent（导航/任务规划）和 Orin 音频板通信。

目标：**脱离 ROS 环境，所有工作在一台本机完成**：
- 唤醒 → ASR → LLM → TTS 的语音闭环在本机完整可跑
- 音频（TTS 播报、mp3 讲解）在本机扬声器播放，不再推流 Orin
- 实机控制逻辑（move_to / NG / manipulate / leave / start）**置空留桩**，之后重写
- 唤醒词改为 **"小娟小娟"**

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 对外通信 | 全部移除，不远程连接 Orin；控制指令置空留桩 |
| 实机控制逻辑 | 删除业务分支，`dispatch()` 留桩 + 日志 TODO |
| 缺失模块 | `NG_config.py` 不再创建（对应逻辑已删）；`prompts/chat_exec.py` 创建功能完整的占位版本 |
| 唤醒词 | "小娟小娟"（FunASR CTC-KWS 的 keywords 是运行时参数，模型不变） |
| 方案取舍 | 方案 A 轻量重排：保业务行为，换通信/音频/配置外壳 |

## 3. 目标目录结构

```
lmam/                            # 仓库根 = 项目根
├── main.py                      # 入口：python main.py [--check]
├── config.yaml                  # 全部可调配置
├── requirements.txt             # Python 依赖
├── README.md                    # 更新为本地运行说明
├── docs/superpowers/specs/      # 本设计文档
├── lmam/
│   └── app.py                   # ← lmam_node/lmam_node.py 去掉 ROS 外壳
├── scripts/
│   ├── __init__.py
│   ├── config.py                # 配置加载（读 config.yaml）
│   ├── command_bus.py           # 极简 dispatch 桩
│   ├── llm.py                   # 路径/API 改从 config 读
│   ├── local_listener.py        # 麦克风设备名可配置
│   ├── wakeup.py                # KWS 模型路径/唤醒词可配置
│   ├── tts_local_player.py      # ← tts_ws_streamer.py：melo 生成 + 本机播放
│   ├── audio_player.py          # 新增：pygame mp3 播放（start/pause/resume/stop/interrupt）
│   ├── matcher.py               # 不动（重写控制层时可能复用）
│   └── test_llm.py              # 不动
├── prompts/
│   ├── __init__.py
│   ├── chat.py                  # 不动
│   └── chat_exec.py             # 占位：llm.py 导入的 7 个 prompt 常量，功能完整
├── text_to_mp3/                 # 不动
└── tests/                       # pytest 单测
```

删除：`package.xml`、`CMakeLists.txt`、`action/`、`lmam_node/`（改造后）、`scripts/tts_ws_streamer.py`（改造后）。

导入方式统一为包导入（`from scripts.llm import ...`），删除 lmam_node.py 头部 ~50 行
ament_index/sys.path hack。种子化 `#!` shebang 行删除。

## 4. 核心语音闭环（保持的行为）

```
IDLE:  KWS 监听"小娟小娟"(0.2s 粒度 PCM 喂入)
       命中 → 防抖(2s) → 打断当前播放 → 播"您好，我在。" → ACTIVE
ACTIVE: ASR 聆听(单句≤10s) → 文本过滤 → LLM 对话 → TTS 本机播报
        静默超过 IDLE_TIMEOUT(10s) → 播回 IDLE 提示语 → IDLE
会话保持：唤醒一次后 15s 内免重复唤醒（SESSION_HOLD_SEC，保留字段）
自动续播：唤醒打断 mp3 讲解 → guide_paused=True → 静默 0.5s 后
         播"我继续为您讲解" → 从断点续播（仅 IDLE 时）
```

状态机 `SharedState` / 防抖 `ClientControlState`（`wakeup.py`）原样保留。

## 5. 模块设计

### 5.1 lmam/app.py（原 lmam_node.py）

`LMAMApp` 类，删除的 ROS 依赖与替代：

| 原 ROS 机制 | 本地替代 |
|---|---|
| `Base`(rclpy Node) + `get_logger()` | 标准 `logging`，main.py 统一配置 |
| `create_publisher(StateMsg)` 发指令 | `dispatch(command)` 桩（见 5.2） |
| Command action server（agent 下发） | 迷你调试 CLI（见 5.4） |
| 订阅 `/audio_done`、`/tts_playing` | 本地播放器直接驱动状态，无需外部反馈 |
| 订阅 `/agent_info`（current_landmark） | 删除（随实机控制逻辑置空） |
| `ActionClient(audio_control)` → Orin | `audio_player.py` 本地调用（见 5.3） |
| `create_timer` 状态发布 30Hz | 删除（`state_pub` 本来就是空实现） |
| `create_timer` 5Hz 续播检查 | 并入消费线程轮询（`queue.get(timeout=0.2)`） |
| WS 服务器 + asyncio loop | 整体删除，换普通线程 + `queue.Queue` |

线程模型（3 个用户线程 + 主线程）：
- **mic 线程**（原样）：IDLE 做 KWS、ACTIVE 做 ASR，产出文本入 `queue.Queue`
- **消费线程**（原 asr_text_consumer 的线程版）：串行 取文本 → 过滤 → LLM → 播 TTS。
  LLM 调用和 TTS 播放在此线程阻塞执行，与原 await 串行语义一致
- **续播检查**：并入消费线程循环（每 0.2s 轮询一次），不再单独 timer

删除的业务逻辑（实机控制，之后重写）：
- `start_flag` 确认开馆块（识别"是否可以开始今天的展览"+发 `start`）
- NG 展区分支（Landmark2 + `NG_LANDMARK_CONFIG`/`NG_TTS_CONFIG`/`NG_TTS_TXT`）
- 麒麟抓取分支（Landmark4/Grasp1/Return1 + `QILIN_TTS_CONFIG`）
- `leave` 自动发送（unvisited 为空时）、`visited_landmarks` 簿记
- `landmark_to_name` 8 个 'xxxx' 映射 → 移入 config（留空占位）
- ASR 过滤词列表（"志愿者"、"杨茜茜"等）→ 移入 config 可配置

`unvisited_landmarks` 恒为 `None`：`move_to` 分支简化为
`dispatch(command)`（日志 TODO）+ 正常 TTS 播报 LLM 回复，不做 visited 校验。

### 5.2 scripts/command_bus.py（桩）

```python
def dispatch(command: dict) -> None:
    """实机控制指令出口。当前为桩：仅日志。
    TODO: 之后在此挂接新的控制层实现。"""
    log.info("[STUB] 实机控制指令: %s (待重写)", command)
```

### 5.3 scripts/audio_player.py + tts_local_player.py

**audio_player.py**（替代 Orin 的 audio_control action）：
`pygame.mixer.music` 实现，接口对齐原 5 个命令：
- `start(path)`：载入播放，`audio_playing=True`
- `pause()` / `resume()`（断点语义由 mixer.music 原生支持）/ `stop()` / `interrupt()`
- 后台轮询 `get_busy()`，自然播完 → 回调 `on_finished(status)`（finished/interrupted），
  等价原 `/audio_done` 消息 → `audio_playing=False`、`guide_paused=False`
- `auto_resume()`：从 `pause()` 位置 `play(start=pos)` 续播

**tts_local_player.py**（原 tts_ws_streamer.py）：
- 保留 melo `TTS` 生成 wav bytes 的逻辑
- 推流循环 → `sounddevice.play(wav, sr)` + 等待播放结束（阻塞式 `speak(text)`，
  播完才返回，与原 await 语义一致）；提供 `stop()` 供唤醒打断
- 播放前后驱动 `SharedState.set_tts_playing()`

### 5.4 调试 CLI（main.py 内，约 20 行）

后台线程读 stdin，仅 3 个命令（仅为本机验证音频体验，非 agent 模拟）：
- `audio_start <mp3路径>`：开始讲解播放（等价原 agent 的 audio_start 命令）
- `stop`：打断全部音频
- `quit`：优雅退出

### 5.5 prompts/chat_exec.py（占位）

功能完整的 7 个常量（非空壳，代码拿来即可跑）：
- `SYSTEM_PROMPT0`：意图分类 A(指令)/B(知识库)/C(闲聊)，单字母输出
- `SYSTEM_PROMPT1`：指令生成，严格两行格式（回复\n/指令），指令限定
  `llm.py is_valid_command` 白名单（/move_to Landmark1-8、/start、/resume、/leave、/NG、/manipulate）
- `SYSTEM_PROMPT3`：闲聊（可参考现有 chat.py 的 SYSTEM_PROMPT 风格）
- `SYSTEM_PROMPT4`：非法指令重生成
- `SYSTEM_PROMPT_DATABASE` + `USER_PROMPT_DATABASE`（含 `{sentences}/{paragraphs}/{user_question}` 占位符）
- `SYSTEM_PROMPT_LANDMARK_NAV`

需求方之后从机器人拷回真实 prompt 覆盖此文件。

## 6. 配置（config.yaml）

```yaml
wake_word: "小娟小娟"
kws_model_path: "模型路径"
kws_rms_gate: 0.01
asr_model_path: "whisper 模型路径"
asr_device: "cuda"          # 无 GPU 改 cpu
tts_config_path / tts_ckpt_path / tts_device / tts_speed
embed_model_path / museum_txt_path / vector_db_path
llm_api_base: "http://192.168.3.11:8088/v1"
mic_device_name: "Wireless microphone"
session_hold_sec: 15.0
auto_resume_silence_sec: 0.5
resume_check_period: 0.2
idle_timeout_sec: 10.0
back_to_idle_prompt: "如果您有任何问题请呼唤两声小娟唤醒我哦。"
wakeup_prompt: "您好，我在。"
asr_filter_words: [...]
landmark_to_name: { Landmark1: "", ... }   # 留空占位
audio:
  sample_rate: 22050
  chunk_size: 65536
```

`scripts/config.py`：读 `config.yaml` → 冻结的 `Config` 对象，路径不存在时启动即报错
（`--check` 模式除外）。

## 7. 依赖（requirements.txt）

openai, torch, faster-whisper, funasr, pyaudio, SpeechRecognition, sounddevice,
numpy, pyyaml, pygame, cn2an, rapidfuzz, langchain-community, langchain-huggingface,
faiss-cpu, melo-tts（git 依赖，README 注明安装方式）

## 8. 测试策略

本机无麦克风/GPU/模型文件，全链路真机验证由需求方执行。
- **pytest 单测**（纯逻辑，可在此机器跑）：
  - `matcher.ExhibitIntentMatcher`（命中/排除词/阈值）
  - `llm.parse_command / parse_llm_result / is_valid_command`
  - `command_bus.dispatch` 桩
  - `prompts.chat_exec` 导入与 `USER_PROMPT_DATABASE.format()` 占位符完整性
  - `config.py` 加载与缺路径报错
- **`main.py --check`**：仅验证配置加载 + 全模块导入，不加载模型不开音频
- README 写真机运行步骤（模型下载位置、CUDA 环境、安装顺序）

## 9. 非目标（明确不做）

- 不实现任何实机控制（move_to/NG/manipulate/leave/start → dispatch 桩）
- 不做与 agent 的任何通信协议（之后重写时再设计）
- 不移植 `NG_config.py`（对应业务已删）
- 不保留 WebSocket 推流路径
- 不改 `text_to_mp3/` 工具
