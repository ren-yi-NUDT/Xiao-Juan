# -*- coding: utf-8 -*-
import time as _time

from lmam.app import LMAMApp, RAG_FALLBACK_REPLY
from scripts.config import Config
from scripts.rag_client import RagAnswer, RagError


class FakeRag:
    def __init__(self, answer="灵山大佛通高八十八米。", error=None, deltas=None):
        self.answer = answer
        self.error = error
        self.deltas = deltas or []
        self.calls = []

    def ask(self, text, on_delta=None):
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        if on_delta is not None:
            for piece in self.deltas:
                on_delta(piece)
        return RagAnswer(answer=self.answer)


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


def _make_app(rag=None, active=True):
    cfg = Config({
        "wake_word": "小娟小娟", "asr_filter_words": ["志愿者", "字幕"],
        "auto_resume_silence_sec": 0.5,
        "resume_check_period": 0.2, "idle_timeout_sec": 10.0,
        "only_resume_when_idle": True, "wakeup_prompt": "您好，我在。",
        "back_to_idle_prompt": "回IDLE",
    })
    tts = FakeTTS()
    player = FakePlayer()
    rag = rag or FakeRag()
    app = LMAMApp(cfg, listener=object(), kws=object(),
                  rag=rag, tts=tts, player=player)
    if active:
        app.shared_state.set_mode("ACTIVE")
    return app, rag, tts, player


def test_handle_text_asks_rag_and_speaks_answer():
    app, rag, tts, _ = _make_app()
    app._handle_text("灵山大佛有多高")
    assert rag.calls == ["灵山大佛有多高"]
    assert tts.spoken == ["灵山大佛通高八十八米。"]


def test_streaming_speaks_sentences_in_order():
    rag = FakeRag(
        answer="第一句。第二句。",
        deltas=["第一句。", "第二句。"],
    )
    app, _, tts, _ = _make_app(rag=rag)
    app._handle_text("介绍一下灵山")
    assert tts.spoken == ["第一句。", "第二句。"]   # 边收边播，不重复整段


def test_streaming_remainder_spoken_from_done():
    rag = FakeRag(
        answer="第一句。第二句。",
        deltas=["第一句。"],                       # done 里还有未流出的尾部
    )
    app, _, tts, _ = _make_app(rag=rag)
    app._handle_text("介绍一下灵山")
    assert tts.spoken == ["第一句。", "第二句。"]


def test_handle_text_filters_words():
    app, rag, tts, _ = _make_app()
    app._handle_text("志愿者来了")
    assert rag.calls == [] and tts.spoken == []


def test_handle_text_ignore_when_idle():
    app, rag, tts, _ = _make_app(active=False)
    app._handle_text("你好呀")
    assert rag.calls == [] and tts.spoken == []


def test_text_ask_enters_active_and_speaks():
    app, rag, tts, _ = _make_app(active=False)
    answer = app.text_ask("灵山的门票多少钱")
    assert app.shared_state.mode == "ACTIVE"
    assert rag.calls == ["灵山的门票多少钱"]
    assert answer == "灵山大佛通高八十八米。"
    assert tts.spoken == [answer]


def test_rag_failure_speaks_apology_and_stays_alive():
    app, _, tts, _ = _make_app(rag=FakeRag(error=RagError("backend down")))
    app._handle_text("灵山的门票多少钱")
    assert tts.spoken == [RAG_FALLBACK_REPLY]
    assert app.shared_state.tts_playing is False
    assert app.shared_state.mode == "ACTIVE"


def test_on_audio_finished_updates_state():
    app, _, _, _ = _make_app()
    app.shared_state.set_audio_playing(True)
    app.guide_paused = True
    app._on_audio_finished("finished")
    assert app.shared_state.audio_playing is False
    assert app.guide_paused is False
    app.shared_state.set_audio_playing(True)
    app.guide_paused = True
    app._on_audio_finished("interrupted")
    assert app.shared_state.audio_playing is False
    assert app.guide_paused is True       # interrupted 不清除待续播


def test_resume_check_triggers_auto_resume():
    app, _, tts, player = _make_app(active=False)
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


# ===== 回归：唤醒打断必须走 pause（断点续播），而非 interrupt =====

def test_on_wake_pauses_player_and_sets_guide_paused():
    app, _, tts, player = _make_app(active=False)
    app.shared_state.set_audio_playing(True)
    app._on_wake()
    assert ("pause",) in player.actions           # 断点保留，可 resume
    assert ("interrupt",) not in player.actions   # interrupt 会丢断点位置
    assert app.guide_paused is True               # 自动续播的唯一开关
    assert app.shared_state.audio_playing is False
    assert app.shared_state.mode == "ACTIVE"
    assert tts.stops >= 1                         # TTS 打断照旧
    assert app._speak_cancel.is_set()             # 后续流式句子不再播


def test_on_wake_without_audio_skips_pause():
    app, _, _, player = _make_app(active=False)   # 无 mp3 在播
    app._on_wake()
    assert player.actions == []
    assert app.guide_paused is False
    assert app.shared_state.mode == "ACTIVE"


# ===== 回归：TTS 播完必须清 tts_playing 并驱动状态机 =====

def test_handle_text_clears_tts_playing_and_stays_active():
    app, _, _, _ = _make_app()
    app._handle_text("灵山大佛有多高")
    assert app.shared_state.tts_playing is False  # 不清除则后续轮次全部饿死
    assert app.shared_state.mode == "ACTIVE"      # 多轮：答完不需要再唤醒


def test_backto_idle_prompt_keeps_idle():
    app, _, _, _ = _make_app()
    app._speak_prompt(app.cfg.back_to_idle_prompt, reactivate=False)
    assert app.shared_state.tts_playing is False
    assert app.shared_state.mode == "IDLE"        # 回 IDLE 提示语后不重新激活


def test_auto_resume_clears_tts_playing_and_keeps_idle():
    app, _, _, player = _make_app(active=False)
    app.guide_paused = True
    app._auto_resume_mp3_once()
    assert app.shared_state.tts_playing is False
    assert app.shared_state.audio_playing is True
    assert app.shared_state.mode == "IDLE"        # mp3 播放中保持 IDLE，可被唤醒打断
    assert app.guide_paused is False
