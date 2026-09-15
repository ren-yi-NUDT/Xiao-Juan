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
    "rapidfuzz": {"fuzz": None},  # None 表示在 _ensure 里特殊构造
}


def _make_fuzz_module():
    """无 rapidfuzz 时提供行为可预期的 partial_ratio：包含=100，否则 0。"""
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
    else:
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
