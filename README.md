# LMAM — 博物馆讲解机器人语音交互（本地版）

大语言模型 + 音频模块：唤醒 → ASR → LLM → TTS 的本地纯 Python 语音闭环。
已脱离 ROS2：音频本机播放，实机控制（导航/机械臂）以 `dispatch` 桩预留，之后重写。

## 目录结构

    main.py                  入口（--check 自检）
    config.yaml              全部可调配置（模型路径/设备/唤醒词/阈值/提示语）
    lmam/app.py              主应用：状态机 + mic 线程 + ASR->LLM->TTS 消费线程
    scripts/
      config.py              配置加载
      command_bus.py         实机控制指令出口（桩，TODO 重写）
      audio_player.py        mp3/wav 讲解播放（pygame，支持打断续播）
      tts_local_player.py    MeloTTS 生成 + sounddevice 本机播放
      local_listener.py      麦克风 ASR（faster-whisper）
      wakeup.py              KWS 唤醒（funasr，唤醒词"小娟小娟"）
      llm.py                 LLM 意图分类 + RAG 知识库问答
      matcher.py             展品意图模糊匹配（控制层重写时复用）
    prompts/chat_exec.py     prompt 集占位版（真实 prompt 拷回后覆盖）
    text_to_mp3/             讲解音频生成工具
    tests/                   pytest 单测（无重型依赖也可跑，见 conftest.py）

## 安装

    pip install -r requirements.txt
    pip install git+https://github.com/myshell-ai/MeloTTS.git

## 配置

编辑 `config.yaml`：模型路径、cuda/cpu、麦克风设备名、唤醒词、LLM API 地址等。
路径不存在时启动会直接报错提示。

## 运行

    python main.py --check   # 校验配置与导入（不需要模型/音频设备）
    python main.py           # 启动；说"小娟小娟"唤醒

调试 CLI（stdin）：

    audio_start <mp3路径>    # 播放讲解音频；唤醒可打断，静默后自动续播
    stop                     # 打断全部播放
    quit                     # 退出

## 测试

    python -m pytest tests/ -v

## 之后要做

- 实机控制层重写：实现 `scripts/command_bus.py` 的 `register()` 挂接导航/机械臂
- 从机器人拷回真实 prompt 覆盖 `prompts/chat_exec.py`
- `landmark_to_name` 展区名映射填入 `config.yaml`
