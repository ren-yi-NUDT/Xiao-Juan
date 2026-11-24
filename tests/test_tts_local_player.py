# -*- coding: utf-8 -*-
import threading
import time

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
    player._stop_gen = 0
    player._stop_gen_lock = tl.threading.Lock()
    player._speak_lock = tl.threading.Lock()
    return player


def _stub_decode(monkeypatch):
    """伪造 sf.read 与 TTS 合成，避免真实音频路径。"""
    monkeypatch.setattr(tl, "sf", type("SF", (), {
        "read": staticmethod(lambda buf, dtype: (np.zeros(100, dtype="float32"), 22050))}))
    monkeypatch.setattr(tl.TTSLocalPlayer, "_run_tts_to_bytes",
                        lambda self, text: b"wav")


def _plays():
    return [c for c in FakePlayerModule.calls if c[0] == "play"]


def _wait_until(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_speak_empty_text_noop(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    player = _make_player()
    player.speak("")   # 不应抛异常也不应调 play
    assert FakePlayerModule.calls == []


def test_speak_plays_audio(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    _stub_decode(monkeypatch)
    player = _make_player()
    player.speak("你好")
    kinds = [c[0] for c in FakePlayerModule.calls]
    assert "play" in kinds


def test_stop_breaks_speak(monkeypatch):
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    _stub_decode(monkeypatch)
    player = _make_player()

    real_is_playing = FakePlayerModule.is_playing

    def playing_then_stop():
        player.stop()                # 第一次检查就触发停止
        return real_is_playing()

    monkeypatch.setattr(FakePlayerModule, "is_playing",
                        staticmethod(playing_then_stop))
    player.speak("长句播报")
    assert ("stop",) in FakePlayerModule.calls


def test_stop_during_synthesis_skips_playback(monkeypatch):
    """stop() 落在 TTS 合成期间时，这段音频不应该再播出来。"""
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    _stub_decode(monkeypatch)
    player = _make_player()

    def synth_then_stop(self, text):
        player.stop()                # 合成耗时期间用户唤醒插话
        return b"wav"

    monkeypatch.setattr(tl.TTSLocalPlayer, "_run_tts_to_bytes", synth_then_stop)
    player.speak("不该播出来的一句")
    assert _plays() == []
    assert FakePlayerModule.calls == []


def test_stop_cancels_queued_speak(monkeypatch):
    """已经有播报在等 _speak_lock 时，stop() 也要让排队的那条作废。"""
    FakePlayerModule.reset()
    monkeypatch.setattr(tl, "sd", FakePlayerModule)
    _stub_decode(monkeypatch)
    player = _make_player()

    gate = threading.Event()
    real_is_playing = FakePlayerModule.is_playing

    def blocked_is_playing():
        gate.wait(3)                 # 第一条播报卡在"正在播"
        return real_is_playing()

    monkeypatch.setattr(FakePlayerModule, "is_playing",
                        staticmethod(blocked_is_playing))

    # 记录每次 speak() 进锁前取代次的时机，用来确定第二条已排队
    snapshots = []
    real_gen = player._current_gen

    def traced_gen():
        gen = real_gen()
        snapshots.append(gen)
        return gen

    player._current_gen = traced_gen

    t1 = threading.Thread(target=player.speak, args=("第一句",))
    t1.start()
    assert _wait_until(lambda: len(snapshots) >= 1)
    t2 = threading.Thread(target=player.speak, args=("第二句",))
    t2.start()
    assert _wait_until(lambda: len(snapshots) >= 2)
    player.stop()                    # 第一句与排队的第二句都作废
    gate.set()
    t1.join(3)
    t2.join(3)

    assert len(_plays()) == 1        # 第二句没有被播出来
    assert ("stop",) in FakePlayerModule.calls
