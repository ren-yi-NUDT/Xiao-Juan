# -*- coding: utf-8 -*-
"""LMAM 本地语音交互主应用（脱离 ROS2）。

由 lmam_node/lmam_node.py 改造：
- ROS 话题/动作   -> scripts/command_bus.dispatch 桩 + 本地播放器
- WS 推流 Orin    -> 本机扬声器播放（scripts/tts_local_player.py）
- 实机控制逻辑    -> 已置空（move_to/NG/manipulate/leave/start 由 dispatch 留桩，之后重写）
"""

import logging
import queue
import threading
import time

from scripts.audio_player import AudioPlayer
from scripts.command_bus import dispatch
from scripts.llm import LLM_ASSISTENT, parse_llm_result
from scripts.local_listener import VoiceListener
from scripts.tts_local_player import TTSLocalPlayer
from scripts.wakeup import ClientControlState, SharedState, XiaoYunKWS

log = logging.getLogger("lmam.app")


class LMAMApp:
    """唤醒 -> ASR -> LLM -> TTS 本机闭环；讲解 mp3 本机播放，支持打断续播。"""

    def __init__(self, cfg, listener=None, kws=None, assistant=None,
                 tts=None, player=None):
        self.cfg = cfg

        # ====== 状态机（原 SharedState / ClientControlState 原样保留） ======
        self.shared_state = SharedState(idle_timeout_sec=float(cfg.idle_timeout_sec))
        self.ctrl = ClientControlState()

        # 会话窗口（唤醒一次后 N 秒内不需要重复唤醒）
        self.session_hold_sec = float(cfg.session_hold_sec)
        self.awake_until_ts = 0.0

        # 静默计时
        self.last_activity_ts = time.time()

        # 讲解是否处于"断点待续播"
        self.guide_paused = False

        # 自动 resume 控制
        self.resume_inflight = False
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
        self.kws_rms_gate = float(cfg.kws_rms_gate)
        self.assistant = assistant or LLM_ASSISTENT(
            api_base=cfg.llm_api_base,
            embed_model_path=cfg.embed_model_path,
            db_file_path=cfg.museum_txt_path,
            vector_db_path=cfg.vector_db_path,
        )
        self.tts = tts or TTSLocalPlayer(
            config_path=cfg.tts_config_path,
            ckpt_path=cfg.tts_ckpt_path,
            device=cfg.tts_device,
            speed=float(cfg.tts_speed),
            sample_rate=int(cfg.tts_sample_rate),
        )

        # ====== 本地讲解播放器（替代 Orin audio_control） ======
        self.player = player or AudioPlayer(on_finished=self._on_audio_finished)

        # ====== 运行时字段（保留原命名） ======
        self.unvisited_landmarks = None
        self.audio_done_path = ""
        self.txt_command = ""
        self.idle_timeout = None
        self.last_command = None
        self.last_replytxt = None
        self.idle_txt = None
        self.current_landmark = "Landmark0"
        self.leave_send = False

        # ====== 线程间队列 / 线程控制 ======
        self.asr_text_queue = queue.Queue()
        self.mic_stop = threading.Event()
        self._consumer_stop = threading.Event()
        self._threads_started = False

        self._enter_idle("boot")

    # =========================
    # 生命周期
    # =========================
    def start(self):
        """启动 mic 线程与消费线程（构造函数不自动起线程，便于测试）。"""
        if self._threads_started:
            return
        self._threads_started = True
        threading.Thread(target=self._mic_worker, daemon=True).start()
        threading.Thread(target=self._asr_text_consumer, daemon=True).start()
        log.info("[LMAM] started. mic thread + consumer thread ready.")

    def shutdown(self):
        self.mic_stop.set()
        self._consumer_stop.set()
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
        log.info("[LMAM] shutdown complete.")

    # =========================
    # 调试 CLI 入口（main.py 调用）
    # =========================
    def audio_start(self, path: str) -> bool:
        """播放讲解音频（原 agent audio_start 命令的本地等价）。"""
        self._enter_idle("audio_start")
        self.guide_paused = False
        self.shared_state.set_audio_playing(True, None)
        ok = self.player.start(path)
        if not ok:
            self.shared_state.set_audio_playing(False, None)
        return ok

    def audio_stop(self):
        """打断全部本地播放（等价原 interrupt）。"""
        self.guide_paused = False
        self.player.interrupt()
        self.tts.stop()

    # =========================
    # mic worker（原逻辑；leave 自动发送已随实机控制置空删除）
    # =========================
    def _mic_worker(self):
        while not self.mic_stop.is_set():
            try:
                mode = self.shared_state.mode
            except Exception:
                mode = "IDLE"

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
                        # 1) 打断当前本地播放（mp3 讲解 -> interrupt；TTS -> stop）
                        self.player.interrupt()
                        self.tts.stop()

                        # 2) 标记：讲解断点待续播（静默后自动续播）
                        if self.shared_state.audio_playing:
                            self.guide_paused = True
                            self.shared_state.set_audio_playing(False, None)

                        # 3) 播唤醒提示语（独立线程，不阻塞 mic 循环）
                        threading.Thread(
                            target=self._play_wakeup_prompt,
                            args=(self.cfg.wakeup_prompt,), daemon=True).start()
                        # 4) 进入 ACTIVE
                        self._enter_active("wakeup")
                        self.idle_timeout = None
                        self.last_activity_ts = time.time()
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

                # 超时回到 IDLE
                if not self.shared_state.tts_playing:
                    self.idle_timeout = self.shared_state.maybe_back_to_idle()
                if (self.idle_timeout is not None and not self.guide_paused
                        and not self.shared_state.audio_playing
                        and not self.shared_state.tts_playing):
                    threading.Thread(
                        target=self._play_backtoIDLE_prompt,
                        args=(self.cfg.back_to_idle_prompt,), daemon=True).start()
                if self.shared_state.mode == "IDLE":
                    log.info("[LMAM] Back to IDLE")

            except Exception as e:
                log.error("[mic] error: %s", e)
                time.sleep(0.05)

    # =========================
    # ASR -> LLM -> TTS 消费线程（原 asyncio consumer 的线程版，串行语义一致）
    # =========================
    def _asr_text_consumer(self):
        while not self._consumer_stop.is_set():
            try:
                text = self.asr_text_queue.get(timeout=self.resume_check_period)
            except queue.Empty:
                self._resume_check()
                continue
            self._handle_text(text)

    def _handle_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        # 过滤词（原硬编码列表 -> config.asr_filter_words）
        if any(w in text for w in self.cfg.asr_filter_words):
            return
        # 只在 ACTIVE 才处理
        if self.shared_state.mode != "ACTIVE":
            return

        self.last_activity_ts = time.time()
        try:
            command, reply_text = self._run_llm(text)

            if command["action"] == "resume":
                self._auto_resume_mp3_once()
                return

            # 实机控制指令出口（当前为桩；move_to/NG/manipulate/leave/start/talk 都走这里）
            dispatch(command)

            # 播报 LLM 回复
            self._enter_idle("tts outgoing")
            self.shared_state.set_tts_playing(True, None)
            self._enter_idle("tts playing")
            self.tts.speak(reply_text)
        except Exception as e:
            log.error("[ASR->LLM->TTS] error: %s", e)

    def _run_llm(self, text: str):
        intent, ai_response = self.assistant.chat(
            text, self.unvisited_landmarks, self.current_landmark)
        return parse_llm_result(intent, ai_response)

    # =========================
    # 自动续播（原 _resume_check_cb / _auto_resume_mp3_once 的同步版）
    # =========================
    def _resume_check(self):
        if self.resume_inflight:
            return
        if not self.guide_paused:
            return
        if self.shared_state.tts_playing:
            return
        if self.only_resume_when_idle and self.shared_state.mode != "IDLE":
            return
        elapsed = time.time() - float(self.last_activity_ts)
        if elapsed >= self.pause_deadline_sec:
            self.resume_inflight = True
            log.info("[LMAM] silence window reached, auto-resume")
            try:
                self._auto_resume_mp3_once()
            finally:
                self.resume_inflight = False

    def _auto_resume_mp3_once(self):
        self.shared_state.set_tts_playing(True, None)
        self._enter_idle("orin playing")
        self.tts.speak("我继续为您讲解")
        ok = self.player.resume()
        if ok:
            self.shared_state.set_audio_playing(True, None)
            self.guide_paused = False
            log.info("[LMAM] auto-resume mp3 success -> guide_paused=False")
        else:
            log.warning("[LMAM] auto-resume mp3 failed -> will retry in next silence window")

    # =========================
    # 提示语播放（原协程改同步，由调用方放独立线程）
    # =========================
    def _play_wakeup_prompt(self, text: str = "您好，我在。"):
        try:
            self._enter_idle("wakeup prompt tts")
            self.tts.speak(text)
            self.idle_txt = None
        except Exception as e:
            log.warning("[wakeup_prompt] failed: %s", e)

    def _play_backtoIDLE_prompt(self, text: str = "如果您有任何问题请呼唤两声小娟唤醒我哦。"):
        try:
            self.idle_txt = text
            self._enter_idle("back to idle prompt tts")
            self.tts.speak(text)
        except Exception as e:
            log.warning("[backto_idle_prompt] failed: %s", e)

    # =========================
    # 播放完成回调（原 /audio_done 订阅的本地等价）
    # =========================
    def _on_audio_finished(self, status: str):
        if status in ("finished", "interrupted"):
            self.shared_state.set_audio_playing(False, None)
        if status != "finished":
            log.info("[LMAM] audio done: status=%s (ignored)", status)
            return
        log.info("[LMAM] audio finished, guide not paused anymore")
        # 讲解自然结束：不再待续播
        self.guide_paused = False

    # =========================
    # 模式切换 / 日志（原样，get_logger -> logging）
    # =========================
    def _enter_idle(self, reason: str = ""):
        self.shared_state.set_mode("IDLE")
        self.idle_timeout = time.time()
        log.info("[LMAM] -> IDLE (%s)", reason)

    def _enter_active(self, reason: str = ""):
        self.shared_state.wake()
        log.info("[LMAM] -> ACTIVE (%s)", reason)
