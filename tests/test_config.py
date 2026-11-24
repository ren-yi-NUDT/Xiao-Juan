# -*- coding: utf-8 -*-
import textwrap

import pytest

from scripts.config import load_config, resolve_device

MINIMAL_YAML = textwrap.dedent("""
    wake_word: "小娟小娟"
    kws_model_path: "{base}/kws"
    kws_device: "cpu"
    asr_model_path: "{base}/asr"
    asr_device: "auto"
    mic_device_name: ""
    tts_config_path: "{base}/melo/config.json"
    tts_ckpt_path: "{base}/melo/checkpoint.pth"
    tts_device: "cpu"
    tts_speed: 1.0
    rag_api_base: "http://127.0.0.1:8765"
    rag_area_id: "lingshan"
    rag_timeout_sec: 15.0
    rag_session_id: ""
    auto_resume_silence_sec: 0.5
    resume_check_period: 0.2
    only_resume_when_idle: true
    idle_timeout_sec: 10.0
    wakeup_prompt: "您好，我在。"
    back_to_idle_prompt: "回IDLE"
    asr_filter_words: []
""")


def _tmp(tmp_path):
    # Windows 反斜杠在 YAML 双引号标量里会被当转义序列，统一用正斜杠
    return str(tmp_path).replace("\\", "/")


def _write_cfg(tmp_path, extra=""):
    for d in ("kws", "asr", "melo"):
        (tmp_path / d).mkdir()
    (tmp_path / "melo" / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "melo" / "checkpoint.pth").write_bytes(b"")
    content = MINIMAL_YAML.format(base=_tmp(tmp_path)) + extra
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    return str(cfg_file)


def test_load_minimal_config(tmp_path):
    cfg = load_config(_write_cfg(tmp_path), check_paths=True)
    assert cfg.wake_word == "小娟小娟"
    assert cfg.rag_area_id == "lingshan"
    assert cfg.mic_device_name == ""


def test_missing_required_key_raises(tmp_path):
    bad = MINIMAL_YAML.format(base=_tmp(tmp_path)).replace(
        'rag_api_base: "http://127.0.0.1:8765"', "")
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text(bad, encoding="utf-8")
    with pytest.raises(KeyError):
        load_config(str(cfg_file), check_paths=False)


def test_missing_model_path_raises_when_check(tmp_path):
    (tmp_path / "kws").mkdir()
    content = MINIMAL_YAML.format(base=_tmp(tmp_path)).replace(
        f"{_tmp(tmp_path)}/asr", f"{_tmp(tmp_path)}/not_exist")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_config(str(cfg_file), check_paths=True)


def test_check_paths_false_skips(tmp_path):
    content = MINIMAL_YAML.format(base=_tmp(tmp_path)).replace(
        f"{_tmp(tmp_path)}/kws", f"{_tmp(tmp_path)}/nope")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    cfg = load_config(str(cfg_file), check_paths=False)
    assert cfg.kws_model_path.endswith("nope")


def test_relative_paths_resolve_against_config_dir(tmp_path):
    content = MINIMAL_YAML.format(base="rel")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    cfg = load_config(str(cfg_file), check_paths=False)
    assert cfg.kws_model_path == str(tmp_path / "rel" / "kws")


def test_resolve_device_explicit():
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("cuda") == "cuda"


def test_resolve_device_auto_uses_probe():
    assert resolve_device("auto", probe=lambda: True) == "cuda"
    assert resolve_device("auto", probe=lambda: False) == "cpu"


def test_resolve_device_auto_probe_failure_falls_back_cpu():
    def boom():
        raise RuntimeError("no cuda")

    assert resolve_device("auto", probe=boom) == "cpu"


def test_resolve_device_rejects_unknown():
    with pytest.raises(ValueError):
        resolve_device("tpu")
