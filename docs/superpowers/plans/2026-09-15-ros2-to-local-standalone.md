# lmam 本地化改造（脱离 ROS2）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 ROS2 包 lmam 改造为单机可跑的纯 Python 语音交互程序（唤醒→ASR→LLM→TTS 本机闭环），实机控制逻辑置空留桩。

**Architecture:** 保留原业务逻辑与线程模型，替换三层外壳：ROS 通信 → 进程内 `dispatch` 桩 + 线程/队列；Orin 音频板 → pygame/sounddevice 本机播放；硬编码 → config.yaml。缺失的 `prompts/chat_exec.py` 用功能完整占位版补齐。

**Tech Stack:** Python 3.10、pytest、pygame（mp3 讲解）、sounddevice+soundfile（TTS 播放）、MeloTTS、faster-whisper、funasr、langchain+faiss。

**Spec:** `docs/superpowers/specs/2026-09-15-ros2-to-local-standalone-design.md`

## Global Constraints

- 全仓库禁止出现 `rclpy` / `ament_index_python` / `std_msgs` / `action` ROS 导入
- 唤醒词统一为 `小娟小娟`（不再用"小云小云"）
- 提示语：唤醒 `您好，我在。`；回 IDLE `如果您有任何问题请呼唤两声小娟唤醒我哦。`
- 保留原中文注释与 `[LMAM]` 日志前缀风格；日志统一用标准 `logging`，logger 名 `lmam.*`
- **新文件**（config/command_bus/audio_player/tts_local_player）中重型库（pygame/melo）只允许在方法内延迟导入，保证 `import` 轻量；既有脚本（llm/local_listener/wakeup）保持原导入风格不动，测试环境由 conftest stub 兜底
- 所有新文件带 `# -*- coding: utf-8 -*-`；不写 `#!/home/igraperobot3/...` shebang
- 每个任务完成后在 `local` 分支上提交一次

---

### Task 1: `local` 分支 + 测试脚手架 + 配置加载

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`
- Create: `scripts/config.py`
- Create: `config.yaml`

**Interfaces:**
- Produces: `load_config(path=..., check_paths=True) -> Config`；`Config` 属性 = yaml 顶层键；缺必填键抛 `KeyError`；`check_paths=True` 时模型路径不存在抛 `FileNotFoundError`

- [ ] **Step 1: 创建分支与空脚手架**

```bash
cd "C:\Users\Lenovo\Desktop\IgrapeRobot3-task_planner_v3.0 (1)\IgrapeRobot3-task_planner_v3.0\lmam"
git checkout -b local
pip install pytest pyyaml 2>/dev/null || pip install --user pytest pyyaml
```

- [ ] **Step 2: 写 tests/conftest.py（重型依赖 stub，仅缺失时注入）**

```python
# -*- coding: utf-8 -*-
"""让纯逻辑单测在没有重型依赖（torch/funasr/melo/...）的机器上也能运行。

仅当真实导入失败时才注入空模块占位；被测的纯函数不触碰这些库的运行时行为。
"""
import os
import sys
import types

# 仓库根加入 sys.path，保证 `import scripts.xxx` 可用
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# name -> 需要 from-import 的属性名列表
_STUB_SPECS = {
    "torch": [],
    "openai": ["Client"],
    "websockets": [],
    "pyaudio": ["PyAudio"],
    "sounddevice": [],
    "soundfile": [],
    "pygame": ["mixer"],
    "faster_whisper": ["WhisperModel"],
    "funasr": ["AutoModel"],
    "melo": [],
    "melo.api": ["TTS"],
    "speech_recognition": ["Recognizer", "Microphone", "WaitTimeoutError", "AudioData"],
    "audioop": [],
    "langchain_community": [],
    "langchain_community.vectorstores": ["FAISS"],
    "langchain_huggingface": ["HuggingFaceEmbeddings"],
    "langchain_core": [],
    "langchain_core.documents": ["Document"],
}

# 必须是异常类的属性
_EXCEPTION_ATTRS = {"WaitTimeoutError"}

# 需要功能性实现（matcher 单测依赖其行为）的属性：name -> {attr: factory}
_FUNCTIONAL_ATTRS = {
    "cn2an": {"transform": lambda text, mode: text},
    "rapidfuzz": {"fuzz": None},  # None 表示在 _make_module 里特殊构造
}


def _make_fuzz_module():
    """无 rapidfuzz 时提供行为可预期的 partial_ratio：包含=100，否则 0。"""
    import types
    fuzz = types.ModuleType("rapidfuzz.fuzz")

    def partial_ratio(a, b):
        return 100 if a in b else 0

    fuzz.partial_ratio = partial_ratio
    mod = types.ModuleType("rapidfuzz")
    mod.fuzz = fuzz
    return mod


def _make_module(name, attr_names):
    mod = types.ModuleType(name)
    for attr in attr_names:
        if attr in _EXCEPTION_ATTRS:
            setattr(mod, attr, type(attr, (Exception,), {}))
        else:
            setattr(mod, attr, type(attr, (), {}))
    return mod


def _ensure(name, attr_names):
    try:
        __import__(name)
        return
    except ImportError:
        pass
    if name == "rapidfuzz":
        sys.modules[name] = _make_fuzz_module()
        return
    mod = _make_module(name, attr_names)
    for attr, factory in _FUNCTIONAL_ATTRS.get(name, {}).items():
        if factory is not None:
            setattr(mod, attr, factory)
    sys.modules[name] = mod
    # 挂到父模块属性上，保证 `from melo.api import TTS` 这类导入可用
    if "." in name:
        parent, child = name.rsplit(".", 1)
        try:
            __import__(parent)
        except ImportError:
            sys.modules[parent] = _make_module(parent, [])
        setattr(sys.modules[parent], child, sys.modules[name])


for _name, _attrs in _STUB_SPECS.items():
    _ensure(_name, _attrs)
```

- [ ] **Step 3: 写失败测试 tests/test_config.py**

```python
# -*- coding: utf-8 -*-
import os
import textwrap

import pytest

from scripts.config import load_config

MINIMAL_YAML = textwrap.dedent("""
    wake_word: "小娟小娟"
    kws_model_path: "{tmp}/kws"
    asr_model_path: "{tmp}/asr"
    llm_api_base: "http://127.0.0.1:8088/v1"
""")


def _write_cfg(tmp_path, extra=""):
    for d in ("kws", "asr"):
        (tmp_path / d).mkdir()
    content = MINIMAL_YAML.format(tmp=str(tmp_path)) + extra
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    return str(cfg_file)


def test_load_minimal_config(tmp_path):
    cfg = load_config(_write_cfg(tmp_path), check_paths=True)
    assert cfg.wake_word == "小娟小娟"
    assert cfg.llm_api_base == "http://127.0.0.1:8088/v1"


def test_missing_required_key_raises(tmp_path):
    bad = MINIMAL_YAML.format(tmp=str(tmp_path)).replace('llm_api_base: "http://127.0.0.1:8088/v1"', "")
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text(bad, encoding="utf-8")
    with pytest.raises(KeyError):
        load_config(str(cfg_file), check_paths=False)


def test_missing_model_path_raises_when_check(tmp_path):
    (tmp_path / "kws").mkdir()
    content = MINIMAL_YAML.format(tmp=str(tmp_path)).replace(
        f"{tmp_path}/asr", f"{tmp_path}/not_exist")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_config(str(cfg_file), check_paths=True)


def test_check_paths_false_skips(tmp_path):
    content = MINIMAL_YAML.format(tmp=str(tmp_path)).replace(
        f"{tmp_path}/kws", f"{tmp_path}/nope")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    cfg = load_config(str(cfg_file), check_paths=False)
    assert cfg.kws_model_path.endswith("nope")
```

- [ ] **Step 4: 运行确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: scripts.config`）

- [ ] **Step 5: 实现 scripts/config.py**

```python
# -*- coding: utf-8 -*-
"""config.yaml 加载。所有可调配置集中在此，代码中不再出现硬编码路径。"""
import os

import yaml

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")

# 必填键：缺失即拒绝启动
REQUIRED_KEYS = (
    "wake_word", "kws_model_path", "asr_model_path", "llm_api_base",
)
# 需要存在性检查的模型/数据路径
PATH_KEYS = (
    "kws_model_path", "asr_model_path", "tts_config_path", "tts_ckpt_path",
    "embed_model_path", "museum_txt_path", "vector_db_path",
)


class Config:
    """只读配置对象：yaml 顶层键 -> 同名属性。"""

    def __init__(self, data: dict):
        self._data = dict(data)
        for key, value in self._data.items():
            setattr(self, key, value)

    def get(self, key, default=None):
        return self._data.get(key, default)


def load_config(path: str = DEFAULT_CONFIG_PATH, check_paths: bool = True) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"配置文件为空或格式不对: {path}")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise KeyError(f"config.yaml 缺少必填项: {missing}")
    if check_paths:
        for key in PATH_KEYS:
            p = data.get(key)
            if p and not os.path.exists(p):
                raise FileNotFoundError(f"配置项 {key} 指向的路径不存在: {p}")
    return Config(data)
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 7: 写仓库级 config.yaml（真实默认值，路径按机器人环境）**

```yaml
# ==================== LMAM 本地运行配置 ====================
# 模型路径按部署机器调整；路径不存在时启动会直接报错（--check 除外）。

# ---------- 唤醒（KWS） ----------
wake_word: "小娟小娟"          # 唤醒词
kws_model_path: "/home/igraperobot3/Model/speech_charctc_kws_phone-xiaoyun"
kws_device: "cuda"             # 无 GPU 改 cpu
kws_rms_gate: 0.01

# ---------- ASR ----------
asr_model_path: "/home/igraperobot3/Model/faster-whisper-large-v3"
asr_device: "cuda"             # 无 GPU 改 cpu
mic_device_name: "Wireless microphone"   # 本机麦克风设备名关键字

# ---------- TTS（MeloTTS，本机扬声器播放） ----------
tts_config_path: "/home/igraperobot3/Model/melo/ZH/config.json"
tts_ckpt_path: "/home/igraperobot3/Model/melo/ZH/checkpoint.pth"
tts_device: "cuda"
tts_speed: 1.0
tts_sample_rate: 22050

# ---------- LLM / RAG ----------
llm_api_base: "http://192.168.3.11:8088/v1"
embed_model_path: "/home/igraperobot3/Model/BAAI/bge-large-zh-v1.5"
museum_txt_path: "/home/igraperobot3/Model/BAAI/museum.txt"
vector_db_path: "/home/igraperobot3/Model/vector_database_faiss/"

# ---------- 会话 / 状态机 ----------
session_hold_sec: 15.0         # 唤醒一次后的会话保持窗口
auto_resume_silence_sec: 0.5   # 静默多久自动续播讲解
resume_check_period: 0.2       # 续播检查周期
idle_timeout_sec: 10.0         # ACTIVE 静默超时回 IDLE
only_resume_when_idle: true    # 仅 IDLE 时自动续播

# ---------- 提示语 ----------
wakeup_prompt: "您好，我在。"
back_to_idle_prompt: "如果您有任何问题请呼唤两声小娟唤醒我哦。"

# ---------- ASR 文本过滤（出现即丢弃） ----------
asr_filter_words: ["志愿者", "杨茜茜", "字幕", "转发", "明镜", "观看", "感谢观看", "谢谢", "搅拌"]

# ---------- 展区名映射（占位，之后填） ----------
landmark_to_name:
  Landmark1: ""
  Landmark2: ""
  Landmark3: ""
  Landmark4: ""
  Landmark5: ""
  Landmark6: ""
  Landmark7: ""
  Landmark8: ""
```

- [ ] **Step 8: Commit**

```bash
git add tests/ scripts/config.py config.yaml
git commit -m "feat: add config loader (config.yaml) and pytest scaffold with dependency stubs"
```

---

### Task 2: command_bus 桩

**Files:**
- Create: `scripts/command_bus.py`
- Test: `tests/test_command_bus.py`

**Interfaces:**
- Produces: `dispatch(command: dict) -> None`（调用全部已注册 handler，handler 异常吞掉只告警）；`register(handler) -> None`

- [ ] **Step 1: 写失败测试 tests/test_command_bus.py**

```python
# -*- coding: utf-8 -*-
from scripts import command_bus


def setup_function(fn):
    command_bus._HANDLERS.clear()


def test_dispatch_calls_registered_handler():
    seen = []
    command_bus.register(seen.append)
    command_bus.dispatch({"action": "move_to", "param": {"marker_id": "Landmark1"}})
    assert seen == [{"action": "move_to", "param": {"marker_id": "Landmark1"}}]


def test_dispatch_swallows_handler_exception():
    def bad(_cmd):
        raise RuntimeError("boom")

    seen = []
    command_bus.register(bad)
    command_bus.register(seen.append)
    command_bus.dispatch({"action": "talk", "param": ""})
    assert seen == [{"action": "talk", "param": ""}]


def test_register_no_duplicates():
    handler = lambda c: None
    command_bus.register(handler)
    command_bus.register(handler)
    assert command_bus._HANDLERS.count(handler) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_command_bus.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 scripts/command_bus.py**

```python
# -*- coding: utf-8 -*-
"""实机控制指令出口（桩）。

原 ROS 版本通过 StateMsg 话题把指令发给 agent（导航/任务规划）。
脱离 ROS 后，指令统一走 dispatch()；当前仅记录日志，控制层之后重写。
"""

import logging

log = logging.getLogger("lmam.command_bus")

_HANDLERS = []


def register(handler) -> None:
    """注册指令处理器 handler(command: dict) -> None（去重）。"""
    if handler not in _HANDLERS:
        _HANDLERS.append(handler)


def dispatch(command: dict) -> None:
    """分发一条实机控制指令。

    TODO: 之后在此挂接新的控制层实现（导航/机械臂/展区讲解联动）。
    """
    log.info("[STUB] 实机控制指令: %s (待重写)", command)
    for handler in list(_HANDLERS):
        try:
            handler(command)
        except Exception as e:  # noqa: BLE001 控制层异常不能打断语音主流程
            log.warning("[command_bus] handler 异常: %s", e)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_command_bus.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/command_bus.py tests/test_command_bus.py
git commit -m "feat: add command_bus dispatch stub (robot control TBD)"
```

---

### Task 3: prompts/chat_exec.py 占位

**Files:**
- Create: `prompts/chat_exec.py`
- Test: `tests/test_chat_exec.py`

**Interfaces:**
- Produces: 常量 `SYSTEM_PROMPT0, SYSTEM_PROMPT1, SYSTEM_PROMPT3, SYSTEM_PROMPT4, SYSTEM_PROMPT_DATABASE, USER_PROMPT_DATABASE, SYSTEM_PROMPT_LANDMARK_NAV`；`USER_PROMPT_DATABASE` 必须恰好支持 `.format(sentences=..., paragraphs=..., user_question=...)`

- [ ] **Step 1: 写失败测试 tests/test_chat_exec.py**

```python
# -*- coding: utf-8 -*-
from prompts import chat_exec


def test_all_constants_exist():
    for name in ("SYSTEM_PROMPT0", "SYSTEM_PROMPT1", "SYSTEM_PROMPT3",
                 "SYSTEM_PROMPT4", "SYSTEM_PROMPT_DATABASE",
                 "USER_PROMPT_DATABASE", "SYSTEM_PROMPT_LANDMARK_NAV"):
        value = getattr(chat_exec, name)
        assert isinstance(value, str) and value.strip(), f"{name} 为空"


def test_user_prompt_database_format():
    out = chat_exec.USER_PROMPT_DATABASE.format(
        sentences="- 句子一", paragraphs="段落", user_question="问题")
    assert "句子一" in out and "段落" in out and "问题" in out


def test_user_prompt_has_no_extra_placeholders():
    # 除三个已知占位符外不应有其它 {}，否则 .format 会炸
    text = (chat_exec.USER_PROMPT_DATABASE
            .replace("{sentences}", "").replace("{paragraphs}", "")
            .replace("{user_question}", ""))
    assert "{" not in text and "}" not in text


def test_system_prompt1_mentions_two_line_format():
    # SYSTEM_PROMPT1 要求"第一行回复 + 第二行 /指令"
    assert "/" in chat_exec.SYSTEM_PROMPT1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_chat_exec.py -v`
Expected: FAIL（`ModuleNotFoundError: prompts.chat_exec`）

- [ ] **Step 3: 实现 prompts/chat_exec.py**

```python
# -*- coding: utf-8 -*-
"""占位 prompt 集（功能完整，可直接跑通）。

注意：机器人上的真实 prompt 拷回后直接覆盖本文件即可，键名保持不变。
"""

# 意图分类：A=指令 B=知识库问答 C=闲聊（llm.py 只认 A/B/C，其余按 C 处理）
SYSTEM_PROMPT0 = """\
你是一个服务机器人的意图分类器。根据用户的话，从下面三类中选一个，只输出单个字母：
A：用户下达了行动指令（带我去某个展区、开始参观、继续讲解、离开、拿展品等）
B：用户提出了知识性问题（询问展品、场馆相关的"是什么/为什么/怎么用"）
C：闲聊、寒暄、其它（你好、你是谁、天气、感谢等）
只输出 A、B 或 C，不要输出任何其它内容。
"""

# 指令生成：第一行口语回复，第二行 /指令（llm.py is_valid_command 白名单校验）
SYSTEM_PROMPT1 = """\
你是博物馆讲解机器人。用户提出了行动类请求，请严格按两行格式回复：
第一行：一句简短自然的中文口语回复（不超过50字）。
第二行：一个以 / 开头的指令，只能从下面选择一个：
/manipulate
/move_to Landmark1
/move_to Landmark2
/move_to Landmark3
/move_to Landmark4
/move_to Landmark5
/move_to Landmark6
/move_to Landmark7
/move_to Landmark8
/start
/resume
/leave
/NG
示例：
好的，我带您前往序厅。
/move_to Landmark1
注意：除上述指令外不要输出任何其它以 / 开头的内容。
"""

# 闲聊
SYSTEM_PROMPT3 = """\
你是一台具备语音交互能力的服务机器人。用户的语音由 ASR 转成文本输入给你，可能包含口语词、\
停顿、语句不完整或少量识别错误，你需要在理解的基础上容错处理，并给出自然、简洁、口语化的中文回复。\
回复必须是可朗读的中文口语句子，不超过100个汉字，不输出结构化信息，不执行任务、不生成指令。
"""

# 指令非法时的重生成
SYSTEM_PROMPT4 = """\
你上一次的输出包含了不允许的指令。请重新回答用户，严格按两行格式：
第一行：简短自然的中文口语回复。
第二行：只从这些指令里选一个：/manipulate、/move_to Landmark1 到 /move_to Landmark8、/start、/resume、/leave、/NG。
如果没有合适的指令，第二行只输出 /talk。
"""

# 知识库问答
SYSTEM_PROMPT_DATABASE = """\
你是博物馆讲解机器人。根据提供的知识库片段回答用户问题：
1. 只使用知识库中的信息，不要编造。
2. 用简洁、自然、口语化的中文回答，不超过150字，可直接朗读。
3. 如果知识库中没有相关内容，礼貌告知不知道并建议换个问法。
"""

# 注意：本字符串会被 .format(sentences=..., paragraphs=..., user_question=...) 填充，
# 不要在文本里再加其它花括号。
USER_PROMPT_DATABASE = """\
知识库检索片段：
{sentences}

参考段落：
{paragraphs}

用户问题：{user_question}
请根据以上知识库内容回答用户问题。
"""

# 未参观点位导航引导语生成
SYSTEM_PROMPT_LANDMARK_NAV = """\
你是博物馆讲解机器人。给你一份未参观点位列表，请生成一段简短、自然、口语化的中文引导语，\
向游客介绍接下来还可以参观哪些展区，鼓励游客前往。不超过100字，不要输出列表或指令。
"""
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_chat_exec.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add prompts/chat_exec.py tests/test_chat_exec.py
git commit -m "feat: add functional placeholder prompts (chat_exec)"
```

---

### Task 4: 本地讲解音频播放器（pygame）

**Files:**
- Create: `scripts/audio_player.py`
- Test: `tests/test_audio_player.py`

**Interfaces:**
- Produces: `AudioPlayer(on_finished=None, poll_interval=0.1)`；方法 `start(path)->bool`、`pause()->bool`、`resume()->bool`、`stop()`、`interrupt()`；`on_finished(status)` 在 `status="finished"`（自然播完）或 `"interrupted"`（stop/interrupt）时回调，各最多一次

- [ ] **Step 1: 写失败测试 tests/test_audio_player.py**

```python
# -*- coding: utf-8 -*-
import time

import pytest

from scripts.audio_player import AudioPlayer


class FakeMusic:
    def __init__(self):
        self.loaded = None
        self.busy = False
        self.paused = False
        self.stops = 0

    def load(self, path):
        self.loaded = path

    def play(self):
        self.busy = True

    def pause(self):
        self.paused = True
        self.busy = False

    def unpause(self):
        self.paused = False
        self.busy = True

    def stop(self):
        self.busy = False
        self.stops += 1

    def get_busy(self):
        return self.busy


@pytest.fixture
def fake_music(monkeypatch):
    music = FakeMusic()
    monkeypatch.setattr(AudioPlayer, "_music", staticmethod(lambda: music))
    return music


def _drain(poll=0.02, deadline=1.0):
    t0 = time.time()
    while time.time() - t0 < deadline:
        time.sleep(poll)


def test_start_plays_and_finish_callback(fake_music):
    got = []
    player = AudioPlayer(on_finished=got.append, poll_interval=0.01)
    assert player.start("demo.mp3") is True
    assert fake_music.loaded == "demo.mp3"
    fake_music.busy = False          # 模拟自然播完
    _drain()
    assert got == ["finished"]


def test_stop_interrupts_once(fake_music):
    got = []
    player = AudioPlayer(on_finished=got.append, poll_interval=0.01)
    player.start("demo.mp3")
    player.stop()
    player.stop()                    # 第二次应被忽略
    _drain()
    assert got == ["interrupted"]
    assert fake_music.stops >= 1


def test_pause_resume_cycle(fake_music):
    got = []
    player = AudioPlayer(on_finished=got.append, poll_interval=0.01)
    player.start("demo.mp3")
    assert player.pause() is True
    assert player.pause() is False   # 已暂停，重复暂停无效
    assert player.resume() is True
    assert player.resume() is False  # 未暂停，恢复无效
    fake_music.busy = False
    _drain()
    assert got == ["finished"]


def test_start_failure_returns_false(fake_music, monkeypatch):
    def bad_load(_path):
        raise RuntimeError("no such file")

    fake_music.load = bad_load
    got = []
    player = AudioPlayer(on_finished=got.append, poll_interval=0.01)
    assert player.start("missing.mp3") is False
    _drain()
    assert got == []                 # 失败不应触发 finished/interrupted
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_audio_player.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 scripts/audio_player.py**

```python
# -*- coding: utf-8 -*-
"""本地讲解音频播放器（替代原 Orin audio_control action）。

用 pygame.mixer.music 实现 mp3/wav 播放，语义对齐原 AudioControl：
- start(path)  开始播放
- pause()      暂停（断点保留）
- resume()     从断点续播
- stop()/interrupt()  停止（视为被打断）
自然播完回调 on_finished("finished")；stop/interrupt 回调 on_finished("interrupted")。
"""

import logging
import threading
import time

log = logging.getLogger("lmam.audio")


class AudioPlayer:
    def __init__(self, on_finished=None, poll_interval: float = 0.1):
        self.on_finished = on_finished or (lambda status: None)
        self.poll_interval = poll_interval
        self._lock = threading.Lock()
        self._paused = False
        self._stopped = True

    # ---- pygame 延迟初始化：导入/单测不触碰音频设备 ----
    @staticmethod
    def _music():
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return pygame.mixer.music

    # ---- 对外接口（对齐原 AudioControl 五个命令） ----
    def start(self, path: str) -> bool:
        music = self._music()
        try:
            music.load(path)
            music.play()
        except Exception as e:
            log.error("[AudioPlayer] start 失败: %s", e)
            return False
        with self._lock:
            self._paused = False
            self._stopped = False
        self._spawn_watcher()
        return True

    def pause(self) -> bool:
        with self._lock:
            if self._stopped or self._paused:
                return False
            self._paused = True
        self._music().pause()
        return True

    def resume(self) -> bool:
        with self._lock:
            if self._stopped or not self._paused:
                return False
            self._paused = False
        self._music().unpause()
        self._spawn_watcher()
        return True

    def stop(self) -> None:
        self._finish("interrupted")

    def interrupt(self) -> None:
        self._finish("interrupted")

    # ---- 内部 ----
    def _finish(self, status: str) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._paused = False
        try:
            self._music().stop()
        except Exception:  # noqa: BLE001
            pass
        self.on_finished(status)

    def _spawn_watcher(self):
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        while True:
            with self._lock:
                if self._stopped:
                    return
                paused = self._paused
            try:
                busy = self._music().get_busy()
            except Exception:  # noqa: BLE001
                busy = False
            if not busy:
                if paused:
                    return        # 暂停中：退出，resume 时重新起 watcher
                self._finish("finished")
                return
            time.sleep(self.poll_interval)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_audio_player.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/audio_player.py tests/test_audio_player.py
git commit -m "feat: add local mp3/wav AudioPlayer (pygame) replacing Orin audio_control"
```

---

### Task 5: TTS 本地播放器（melo 生成 + sounddevice 播放）

**Files:**
- Create: `scripts/tts_local_player.py`
- Delete（延后到 Task 8 统一删）: `scripts/tts_ws_streamer.py`
- Test: `tests/test_tts_local_player.py`

**Interfaces:**
- Produces: `TTSLocalPlayer(config_path, ckpt_path, device="cuda", language="ZH", speaker_key="ZH", speed=1.0, sample_rate=22050)`；`speak(text)` 阻塞播报（可被 `stop()` 打断提前返回）；`stop()` 置停止标记。melo 为延迟导入。

- [ ] **Step 1: 写失败测试 tests/test_tts_local_player.py**

```python
# -*- coding: utf-8 -*-
import numpy as np

from scripts import tts_local_player as tl


class FakePlayerModule:
    """模拟 sounddevice 的 play/is_playing/stop/wait。"""

    calls = []

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.playing = False

    @classmethod
    def play(cls, data, sr):
        cls.calls.append(("play", data.shape, sr))
        cls.playing = True

    @classmethod
    def is_playing(cls):
        return cls.playing

    @classmethod
    def stop(cls):
        cls.calls.append(("stop",))
        cls.playing = False


def test_speak_empty_text_noop(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    player = tl.TTSLocalPlayer.__new__(tl.TTSLocalPlayer)  # 跳过 melo 加载
    player._stop_flag = tl.threading.Event()
    player.speak("")   # 不应抛异常也不应调 play
    assert FakePlayerModule.calls == []


def test_speak_plays_audio(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    monkeypatch.setattr(tl, "sf", type("SF", (), {
        "read": staticmethod(lambda buf, dtype: (np.zeros(100, dtype="float32"), 22050))}))
    monkeypatch.setattr(tl.TTSLocalPlayer, "_run_tts_to_bytes",
                        lambda self, text: b"wav")
    player = tl.TTSLocalPlayer.__new__(tl.TTSLocalPlayer)
    player._stop_flag = tl.threading.Event()
    player.speak("你好")
    kinds = [c[0] for c in FakePlayerModule.calls]
    assert "play" in kinds


def test_stop_breaks_speak(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    monkeypatch.setattr(tl, "sf", type("SF", (), {
        "read": staticmethod(lambda buf, dtype: (np.zeros(100, dtype="float32"), 22050))}))
    monkeypatch.setattr(tl.TTSLocalPlayer, "_run_tts_to_bytes",
                        lambda self, text: b"wav")
    player = tl.TTSLocalPlayer.__new__(tl.TTSLocalPlayer)
    player._stop_flag = tl.threading.Event()

    real_is_playing = FakePlayerModule.is_playing

    def playing_then_stop():
        player._stop_flag.set()      # 第一次检查就触发停止
        return real_is_playing()

    monkeypatch.setattr(FakePlayerModule, "is_playing",
                        staticmethod(playing_then_stop))
    player.speak("长句播报")
    assert ("stop",) in FakePlayerModule.calls
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tts_local_player.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 scripts/tts_local_player.py**

```python
# -*- coding: utf-8 -*-
"""本地 TTS 播放器：MeloTTS 生成 wav + sounddevice 本机扬声器播放。

由 scripts/tts_ws_streamer.py 改造：删除 WebSocket 推流，改为本机播放。
speak(text) 阻塞至播完（与原 await 语义一致）；stop() 可从其它线程打断。
"""

import io
import logging
import tempfile
import threading
import time

import sounddevice as sd
import soundfile as sf

log = logging.getLogger("lmam.tts")


class TTSLocalPlayer:
    def __init__(
        self,
        config_path: str,
        ckpt_path: str,
        device: str = "cuda",
        language: str = "ZH",
        speaker_key: str = "ZH",
        speed: float = 1.0,
        sample_rate: int = 22050,
    ):
        self.speed = speed
        self.sample_rate = sample_rate
        # 延迟导入：melo 加载很重，--check/单测不需要
        from melo.api import TTS
        self.tts = TTS(
            language=language,
            device=device,
            use_hf=False,
            config_path=config_path,
            ckpt_path=ckpt_path,
        )
        self.speaker_ids = self.tts.hps.data.spk2id
        if speaker_key not in self.speaker_ids:
            raise ValueError(
                f"speaker_key='{speaker_key}' not in {list(self.speaker_ids.keys())}")
        self.speaker_id = self.speaker_ids[speaker_key]
        self._stop_flag = threading.Event()

    def _run_tts_to_bytes(self, text: str) -> bytes:
        """同步：TTS -> wav bytes（与原实现一致，临时文件放系统临时目录）。"""
        tmp_wav = f"{tempfile.gettempdir()}/tts_{int(time.time() * 1000)}.wav"
        self.tts.tts_to_file(text, self.speaker_id, tmp_wav, speed=self.speed)
        with open(tmp_wav, "rb") as f:
            wav_bytes = f.read()
        return wav_bytes

    def speak(self, text: str) -> None:
        """阻塞式播报；stop() 可打断。"""
        if not text:
            return
        try:
            wav_bytes = self._run_tts_to_bytes(text)
            data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
            self._stop_flag.clear()
            sd.play(data, sr)
            while sd.is_playing() and not self._stop_flag.is_set():
                time.sleep(0.05)
            sd.stop()
        except Exception as e:
            log.error("[TTSLocalPlayer] speak 失败: %s", e)

    def stop(self) -> None:
        self._stop_flag.set()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_tts_local_player.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/tts_local_player.py tests/test_tts_local_player.py
git commit -m "feat: add TTSLocalPlayer (melo + sounddevice) replacing WS streamer"
```

---

### Task 6: 三个既有脚本去硬编码（llm / local_listener / wakeup）

**Files:**
- Modify: `scripts/llm.py:1-26`（头部常量 + KnowledgeBase/LLM_ASSISTENT 构造参数化）
- Modify: `scripts/local_listener.py:27-65`（VoiceListener 增加 mic_device_name 参数）
- Modify: `scripts/wakeup.py:1-67,122-148`（IDLE_TIMEOUT 参数化、XiaoYunKWS 模型路径/设备参数化、唤醒词默认值改"小娟小娟"）
- Test: `tests/test_llm_parsing.py`, `tests/test_matcher.py`

**Interfaces:**
- Consumes: 无（本任务自包含）
- Produces:
  - `LLM_ASSISTENT(api_base=LLM_API_BASE, embed_model_path=EMBED_MODEL_PATH, db_file_path=DB_FILE_PATH, vector_db_path=VECTOR_DB_PATH)`（全部带原默认值）
  - `VoiceListener(model_path_or_size="small", device="auto", mic_device_name="Wireless microphone")`
  - `SharedState(idle_timeout_sec=10.0)`；`XiaoYunKWS(sample_rate=16000, keyword="小娟小娟", model_path=KWS_MODEL_PATH, device="cuda")`
  - `llm.parse_command / parse_llm_result / is_valid_command` 签名不变

- [ ] **Step 1: 写失败测试 tests/test_llm_parsing.py**

```python
# -*- coding: utf-8 -*-
from scripts.llm import is_valid_command, parse_command, parse_llm_result


def test_parse_command_no_param():
    assert parse_command("/start") == {"action": "start", "param": {"marker_id": ""}}


def test_parse_command_with_param():
    assert parse_command("/move_to Landmark1") == {
        "action": "move_to", "param": {"marker_id": "Landmark1"}}


def test_is_valid_command_accepts_whitelist():
    assert is_valid_command("好的。\n/move_to Landmark1") is True
    assert is_valid_command("好的。\n/start") is True


def test_is_valid_command_rejects_unknown():
    assert is_valid_command("好的。\n/destroy_world") is False


def test_parse_llm_result_intent_a():
    command, reply = parse_llm_result("A", "好的，带你去。\n/move_to Landmark2")
    assert command == {"action": "move_to", "param": {"marker_id": "Landmark2"}}
    assert reply == "好的，带你去。"


def test_parse_llm_result_intent_b_and_c():
    assert parse_llm_result("B", "答案")[0] == {"action": "talk_database", "param": ""}
    assert parse_llm_result("C", "哈喽")[0] == {"action": "talk", "param": ""}
```

- [ ] **Step 2: 运行确认失败/通过基线**

Run: `python -m pytest tests/test_llm_parsing.py -v`
Expected: PASS（现有函数已具备该行为；此测试是改造的回归保护网）。若失败，先修测试认知再继续。

- [ ] **Step 2b: 写 matcher 回归测试 tests/test_matcher.py（matcher.py 本身不改，纯保护网）**

```python
# -*- coding: utf-8 -*-
from scripts.matcher import ExhibitIntentMatcher

CFG = {
    "area_name": "NG展区",
    "global_excludes": ["机器人"],
    "settings": {"fuzzy_threshold": 50},
    "products": [
        {"id": "P1", "names": ["智能分拣机"], "anchors": ["分拣"], "exclude_words": ["坏了"]},
        {"id": "P2", "names": ["机械臂"], "anchors": ["手臂", "机械臂"], "exclude_words": []},
    ],
}


def test_anchor_and_name_hit():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("这个分拣的智能分拣机叫什么")
    assert r["success"] is True and r["product_id"] == "P1"


def test_global_exclude_blocks():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("机器人分拣机怎么样")
    assert r["success"] is False


def test_product_exclude_blocks():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("分拣机坏了怎么修")
    assert r["success"] is False


def test_no_anchor_no_match():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("天气怎么样")
    assert r["success"] is False
```

Run: `python -m pytest tests/test_matcher.py -v`
Expected: 4 passed（真实 rapidfuzz 或 conftest 功能性 stub 下行为一致：包含即命中）

- [ ] **Step 3: 修改 scripts/llm.py 头部（参数化构造，行为不变）**

把：

```python
LLM_API_BASE = "http://192.168.3.11:8088/v1"
MAX_HISTORY_ROUNDS = 10
DB_FILE_PATH = "/home/igraperobot3/Model/BAAI/museum.txt"
VECTOR_DB_PATH = "/home/igraperobot3/Model/vector_database_faiss/"
class KnowledgeBase:
    def __init__(self, device="cuda"):
        model_name = "/home/igraperobot3/Model/BAAI/bge-large-zh-v1.5"
```

改为：

```python
LLM_API_BASE = "http://192.168.3.11:8088/v1"
EMBED_MODEL_PATH = "/home/igraperobot3/Model/BAAI/bge-large-zh-v1.5"
MAX_HISTORY_ROUNDS = 10
DB_FILE_PATH = "/home/igraperobot3/Model/BAAI/museum.txt"
VECTOR_DB_PATH = "/home/igraperobot3/Model/vector_database_faiss/"
class KnowledgeBase:
    def __init__(self, device="cuda", model_name=EMBED_MODEL_PATH):
```

把 `class LLM_ASSISTENT:` 的 `def __init__(self):` 改为：

```python
    def __init__(self, api_base=LLM_API_BASE, embed_model_path=EMBED_MODEL_PATH,
                 db_file_path=DB_FILE_PATH, vector_db_path=VECTOR_DB_PATH):
```

函数体内把 `VECTOR_DB_PATH`、`DB_FILE_PATH`、`kb_builder = KnowledgeBase(device="cuda")`、
`self.llm_client = openai.Client(base_url=LLM_API_BASE, api_key="EMPTY")` 分别换成参数名
`vector_db_path`、`db_file_path`、`kb_builder = KnowledgeBase(device="cuda", model_name=embed_model_path)`、
`self.llm_client = openai.Client(base_url=api_base, api_key="EMPTY")`。

- [ ] **Step 4: 修改 scripts/local_listener.py**

把：

```python
    def __init__(self, model_path_or_size="small", device="auto"):
```

改为：

```python
    def __init__(self, model_path_or_size="small", device="auto",
                 mic_device_name="Wireless microphone"):
```

把 `self.mic_index = self._find_sdd_device_index()` 改为
`self.mic_index = self._find_sdd_device_index(mic_device_name)`；把：

```python
    def _find_sdd_device_index(self):
        devices = sd.query_devices()
        device_index=None
        for i, dev in enumerate(devices):
            if "Wireless microphone" in dev['name']:
```

改为：

```python
    def _find_sdd_device_index(self, mic_device_name="Wireless microphone"):
        devices = sd.query_devices()
        device_index=None
        for i, dev in enumerate(devices):
            if mic_device_name in dev['name']:
```

- [ ] **Step 5: 修改 scripts/wakeup.py**

头部 `IDLE_TIMEOUT = 10.0` 改为 `DEFAULT_IDLE_TIMEOUT = 10.0`；`SharedState` 改为：

```python
    def __init__(self, idle_timeout_sec: float = DEFAULT_IDLE_TIMEOUT):
        self.idle_timeout_sec = float(idle_timeout_sec)
        self.mode: str = "IDLE"
        self.tts_playing: bool = False
        self.audio_playing: bool = False
        self.tts_proc: Optional[subprocess.Popen] = None
        self.last_user_activity: float = field(default_factory=time.time)
        self.lock: Lock = field(default_factory=Lock)
```

`maybe_back_to_idle` 里 `need_idle = elapsed > IDLE_TIMEOUT` 与打印中的 `IDLE_TIMEOUT`
改为 `self.idle_timeout_sec`。`XiaoYunKWS.__init__` 改为：

```python
    DEFAULT_KWS_MODEL = "/home/igraperobot3/Model/speech_charctc_kws_phone-xiaoyun"

    def __init__(self, sample_rate: int = 16000, keyword: str = "小娟小娟",
                 model_path: str = DEFAULT_KWS_MODEL, device: str = "cuda"):
        self.sample_rate = sample_rate
        self.keyword = keyword

        print("[KWS] Loading FunASR KWS model...")
        self.model = AutoModel(
            model=model_path,
            keywords=keyword,
            disable_update=True,
            output_dir="./outputs/debug",
            device=device,
        )
```

（`DEFAULT_KWS_MODEL` 作为类常量放在类体内、`__init__` 上方；原 `model="..."`、
`keyword: str = "小云小云"` 默认值删除。）

- [ ] **Step 6: 全量回归**

Run: `python -m pytest tests/ -v`
Expected: Task 1-5 全部 PASS，新增 test_llm_parsing 6 条 + test_matcher 4 条 PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/llm.py scripts/local_listener.py scripts/wakeup.py tests/test_llm_parsing.py tests/test_matcher.py
git commit -m "refactor: parameterize llm/local_listener/wakeup, config-ready (wake word -> 小娟小娟)"
```

---

### Task 7: 主应用 lmam/app.py（核心改造）

**Files:**
- Create: `lmam/__init__.py`（空文件）
- Create: `lmam/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 2 `dispatch`、Task 4 `AudioPlayer`、Task 5 `TTSLocalPlayer`、Task 6 三个组件新签名、`Config`
- Produces: `LMAMApp(cfg, listener=None, kws=None, assistant=None, tts=None, player=None)`；方法 `start()`（起线程）、`shutdown()`、`audio_start(path)->bool`、`audio_stop()`、`_handle_text(text)`、`_on_audio_finished(status)`、`_resume_check()`、`_run_llm(text)->(command, reply)`

- [ ] **Step 1: 写失败测试 tests/test_app.py**

```python
# -*- coding: utf-8 -*-
import queue as q

import pytest

from lmam.app import LMAMApp
from scripts.config import Config
from scripts.wakeup import SharedState


class FakeAssistant:
    def __init__(self, intent="A", reply="好的。\n/move_to Landmark1"):
        self.intent = intent
        self.reply = reply
        self.calls = []

    def chat(self, text, unvisited, current_landmark):
        self.calls.append((text, unvisited, current_landmark))
        return self.intent, self.reply


class FakeTTS:
    def __init__(self):
        self.spoken = []
        self.stops = 0

    def speak(self, text):
        self.spoken.append(text)

    def stop(self):
        self.stops += 1


class FakePlayer:
    def __init__(self):
        self.finished_cb = None
        self.actions = []
        self.resume_ok = True

    def start(self, path):
        self.actions.append(("start", path))
        return True

    def pause(self):
        self.actions.append(("pause",))
        return True

    def resume(self):
        self.actions.append(("resume",))
        return self.resume_ok

    def stop(self):
        self.actions.append(("stop",))

    def interrupt(self):
        self.actions.append(("interrupt",))


@pytest.fixture
def app_parts():
    cfg = {"wake_word": "小娟小娟", "asr_filter_words": ["志愿者", "字幕"],
           "session_hold_sec": 15.0, "auto_resume_silence_sec": 0.5,
           "resume_check_period": 0.2, "idle_timeout_sec": 10.0,
           "only_resume_when_idle": True, "wakeup_prompt": "您好，我在。",
           "back_to_idle_prompt": "回IDLE", "kws_rms_gate": 0.01}
    cfg = Config(cfg)
    tts = FakeTTS()
    player = FakePlayer()
    assistant = FakeAssistant()
    app = LMAMApp(cfg, listener=object(), kws=object(),
                  assistant=assistant, tts=tts, player=player)
    app.shared_state.set_mode("ACTIVE")
    return app, assistant, tts, player


def test_handle_text_dispatches_command_and_speaks(app_parts):
    app, assistant, tts, player = app_parts
    app._handle_text("带我去序厅")
    assert assistant.calls and assistant.calls[0][0] == "带我去序厅"
    assert tts.spoken == ["好的。"]       # 两行格式只播第一行
    assert ("resume",) not in player.actions


def test_handle_text_filters_words(app_parts):
    app, assistant, tts, player = app_parts
    app._handle_text("志愿者来了")
    assert assistant.calls == [] and tts.spoken == []


def test_handle_text_ignore_when_idle(app_parts):
    app, assistant, tts, player = app_parts
    app.shared_state.set_mode("IDLE")
    app._handle_text("你好呀")
    assert assistant.calls == []


def test_handle_text_resume_action(app_parts):
    app, assistant, tts, player = app_parts
    app.guide_paused = True
    assistant.intent, assistant.reply = "A", "我继续为您讲解\n/resume"
    app._handle_text("继续讲解")
    assert ("resume",) in player.actions
    assert app.guide_paused is False


def test_on_audio_finished_updates_state(app_parts):
    app, *_ = app_parts
    app.shared_state.set_audio_playing(True, None)
    app.guide_paused = True
    app._on_audio_finished("finished")
    assert app.shared_state.audio_playing is False
    assert app.guide_paused is False
    app.shared_state.set_audio_playing(True, None)
    app.guide_paused = True
    app._on_audio_finished("interrupted")
    assert app.shared_state.audio_playing is False
    assert app.guide_paused is True       # interrupted 不清除待续播


def test_resume_check_triggers_auto_resume(app_parts):
    app, _, tts, player = app_parts
    app.shared_state.set_mode("IDLE")
    app.guide_paused = True
    import time as _time
    app.last_activity_ts = _time.time() - 10.0
    app._resume_check()
    assert ("resume",) in player.actions
    assert tts.spoken == ["我继续为您讲解"]
    assert app.guide_paused is False


def test_resume_check_skip_when_active(app_parts):
    app, _, tts, player = app_parts
    app.guide_paused = True
    import time as _time
    app.last_activity_ts = _time.time() - 10.0
    app._resume_check()                   # mode==ACTIVE，且 only_resume_when_idle
    assert player.actions == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL（`ModuleNotFoundError: lmam`）

- [ ] **Step 3: 实现 lmam/__init__.py（空）与 lmam/app.py**

```python
# -*- coding: utf-8 -*-
"""LMAM 本地语音交互主应用（脱离 ROS2）。

由 lmam_node/lmam_node.py 改造：
- ROS 话题/动作   -> scripts/command_bus.dispatch 桩 + 本地播放器
- WS 推流 Orin    -> 本机扬声器播放（scripts/tts_local_player.py）
- 实机控制逻辑    -> 已置空（move_to/NG/manipulate/leave/start 由 dispatch 留桩，之后重写）
"""

import logging
import queue
import threading
import time

from scripts.audio_player import AudioPlayer
from scripts.command_bus import dispatch
from scripts.llm import LLM_ASSISTENT, parse_llm_result
from scripts.local_listener import VoiceListener
from scripts.tts_local_player import TTSLocalPlayer
from scripts.wakeup import ClientControlState, SharedState, XiaoYunKWS

log = logging.getLogger("lmam.app")


class LMAMApp:
    """唤醒 -> ASR -> LLM -> TTS 本机闭环；讲解 mp3 本机播放，支持打断续播。"""

    def __init__(self, cfg, listener=None, kws=None, assistant=None,
                 tts=None, player=None):
        self.cfg = cfg

        # ====== 状态机（原 SharedState / ClientControlState 原样保留） ======
        self.shared_state = SharedState(idle_timeout_sec=float(cfg.idle_timeout_sec))
        self.ctrl = ClientControlState()

        # 会话窗口（唤醒一次后 N 秒内不需要重复唤醒）
        self.session_hold_sec = float(cfg.session_hold_sec)
        self.awake_until_ts = 0.0

        # 静默计时
        self.last_activity_ts = time.time()

        # 讲解是否处于“断点待续播”
        self.guide_paused = False

        # 自动 resume 控制
        self.resume_inflight = False
        self.pause_deadline_sec = float(cfg.auto_resume_silence_sec)
        self.resume_check_period = float(cfg.resume_check_period)
        self.only_resume_when_idle = bool(cfg.only_resume_when_idle)

        # ====== 组件（支持注入，便于测试；默认构造真实组件） ======
        self.local_listener = listener or VoiceListener(
            model_path_or_size=cfg.asr_model_path,
            device=cfg.asr_device,
            mic_device_name=cfg.mic_device_name,
        )
        self.kws = kws or XiaoYunKWS(
            sample_rate=16000,
            keyword=cfg.wake_word,
            model_path=cfg.kws_model_path,
            device=cfg.kws_device,
        )
        self.kws_rms_gate = float(cfg.kws_rms_gate)
        self.assistant = assistant or LLM_ASSISTENT(
            api_base=cfg.llm_api_base,
            embed_model_path=cfg.embed_model_path,
            db_file_path=cfg.museum_txt_path,
            vector_db_path=cfg.vector_db_path,
        )
        self.tts = tts or TTSLocalPlayer(
            config_path=cfg.tts_config_path,
            ckpt_path=cfg.tts_ckpt_path,
            device=cfg.tts_device,
            speed=float(cfg.tts_speed),
            sample_rate=int(cfg.tts_sample_rate),
        )

        # ====== 本地讲解播放器（替代 Orin audio_control） ======
        self.player = player or AudioPlayer(on_finished=self._on_audio_finished)

        # ====== 运行时字段（保留原命名） ======
        self.unvisited_landmarks = None
        self.audio_done_path = ""
        self.txt_command = ""
        self.idle_timeout = None
        self.last_command = None
        self.last_replytxt = None
        self.idle_txt = None
        self.current_landmark = "Landmark0"
        self.leave_send = False

        # ====== 线程间队列 / 线程控制 ======
        self.asr_text_queue = queue.Queue()
        self.mic_stop = threading.Event()
        self._consumer_stop = threading.Event()
        self._threads_started = False

        self._enter_idle("boot")

    # =========================
    # 生命周期
    # =========================
    def start(self):
        """启动 mic 线程与消费线程（构造函数不再自动起线程，便于测试）。"""
        if self._threads_started:
            return
        self._threads_started = True
        threading.Thread(target=self._mic_worker, daemon=True).start()
        threading.Thread(target=self._asr_text_consumer, daemon=True).start()
        log.info("[LMAM] started. mic thread + consumer thread ready.")

    def shutdown(self):
        self.mic_stop.set()
        self._consumer_stop.set()
        try:
            self.player.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.tts.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.local_listener.destroy()
        except Exception:  # noqa: BLE001
            pass
        log.info("[LMAM] shutdown complete.")

    # =========================
    # 调试 CLI 入口（main.py 调用）
    # =========================
    def audio_start(self, path: str) -> bool:
        """播放讲解音频（原 agent audio_start 命令的本地等价）。"""
        self._enter_idle("audio_start")
        self.guide_paused = False
        self.shared_state.set_audio_playing(True, None)
        ok = self.player.start(path)
        if not ok:
            self.shared_state.set_audio_playing(False, None)
        return ok

    def audio_stop(self):
        """打断全部本地播放（等价原 interrupt）。"""
        self.guide_paused = False
        self.player.interrupt()
        self.tts.stop()

    # =========================
    # mic worker（原逻辑；leave 自动发送已随实机控制置空删除）
    # =========================
    def _mic_worker(self):
        while not self.mic_stop.is_set():
            try:
                mode = self.shared_state.mode
            except Exception:
                mode = "IDLE"

            # ========== IDLE：只做 KWS ==========
            if mode == "IDLE":
                try:
                    pcm = self.local_listener.read_kws_pcm_16k(duration_sec=0.2)
                except Exception as e:
                    log.warning("[KWS] read_kws_pcm_16k failed: %s", e)
                    time.sleep(0.05)
                    continue

                if self.kws.feed(pcm):
                    if self.ctrl.can_send("WAKE", min_interval=2.0):
                        log.info("[LMAM] wake word detected -> interrupt playback")
                        # 1) 打断当前本地播放（mp3 讲解 -> interrupt；TTS -> stop）
                        self.player.interrupt()
                        self.tts.stop()

                        # 2) 标记：讲解断点待续播（静默后自动续播）
                        if self.shared_state.audio_playing:
                            self.guide_paused = True
                            self.shared_state.set_audio_playing(False, None)

                        # 3) 播唤醒提示语（独立线程，不阻塞 mic 循环）
                        threading.Thread(
                            target=self._play_wakeup_prompt,
                            args=(self.cfg.wakeup_prompt,), daemon=True).start()
                        # 4) 进入 ACTIVE
                        self._enter_active("wakeup")
                        self.idle_timeout = None
                        self.last_activity_ts = time.time()
                continue

            # ========== ACTIVE：ASR ==========
            try:
                try:
                    self.local_listener.close_kws_stream()
                except Exception:
                    pass

                result_text = self.local_listener.listen_and_transcribe()
                if result_text and result_text.strip():
                    self.asr_text_queue.put(result_text.strip())

                # 超时回到 IDLE
                if not self.shared_state.tts_playing:
                    self.idle_timeout = self.shared_state.maybe_back_to_idle()
                if (self.idle_timeout is not None and not self.guide_paused
                        and not self.shared_state.audio_playing
                        and not self.shared_state.tts_playing):
                    threading.Thread(
                        target=self._play_backtoIDLE_prompt,
                        args=(self.cfg.back_to_idle_prompt,), daemon=True).start()
                if self.shared_state.mode == "IDLE":
                    log.info("[LMAM] Back to IDLE")

            except Exception as e:
                log.error("[mic] error: %s", e)
                time.sleep(0.05)

    # =========================
    # ASR -> LLM -> TTS 消费线程（原 asyncio consumer 的线程版，串行语义一致）
    # =========================
    def _asr_text_consumer(self):
        while not self._consumer_stop.is_set():
            try:
                text = self.asr_text_queue.get(timeout=self.resume_check_period)
            except queue.Empty:
                self._resume_check()
                continue
            self._handle_text(text)

    def _handle_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        # 过滤词（原硬编码列表 -> config.asr_filter_words）
        if any(w in text for w in self.cfg.asr_filter_words):
            return
        # 只在 ACTIVE 才处理
        if self.shared_state.mode != "ACTIVE":
            return

        self.last_activity_ts = time.time()
        try:
            command, reply_text = self._run_llm(text)

            if command["action"] == "resume":
                self._auto_resume_mp3_once()
                return

            # 实机控制指令出口（当前为桩；move_to/NG/manipulate/leave/start/talk 都走这里）
            dispatch(command)

            # 播报 LLM 回复
            self._enter_idle("tts outgoing")
            self.shared_state.set_tts_playing(True, None)
            self._enter_idle("tts playing")
            self.tts.speak(reply_text)
        except Exception as e:
            log.error("[ASR->LLM->TTS] error: %s", e)

    def _run_llm(self, text: str):
        intent, ai_response = self.assistant.chat(
            text, self.unvisited_landmarks, self.current_landmark)
        return parse_llm_result(intent, ai_response)

    # =========================
    # 自动续播（原 _resume_check_cb / _auto_resume_mp3_once 的同步版）
    # =========================
    def _resume_check(self):
        if self.resume_inflight:
            return
        if not self.guide_paused:
            return
        if self.shared_state.tts_playing:
            return
        if self.only_resume_when_idle and self.shared_state.mode != "IDLE":
            return
        elapsed = time.time() - float(self.last_activity_ts)
        if elapsed >= self.pause_deadline_sec:
            self.resume_inflight = True
            log.info("[LMAM] silence window reached, auto-resume")
            try:
                self._auto_resume_mp3_once()
            finally:
                self.resume_inflight = False

    def _auto_resume_mp3_once(self):
        self.shared_state.set_tts_playing(True, None)
        self._enter_idle("orin playing")
        self.tts.speak("我继续为您讲解")
        ok = self.player.resume()
        if ok:
            self.shared_state.set_audio_playing(True, None)
            self.guide_paused = False
            log.info("[LMAM] auto-resume mp3 success -> guide_paused=False")
        else:
            log.warning("[LMAM] auto-resume mp3 failed -> will retry in next silence window")

    # =========================
    # 提示语播放（原协程改同步，由调用方放独立线程）
    # =========================
    def _play_wakeup_prompt(self, text: str = "您好，我在。"):
        try:
            self._enter_idle("wakeup prompt tts")
            self.tts.speak(text)
            self.idle_txt = None
        except Exception as e:
            log.warning("[wakeup_prompt] failed: %s", e)

    def _play_backtoIDLE_prompt(self, text: str = "如果您有任何问题请呼唤两声小娟唤醒我哦。"):
        try:
            self.idle_txt = text
            self._enter_idle("back to idle prompt tts")
            self.tts.speak(text)
        except Exception as e:
            log.warning("[backto_idle_prompt] failed: %s", e)

    # =========================
    # 播放完成回调（原 /audio_done 订阅的本地等价）
    # =========================
    def _on_audio_finished(self, status: str):
        if status in ("finished", "interrupted"):
            self.shared_state.set_audio_playing(False, None)
        if status != "finished":
            log.info("[LMAM] audio done: status=%s (ignored)", status)
            return
        log.info("[LMAM] audio finished, guide not paused anymore")
        # 讲解自然结束：不再待续播
        self.guide_paused = False

    # =========================
    # 模式切换 / 日志（原样，get_logger -> logging）
    # =========================
    def _enter_idle(self, reason: str = ""):
        self.shared_state.set_mode("IDLE")
        self.idle_timeout = time.time()
        log.info("[LMAM] -> IDLE (%s)", reason)

    def _enter_active(self, reason: str = ""):
        self.shared_state.wake()
        log.info("[LMAM] -> ACTIVE (%s)", reason)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_app.py -v`
Expected: 7 passed

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add lmam/__init__.py lmam/app.py tests/test_app.py
git commit -m "feat: add LMAMApp local voice loop (ROS node -> threads + local playback)"
```

---

### Task 8: main.py 入口 + 调试 CLI + --check + 清理 ROS 文件

**Files:**
- Create: `main.py`
- Delete: `package.xml`, `CMakeLists.txt`, `action/AudioControl.action`, `action/StartClient.action`, `lmam_node/lmam_node.py`, `scripts/tts_ws_streamer.py`
- Modify: `README.md`（整文件替换）
- Create: `requirements.txt`

**Interfaces:**
- Consumes: Task 7 `LMAMApp.start/shutdown/audio_start/audio_stop`、Task 1 `load_config`
- Produces: `python main.py [--check]`；CLI 命令 `audio_start <路径>` / `stop` / `quit`

- [ ] **Step 1: 实现 main.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LMAM 本地运行入口。

用法：
    python main.py            # 启动语音交互（需音频设备与模型文件）
    python main.py --check    # 只校验配置与模块导入，不加载模型、不开音频

调试 CLI（stdin）：
    audio_start <mp3路径>     # 播放讲解音频（验证打断/续播）
    stop                      # 打断全部本地播放
    quit                      # 退出
"""

import argparse
import logging
import sys
import threading

from scripts.config import load_config


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def run_check() -> int:
    """轻量自检：配置 + 模块导入。不加载任何模型。

    轻量模块（config/command_bus/audio_player/matcher/tts_local_player 模块级）
    必须可导入，否则退出码 1；重型依赖模块（llm/local_listener/wakeup/app，依赖
    torch/funasr/pyaudio 等）允许缺失，仅提示——它们在真机环境才就绪。
    """
    import importlib
    import os

    try:
        cfg = load_config(check_paths=False)
    except Exception as e:
        print(f"[check] FAIL: {e}")
        return 1
    print("[check] OK: config 加载成功")
    print(f"[check] 唤醒词: {cfg.wake_word}")

    light = ["scripts.command_bus", "scripts.audio_player",
             "scripts.tts_local_player", "scripts.matcher"]
    heavy = ["scripts.llm", "scripts.local_listener", "scripts.wakeup", "lmam.app"]
    failed_light = []
    for mod_name in light + heavy:
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            if mod_name in light:
                failed_light.append(f"{mod_name}: {e}")
            else:
                print(f"[check] 跳过 {mod_name}（依赖未安装，真机环境需就绪）: {type(e).__name__}")
    if failed_light:
        for line in failed_light:
            print(f"[check] FAIL: {line}")
        return 1

    missing = [k for k in ("kws_model_path", "asr_model_path", "tts_config_path",
                           "tts_ckpt_path", "embed_model_path", "museum_txt_path",
                           "vector_db_path") if not os.path.exists(cfg.get(k, ""))]
    if missing:
        print(f"[check] 提示: 以下模型/数据路径在本机不存在（真机运行前需就绪）: {missing}")
    print("[check] DONE")
    return 0


def cli_loop(app):
    """调试 CLI：驱动音频播放/打断，验证打断续播体验。"""
    while True:
        try:
            line = input().strip()
        except (EOFError, KeyboardInterrupt):
            line = "quit"
        if not line:
            continue
        if line == "quit":
            app.shutdown()
            return
        if line.startswith("audio_start "):
            path = line.split(" ", 1)[1].strip()
            print(f"[cli] audio_start -> {app.audio_start(path)}")
        elif line == "stop":
            app.audio_stop()
            print("[cli] stop sent")
        else:
            print("[cli] 可用命令: audio_start <路径> | stop | quit")


def main():
    parser = argparse.ArgumentParser(description="LMAM local voice app")
    parser.add_argument("--check", action="store_true", help="只校验配置与导入")
    args = parser.parse_args()

    setup_logging()
    if args.check:
        sys.exit(run_check())

    cfg = load_config(check_paths=True)  # 路径不就绪直接报错退出
    from lmam.app import LMAMApp
    app = LMAMApp(cfg)
    app.start()

    threading.Thread(target=cli_loop, args=(app,), daemon=True).start()
    try:
        while threading.active_count() > 1:
            threading.Event().wait(0.5)
    except KeyboardInterrupt:
        app.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手动验证 --check**

Run: `python main.py --check`
Expected: 退出码 0，输出 `[check] OK: config 加载成功` 与 `[check] DONE`；开发机（无 torch/funasr 等）会看到"跳过 ... 依赖未安装"提示，模型路径缺失提示属预期

- [ ] **Step 3: 删除 ROS 文件**

```bash
git rm package.xml CMakeLists.txt action/AudioControl.action action/StartClient.action lmam_node/lmam_node.py scripts/tts_ws_streamer.py
```

- [ ] **Step 4: 写 requirements.txt**

```
# Python 3.10 建议；MeloTTS 无 PyPI 包，单独安装：
#   pip install git+https://github.com/myshell-ai/MeloTTS.git
openai>=1.0
numpy
pyyaml
pygame>=2.0
sounddevice
soundfile
SpeechRecognition
pyaudio
faster-whisper
funasr
torch
cn2an
rapidfuzz
langchain-community
langchain-huggingface
faiss-cpu
```

- [ ] **Step 5: 重写 README.md**

```markdown
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
      wakeup.py              KWS 唤醒（funasr，唤醒词“小娟小娟”）
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
    python main.py           # 启动；说“小娟小娟”唤醒

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
```

- [ ] **Step 6: 全量回归 + --check**

Run: `python -m pytest tests/ -v && python main.py --check`
Expected: 全部 PASS；`[check] OK`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add main.py entry + CLI + requirements + README; remove ROS2 files"
```

---

### Task 9: 收尾验证与合并

**Files:** 无新文件

- [ ] **Step 1: 确认无 ROS 残留**

Run: `grep -rn "rclpy\|ament_index\|std_msgs\|tts_ws_streamer\|小云" --include="*.py" --include="*.yaml" --include="*.md" . | grep -v docs/ | grep -v text_to_mp3 || echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 2: 全量测试**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: 合并回 lmam 并推送**

```bash
git checkout lmam
git merge --no-ff local -m "Merge branch 'local': ROS2 -> local standalone conversion"
git push origin lmam local
```

- [ ] **Step 4: 汇报**

向需求方汇报：完成内容、测试结果、`--check` 输出、遗留事项（真机验证步骤）。
