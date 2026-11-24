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


def _drain(cond, poll=0.01, deadline=1.0):
    """轮询等待 cond() 成立（回调在 watcher 线程异步触发）。"""
    t0 = time.time()
    while not cond() and time.time() - t0 < deadline:
        time.sleep(poll)


def test_start_plays_and_finish_callback(fake_music):
    got = []
    player = AudioPlayer(on_finished=got.append, poll_interval=0.01)
    assert player.start("demo.mp3") is True
    assert fake_music.loaded == "demo.mp3"
    fake_music.busy = False          # 模拟自然播完
    _drain(lambda: got)
    assert got == ["finished"]


def test_stop_interrupts_once(fake_music):
    got = []
    player = AudioPlayer(on_finished=got.append, poll_interval=0.01)
    player.start("demo.mp3")
    player.stop()
    player.stop()                    # 第二次应被忽略
    _drain(lambda: got)
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
    _drain(lambda: got)
    assert got == ["finished"]


def test_start_failure_returns_false(fake_music):
    def bad_load(_path):
        raise RuntimeError("no such file")

    fake_music.load = bad_load
    got = []
    player = AudioPlayer(on_finished=got.append, poll_interval=0.01)
    assert player.start("missing.mp3") is False
    time.sleep(0.05)                 # 给足时间确认不会回调
    assert got == []                 # 失败不应触发 finished/interrupted


# ===== 回归：can_resume 判定与设备异常不传播 =====

def test_can_resume_reflects_pause_state(fake_music):
    player = AudioPlayer(poll_interval=0.01)
    assert player.can_resume() is False      # 还没 start
    player.start("demo.mp3")
    assert player.can_resume() is False      # 播放中
    player.pause()
    assert player.can_resume() is True
    player.resume()
    assert player.can_resume() is False
    player.stop()
    assert player.can_resume() is False


def test_resume_failure_keeps_paused(fake_music):
    player = AudioPlayer(poll_interval=0.01)
    player.start("demo.mp3")
    player.pause()

    def bad_unpause():
        raise RuntimeError("音箱掉线")

    fake_music.unpause = bad_unpause
    assert player.resume() is False
    assert player.can_resume() is True       # 仍算可续播，交上层退避重试


def test_pause_failure_keeps_playing(fake_music):
    player = AudioPlayer(poll_interval=0.01)
    player.start("demo.mp3")

    def bad_pause():
        raise RuntimeError("设备掉线")

    fake_music.pause = bad_pause
    assert player.pause() is False           # 异常不外抛（否则会杀 mic 线程）
    assert player.can_resume() is False
