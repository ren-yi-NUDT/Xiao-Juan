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
