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
}

# 必须是异常类的属性
_EXCEPTION_ATTRS = {"WaitTimeoutError"}


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
    sys.modules[name] = _make_module(name, attr_names)
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
