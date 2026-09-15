# -*- coding: utf-8 -*-
import textwrap

import pytest

from scripts.config import load_config

MINIMAL_YAML = textwrap.dedent("""
    wake_word: "小娟小娟"
    kws_model_path: "{tmp}/kws"
    asr_model_path: "{tmp}/asr"
    llm_api_base: "http://127.0.0.1:8088/v1"
""")


def _tmp(tmp_path):
    # Windows 反斜杠在 YAML 双引号标量里会被当转义序列，统一用正斜杠
    return str(tmp_path).replace("\\", "/")


def _write_cfg(tmp_path, extra=""):
    for d in ("kws", "asr"):
        (tmp_path / d).mkdir()
    content = MINIMAL_YAML.format(tmp=_tmp(tmp_path)) + extra
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    return str(cfg_file)


def test_load_minimal_config(tmp_path):
    cfg = load_config(_write_cfg(tmp_path), check_paths=True)
    assert cfg.wake_word == "小娟小娟"
    assert cfg.llm_api_base == "http://127.0.0.1:8088/v1"


def test_missing_required_key_raises(tmp_path):
    bad = MINIMAL_YAML.format(tmp=_tmp(tmp_path)).replace('llm_api_base: "http://127.0.0.1:8088/v1"', "")
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text(bad, encoding="utf-8")
    with pytest.raises(KeyError):
        load_config(str(cfg_file), check_paths=False)


def test_missing_model_path_raises_when_check(tmp_path):
    (tmp_path / "kws").mkdir()
    content = MINIMAL_YAML.format(tmp=_tmp(tmp_path)).replace(
        f"{_tmp(tmp_path)}/asr", f"{_tmp(tmp_path)}/not_exist")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_config(str(cfg_file), check_paths=True)


def test_check_paths_false_skips(tmp_path):
    content = MINIMAL_YAML.format(tmp=_tmp(tmp_path)).replace(
        f"{_tmp(tmp_path)}/kws", f"{_tmp(tmp_path)}/nope")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    cfg = load_config(str(cfg_file), check_paths=False)
    assert cfg.kws_model_path.endswith("nope")
