# -*- coding: utf-8 -*-
"""config.yaml 加载。所有可调配置集中在此，代码中不再出现硬编码路径。

约定：
- 扁平键；相对路径按 config.yaml 所在目录解析（跨机器/跨目录可直接复用）。
- 路径支持 ``~`` 与 ``$VAR`` 展开。
- 设备值支持 ``auto``（探测 CUDA，失败回退 CPU）。
"""
import logging
import os

import yaml

log = logging.getLogger("lmam.config")

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")

# 必填键：缺失即拒绝启动（app 以属性方式访问这些键，缺失会在构建中途才 AttributeError）
REQUIRED_KEYS = (
    # KWS / 唤醒
    "wake_word", "kws_model_path", "kws_device",
    # ASR
    "asr_model_path", "asr_device", "mic_device_name",
    # TTS
    "tts_config_path", "tts_ckpt_path", "tts_device", "tts_speed",
    # 问答后端
    "rag_api_base", "rag_area_id", "rag_timeout_sec", "rag_session_id",
    # 会话 / 状态机
    "auto_resume_silence_sec", "resume_check_period",
    "only_resume_when_idle", "idle_timeout_sec",
    # 提示语 / 过滤
    "wakeup_prompt", "back_to_idle_prompt", "asr_filter_words",
)
# 需要存在性检查的模型/数据路径
PATH_KEYS = (
    "kws_model_path", "asr_model_path", "tts_config_path", "tts_ckpt_path",
)


def resolve_device(value: str, probe=None) -> str:
    """把配置里的 auto/cpu/cuda 解析成实际设备。

    probe: 可选的无参函数，返回 bool；默认用 torch.cuda.is_available()，
    便于单测注入。探测失败一律回退 cpu。
    """
    v = (value or "auto").strip().lower()
    if v in ("cpu", "cuda"):
        return v
    if v != "auto":
        raise ValueError(f"未知设备配置: {value!r}（可选 auto/cpu/cuda）")
    if probe is None:
        probe = _cuda_available
    try:
        return "cuda" if probe() else "cpu"
    except Exception as e:  # noqa: BLE001
        log.warning("CUDA 探测失败，回退 cpu: %s", e)
        return "cpu"


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


class Config:
    """只读配置对象：yaml 顶层键 -> 同名属性。"""

    def __init__(self, data: dict, base_dir: str = ""):
        self._data = dict(data)
        self.base_dir = base_dir
        for key, value in self._data.items():
            setattr(self, key, value)

    def get(self, key, default=None):
        return self._data.get(key, default)


def _resolve_path(value, base_dir: str) -> str:
    if not value:
        return value
    p = os.path.expandvars(os.path.expanduser(str(value)))
    if not os.path.isabs(p):
        p = os.path.join(base_dir, p)
    return os.path.normpath(p)


def load_config(path: str = DEFAULT_CONFIG_PATH, check_paths: bool = True) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"配置文件为空或格式不对: {path}")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise KeyError(f"config.yaml 缺少必填项: {missing}")

    base_dir = os.path.dirname(os.path.abspath(path))
    data = dict(data)
    for key in PATH_KEYS:
        if key in data:
            data[key] = _resolve_path(data[key], base_dir)

    if check_paths:
        for key in PATH_KEYS:
            p = data.get(key)
            if p and not os.path.exists(p):
                raise FileNotFoundError(f"配置项 {key} 指向的路径不存在: {p}")
    return Config(data, base_dir=base_dir)
