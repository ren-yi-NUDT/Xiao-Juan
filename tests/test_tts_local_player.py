# -*- coding: utf-8 -*-
import numpy as np

from scripts import tts_local_player as tl


class FakePlayerModule:
    """模拟 sounddevice 的 play/is_playing/stop/wait。

    is_playing 在 play 后的前 2 次查询返回 True，之后返回 False，
    模拟"播放一小段后自然结束"，保证 speak() 的轮询循环能退出。
    """

    calls = []
    playing = False
    _ticks = 0

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.playing = False
        cls._ticks = 0

    @classmethod
    def play(cls, data, sr):
        cls.calls.append(("play", data.shape, sr))
        cls.playing = True
        cls._ticks = 2

    @classmethod
    def is_playing(cls):
        if cls._ticks > 0:
            cls._ticks -= 1
            return True
        cls.playing = False
        return False

    @classmethod
    def stop(cls):
        cls.calls.append(("stop",))
        cls.playing = False
        cls._ticks = 0


def _make_player():
    player = tl.TTSLocalPlayer.__new__(tl.TTSLocalPlayer)  # 跳过 melo 加载
    player._stop_flag = tl.threading.Event()
    player._speak_lock = tl.threading.Lock()
    return player


def test_speak_empty_text_noop(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    player = _make_player()
    player.speak("")   # 不应抛异常也不应调 play
    assert FakePlayerModule.calls == []


def test_speak_plays_audio(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    monkeypatch.setattr(tl, "sf", type("SF", (), {
        "read": staticmethod(lambda buf, dtype: (np.zeros(100, dtype="float32"), 22050))}))
    monkeypatch.setattr(tl.TTSLocalPlayer, "_run_tts_to_bytes",
                        lambda self, text: b"wav")
    player = _make_player()
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
    player = _make_player()

    real_is_playing = FakePlayerModule.is_playing

    def playing_then_stop():
        player._stop_flag.set()      # 第一次检查就触发停止
        return real_is_playing()

    monkeypatch.setattr(FakePlayerModule, "is_playing",
                        staticmethod(playing_then_stop))
    player.speak("长句播报")
    assert ("stop",) in FakePlayerModule.calls
