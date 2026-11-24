# -*- coding: utf-8 -*-
"""LMAM 语音前端主应用（前后端分离）。

- 唤醒（KWS）→ ASR → 问答后端（rag_backend HTTP/SSE）→ 本机 TTS
- 讲解 mp3 本机播放：唤醒打断暂停、静默后自动续播
- 问答/知识库/大模型全部在后端，前端不内置检索
"""

import logging
import queue
import re
import threading
import time

from scripts.audio_player import AudioPlayer
from scripts.rag_client import RagClient, RagError
from scripts.local_listener import VoiceListener
from scripts.tts_local_player import TTSLocalPlayer
from scripts.wakeup import ClientControlState, SharedState, XiaoYunKWS

log = logging.getLogger("lmam.app")

# 后端不可用时的降级播报（SRS 3.3.5：服务异常要给用户可听懂的提示）
RAG_FALLBACK_REPLY = "抱歉，知识库服务暂时不可用，请稍后再试。"

_SENT_END = "。！？!?；;\n"


def _split_complete_sentences(text: str):
    """切出已完结的句子，返回 (句子列表, 未完结的尾巴)。"""
    sentences = []
    start = 0
    for i, ch in enumerate(text):
        if ch in _SENT_END:
            s = text[start:i + 1].strip()
            if s:
                sentences.append(s)
            start = i + 1
    return sentences, text[start:]


class LMAMApp:
    """唤醒 -> ASR -> 问答后端 -> TTS 本机闭环；讲解 mp3 支持打断续播。"""

    def __init__(self, cfg, listener=None, kws=None, rag=None,
                 tts=None, player=None):
        self.cfg = cfg

        # ====== 状态机 ======
        self.shared_state = SharedState(idle_timeout_sec=float(cfg.idle_timeout_sec))
        self.ctrl = ClientControlState()

        # 静默计时（自动续播的静默窗口起点）
        self.last_activity_ts = time.time()

        # 讲解是否处于"断点待续播"
        self.guide_paused = False

        # 流式播报打断标志：唤醒/停止后不再把后续句子送去 TTS
        self._speak_cancel = threading.Event()

        # 问答串行化：mic 消费线程与 CLI 的 text_ask 可能同时答，必须排队
        self._answer_lock = threading.Lock()

        # 自动续播参数
        self.pause_deadline_sec = float(cfg.auto_resume_silence_sec)
        self.resume_check_period = float(cfg.resume_check_period)
        self.only_resume_when_idle = bool(cfg.only_resume_when_idle)

        # ====== 组件（支持注入，便于测试；默认构造真实组件） ======
        self.local_listener = listener or VoiceListener(
            model_path_or_size=cfg.asr_model_path,
            device=cfg.asr_device,
            mic_device_name=cfg.mic_device_name,
        )
        self.kws = kws or XiaoYunKWS(
            sample_rate=16000,
            keyword=cfg.wake_word,
            model_path=cfg.kws_model_path,
            device=cfg.kws_device,
        )
        self.rag = rag or RagClient(
            api_base=cfg.rag_api_base,
            area_id=cfg.rag_area_id,
            timeout_sec=float(cfg.rag_timeout_sec),
            session_id=cfg.rag_session_id,
        )
        self.tts = tts or TTSLocalPlayer(
            config_path=cfg.tts_config_path,
            ckpt_path=cfg.tts_ckpt_path,
            device=cfg.tts_device,
            speed=float(cfg.tts_speed),
        )

        # ====== 本地讲解播放器 ======
        self.player = player or AudioPlayer(on_finished=self._on_audio_finished)

        # ====== 线程间队列 / 线程控制 ======
        self.asr_text_queue = queue.Queue()
        self.mic_stop = threading.Event()
        self._consumer_stop = threading.Event()
        self._threads_started = False
        self._mic_thread = None
        self._consumer_thread = None

        self._enter_idle("boot")

    # =========================
    # 生命周期
    # =========================
    def start(self):
        """启动 mic 线程与消费线程（构造函数不自动起线程，便于测试）。"""
        if self._threads_started:
            return
        self._threads_started = True
        self._mic_thread = threading.Thread(
            target=self._mic_worker, daemon=True, name="mic")
        self._consumer_thread = threading.Thread(
            target=self._asr_text_consumer, daemon=True, name="asr-consumer")
        self._mic_thread.start()
        self._consumer_thread.start()
        log.info("[LMAM] started. mic thread + consumer thread ready.")

    def shutdown(self):
        self.mic_stop.set()
        self._consumer_stop.set()
        self._speak_cancel.set()
        try:
            self.player.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.tts.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.local_listener.destroy()
        except Exception:  # noqa: BLE001
            pass
        # 等工作线程收尾（mic 可能阻塞在单次收音里，给个上限即可）
        for t in (self._mic_thread, self._consumer_thread):
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
        log.info("[LMAM] shutdown complete.")

    # =========================
    # 调试 CLI 入口（main.py 调用）
    # =========================
    def audio_start(self, path: str) -> bool:
        """播放讲解音频。"""
        self._enter_idle("audio_start")
        self.guide_paused = False
        self.shared_state.set_audio_playing(True)
        ok = self.player.start(path)
        if not ok:
            self.shared_state.set_audio_playing(False)
        return ok

    def audio_stop(self):
        """打断全部本地播放。"""
        self.guide_paused = False
        self._speak_cancel.set()
        self.player.interrupt()
        self.tts.stop()

    def text_ask(self, text: str):
        """无麦克风调试：按真实链路走 唤醒态 -> 问答 -> TTS，返回回答文本。"""
        self._enter_active("cli text")
        self.last_activity_ts = time.time()
        return self._handle_text(text)

    def _on_wake(self):
        """唤醒：暂停讲解断点待续播、停 TTS、进 ACTIVE。

        注意顺序：必须先判断 audio_playing 再暂停——pause() 保留断点位置；
        若先 interrupt()，其同步回调会把 audio_playing 清掉，guide_paused 永远置不上，
        自动续播（断点续播语义）即失效。
        """
        self._speak_cancel.set()
        if self.shared_state.audio_playing:
            self.player.pause()
            self.guide_paused = True
            self.shared_state.set_audio_playing(False)
        self.tts.stop()
        self._enter_active("wakeup")
        self.last_activity_ts = time.time()

    # =========================
    # mic worker：IDLE 只跑 KWS，ACTIVE 跑 ASR
    # =========================
    def _mic_worker(self):
        while not self.mic_stop.is_set():
            mode = self.shared_state.mode

            # ========== IDLE：只做 KWS ==========
            if mode == "IDLE":
                try:
                    pcm = self.local_listener.read_kws_pcm_16k(duration_sec=0.2)
                except Exception as e:
                    log.warning("[KWS] read_kws_pcm_16k failed: %s", e)
                    time.sleep(0.05)
                    continue

                if self.kws.feed(pcm):
                    if self.ctrl.can_send("WAKE", min_interval=2.0):
                        log.info("[LMAM] wake word detected -> interrupt playback")
                        self._on_wake()
                        # 播唤醒提示语（独立线程，不阻塞 mic 循环；播完回 ACTIVE 保持多轮）
                        self._speak_prompt_async(self.cfg.wakeup_prompt, reactivate=True)
                continue

            # ========== ACTIVE：ASR ==========
            try:
                try:
                    self.local_listener.close_kws_stream()
                except Exception:
                    pass

                result_text = self.local_listener.listen_and_transcribe()
                if result_text and result_text.strip():
                    self.asr_text_queue.put(result_text.strip())

                # 超时回到 IDLE（idle_ts 仅表示本周期 maybe_back_to_idle 是否刚翻转）
                idle_ts = None
                if not self.shared_state.tts_playing:
                    idle_ts = self.shared_state.maybe_back_to_idle()
                if (idle_ts is not None and not self.guide_paused
                        and not self.shared_state.audio_playing
                        and not self.shared_state.tts_playing):
                    # 回 IDLE 提示语（播完后保持 IDLE，不重新激活）
                    self._speak_prompt_async(self.cfg.back_to_idle_prompt, reactivate=False)
                if self.shared_state.mode == "IDLE":
                    log.info("[LMAM] Back to IDLE")

            except Exception as e:
                log.error("[mic] error: %s", e)
                time.sleep(0.05)

    # =========================
    # ASR -> 问答后端 -> TTS 消费线程（串行语义）
    # =========================
    def _asr_text_consumer(self):
        while not self._consumer_stop.is_set():
            try:
                text = self.asr_text_queue.get(timeout=self.resume_check_period)
            except queue.Empty:
                self._resume_check()
                continue
            try:
                self._handle_text(text)
            except Exception as e:  # noqa: BLE001
                # 兜底：消费线程绝不能因单条文本异常而死
                log.error("[consumer] _handle_text error: %s", e)

    def _handle_text(self, text: str):
        """过滤 -> 仅 ACTIVE -> 后端问答（句级边收边播）-> 补播尾部。

        用 _answer_lock 串行化所有调用方（mic 消费线程 / CLI text_ask）：
        两个回答若并行，会交错送进 TTS 并互相清掉 _speak_cancel。
        """
        with self._answer_lock:
            return self._handle_text_locked(text)

    def _handle_text_locked(self, text: str):
        text = (text or "").strip()
        if not text:
            return None
        # 过滤词（原硬编码列表 -> config.asr_filter_words）
        if any(w in text for w in self.cfg.asr_filter_words):
            return None
        # 只在 ACTIVE 才处理
        if self.shared_state.mode != "ACTIVE":
            return None

        self.last_activity_ts = time.time()
        t0 = time.time()
        self._speak_cancel.clear()

        buf = ""
        spoken: list[str] = []

        def on_delta(piece: str):
            """收到增量文本：凑满一句就立刻送 TTS，降低首音延迟。"""
            nonlocal buf
            if self._speak_cancel.is_set() or not piece:
                return
            buf += piece
            sentences, buf = _split_complete_sentences(buf)
            for sent in sentences:
                if self._speak_cancel.is_set():
                    return
                spoken.append(sent)
                self.tts.speak(sent)

        # 整个流式回答期间保持 tts_playing，避免静默超时误判；mode 置 IDLE 让 KWS 可打断
        self.shared_state.set_tts_playing(True)
        self._enter_idle("streaming answer")
        try:
            answer = self.rag.ask(text, on_delta=on_delta)
        except RagError as e:
            log.error("[RAG] 问答失败: %s", e)
            self.shared_state.set_tts_playing(False)
            if not self._speak_cancel.is_set():
                self._speak(RAG_FALLBACK_REPLY)
            return None
        except Exception as e:  # noqa: BLE001
            log.error("[RAG] 未预期异常: %s", e)
            self.shared_state.set_tts_playing(False)
            if not self._speak_cancel.is_set():
                self._speak(RAG_FALLBACK_REPLY)
            return None

        # done.answer 是权威全文：把尚未播出的尾部补上
        spoken_text = "".join(spoken)
        if answer.answer.startswith(spoken_text):
            remainder = answer.answer[len(spoken_text):]
        elif not spoken_text:
            remainder = answer.answer
        else:
            remainder = ""
            log.warning("[RAG] 流式文本与最终回答不一致，跳过补播")
        if remainder.strip() and not self._speak_cancel.is_set():
            spoken.append(remainder)
            self.tts.speak(remainder)

        log.info("[RAG] answer (%d chars, model=%s, %.2fs, session=%s): %s",
                 len(answer.answer), answer.model, time.time() - t0,
                 answer.session_id, answer.answer[:80])
        self._on_tts_finished(True)
        return answer.answer

    # =========================
    # 自动续播
    # =========================
    def _resume_check(self):
        if not self.guide_paused:
            return
        if self.shared_state.tts_playing:
            return
        if self.only_resume_when_idle and self.shared_state.mode != "IDLE":
            return
        if time.time() - float(self.last_activity_ts) >= self.pause_deadline_sec:
            log.info("[LMAM] silence window reached, auto-resume")
            self._auto_resume_mp3_once()

    def _auto_resume_mp3_once(self):
        # 播报续播提示并保持 IDLE（reactivate=False），随后从断点续播 mp3
        self._speak("我继续为您讲解", reactivate=False)
        ok = self.player.resume()
        if ok:
            self.shared_state.set_audio_playing(True)
            self.guide_paused = False
            log.info("[LMAM] auto-resume mp3 success -> guide_paused=False")
        else:
            log.warning("[LMAM] auto-resume mp3 failed -> will retry in next silence window")

    # =========================
    # TTS 播报 + 状态机驱动
    # =========================
    def _speak(self, text: str, reactivate: bool = True):
        """播报一段 TTS：开始前置 tts_playing，结束后按回调语义驱动状态机。

        try/finally 保证即使注入的 TTS 实现抛异常，tts_playing 也一定被清除，
        否则 _resume_check 与回 IDLE 判定会被永久卡死。
        """
        self.shared_state.set_tts_playing(True)
        self._enter_idle("tts playing")
        try:
            self.tts.speak(text)
        finally:
            self._on_tts_finished(reactivate)

    def _on_tts_finished(self, reactivate: bool = True):
        """TTS 播完：无音频在播且需要时回 ACTIVE（多轮关键）。"""
        self.shared_state.set_tts_playing(False)
        if self.shared_state.audio_playing:
            self._enter_idle("audio playing")
            return
        if reactivate:
            self._enter_active("no audio playing")
        self.shared_state.on_user_voice()

    # =========================
    # 提示语播放（独立线程，不阻塞调用线程）
    # =========================
    def _speak_prompt_async(self, text: str, reactivate: bool):
        threading.Thread(target=self._speak_prompt, args=(text, reactivate),
                         daemon=True).start()

    def _speak_prompt(self, text: str, reactivate: bool):
        try:
            self._speak(text, reactivate=reactivate)
        except Exception as e:
            log.warning("[prompt] speak failed: %s", e)

    # =========================
    # 播放完成回调
    # =========================
    def _on_audio_finished(self, status: str):
        # AudioPlayer 只回调 "finished" / "interrupted" 两种状态，播放状态一律清除
        self.shared_state.set_audio_playing(False)
        if status != "finished":
            log.info("[LMAM] audio done: status=%s（被打断：断点待续播由唤醒路径标记）", status)
            return
        log.info("[LMAM] audio finished, guide not paused anymore")
        # 讲解自然结束：不再待续播
        self.guide_paused = False

    # =========================
    # 模式切换 / 日志
    # =========================
    def _enter_idle(self, reason: str = ""):
        self.shared_state.set_mode("IDLE")
        log.info("[LMAM] -> IDLE (%s)", reason)

    def _enter_active(self, reason: str = ""):
        self.shared_state.wake()
        log.info("[LMAM] -> ACTIVE (%s)", reason)
