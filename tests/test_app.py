# -*- coding: utf-8 -*-
import time as _time

from lmam.app import LMAMApp
from scripts.config import Config


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


def _make_app():
    cfg = Config({
        "wake_word": "小娟小娟", "asr_filter_words": ["志愿者", "字幕"],
        "session_hold_sec": 15.0, "auto_resume_silence_sec": 0.5,
        "resume_check_period": 0.2, "idle_timeout_sec": 10.0,
        "only_resume_when_idle": True, "wakeup_prompt": "您好，我在。",
        "back_to_idle_prompt": "回IDLE", "kws_rms_gate": 0.01,
    })
    tts = FakeTTS()
    player = FakePlayer()
    assistant = FakeAssistant()
    app = LMAMApp(cfg, listener=object(), kws=object(),
                  assistant=assistant, tts=tts, player=player)
    app.shared_state.set_mode("ACTIVE")
    return app, assistant, tts, player


def test_handle_text_dispatches_command_and_speaks():
    app, assistant, tts, player = _make_app()
    app._handle_text("带我去序厅")
    assert assistant.calls and assistant.calls[0][0] == "带我去序厅"
    assert tts.spoken == ["好的。"]       # 两行格式只播第一行
    assert ("resume",) not in player.actions


def test_handle_text_filters_words():
    app, assistant, tts, player = _make_app()
    app._handle_text("志愿者来了")
    assert assistant.calls == [] and tts.spoken == []


def test_handle_text_ignore_when_idle():
    app, assistant, tts, player = _make_app()
    app.shared_state.set_mode("IDLE")
    app._handle_text("你好呀")
    assert assistant.calls == []


def test_handle_text_resume_action():
    app, assistant, tts, player = _make_app()
    app.guide_paused = True
    assistant.intent, assistant.reply = "A", "我继续为您讲解\n/resume"
    app._handle_text("继续讲解")
    assert ("resume",) in player.actions
    assert app.guide_paused is False


def test_on_audio_finished_updates_state():
    app, _, _, _ = _make_app()
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


def test_resume_check_triggers_auto_resume():
    app, _, tts, player = _make_app()
    app.shared_state.set_mode("IDLE")
    app.guide_paused = True
    app.last_activity_ts = _time.time() - 10.0
    app._resume_check()
    assert ("resume",) in player.actions
    assert tts.spoken == ["我继续为您讲解"]
    assert app.guide_paused is False


def test_resume_check_skip_when_active():
    app, _, tts, player = _make_app()
    app.guide_paused = True
    app.last_activity_ts = _time.time() - 10.0
    app._resume_check()                   # mode==ACTIVE，且 only_resume_when_idle
    assert player.actions == []


# ===== 回归：唤醒打断必须走 pause（断点续播），而非 interrupt（review C1/C2） =====

def test_on_wake_pauses_player_and_sets_guide_paused():
    app, _, tts, player = _make_app()
    app.shared_state.set_mode("IDLE")
    app.shared_state.set_audio_playing(True, None)
    app._on_wake()
    assert ("pause",) in player.actions           # 断点保留，可 resume
    assert ("interrupt",) not in player.actions   # interrupt 会丢断点位置
    assert app.guide_paused is True               # 自动续播的唯一开关
    assert app.shared_state.audio_playing is False
    assert app.shared_state.mode == "ACTIVE"
    assert tts.stops >= 1                         # TTS 打断照旧


def test_on_wake_without_audio_skips_pause():
    app, _, _, player = _make_app()
    app.shared_state.set_mode("IDLE")             # 无 mp3 在播
    app._on_wake()
    assert player.actions == []
    assert app.guide_paused is False
    assert app.shared_state.mode == "ACTIVE"


# ===== 回归：TTS 播完必须清 tts_playing 并按原 /tts_playing=False 语义驱动状态机 =====

def test_handle_text_clears_tts_playing_and_stays_active():
    app, _, _, _ = _make_app()
    app._handle_text("带我去序厅")
    assert app.shared_state.tts_playing is False  # 不清除则后续轮次全部饿死
    assert app.shared_state.mode == "ACTIVE"      # 多轮：答完不需要再唤醒


def test_backto_idle_prompt_keeps_idle():
    app, _, _, _ = _make_app()
    app._play_backtoIDLE_prompt(app.cfg.back_to_idle_prompt)
    assert app.shared_state.tts_playing is False
    assert app.shared_state.mode == "IDLE"        # 回 IDLE 提示语后不重新激活


def test_auto_resume_clears_tts_playing_and_keeps_idle():
    app, _, _, player = _make_app()
    app.shared_state.set_mode("IDLE")
    app.guide_paused = True
    app._auto_resume_mp3_once()
    assert app.shared_state.tts_playing is False
    assert app.shared_state.audio_playing is True
    assert app.shared_state.mode == "IDLE"        # mp3 播放中保持 IDLE，可被唤醒打断
    assert app.guide_paused is False
