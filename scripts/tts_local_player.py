# -*- coding: utf-8 -*-
"""本地 TTS 播放器：MeloTTS 生成 wav + sounddevice 本机扬声器播放。

由 scripts/tts_ws_streamer.py 改造：删除 WebSocket 推流，改为本机播放。
speak(text) 阻塞至播完（与原 await 语义一致）；stop() 可从其它线程打断。
"""

import io
import logging
import os
import tempfile
import threading
import time

import sounddevice as sd
import soundfile as sf

from scripts.config import resolve_device

log = logging.getLogger("lmam.tts")


class TTSLocalPlayer:
    def __init__(
        self,
        config_path: str,
        ckpt_path: str,
        device: str = "auto",
        language: str = "ZH",
        speaker_key: str = "ZH",
        speed: float = 1.0,
    ):
        self.speed = speed
        # 延迟导入：melo 加载很重，--check/单测不需要
        from melo.api import TTS
        resolved = resolve_device(device)
        try:
            self.tts = TTS(
                language=language,
                device=resolved,
                use_hf=False,
                config_path=config_path,
                ckpt_path=ckpt_path,
            )
        except Exception as e:  # noqa: BLE001
            if resolved != "cuda":
                raise
            log.warning("MeloTTS CUDA 初始化失败（%s），回退 CPU", e)
            self.tts = TTS(
                language=language,
                device="cpu",
                use_hf=False,
                config_path=config_path,
                ckpt_path=ckpt_path,
            )
        self.speaker_ids = self.tts.hps.data.spk2id
        if speaker_key not in self.speaker_ids:
            raise ValueError(
                f"speaker_key='{speaker_key}' not in {list(self.speaker_ids.keys())}")
        self.speaker_id = self.speaker_ids[speaker_key]
        # 打断用「代次计数」而不是 Event：speak() 会先排队等 _speak_lock，
        # 若用 Event 并在拿到锁后 clear，排队期间发生的 stop() 会被吞掉。
        self._stop_gen = 0
        self._stop_gen_lock = threading.Lock()
        # 串行化 speak：melo 推理非线程安全，sd.play 是全局流（原版由 asyncio 串行）
        self._speak_lock = threading.Lock()

    def _run_tts_to_bytes(self, text: str) -> bytes:
        """同步：TTS -> wav bytes（melo 只支持写文件，落系统临时目录并及时清理）。"""
        tmp_wav = f"{tempfile.gettempdir()}/tts_{int(time.time() * 1000)}.wav"
        try:
            self.tts.tts_to_file(text, self.speaker_id, tmp_wav, speed=self.speed)
            with open(tmp_wav, "rb") as f:
                return f.read()
        finally:
            try:
                os.remove(tmp_wav)
            except OSError:
                pass

    def speak(self, text: str) -> None:
        """阻塞式播报；stop() 可打断。多线程调用时按先后串行播报。"""
        if not text:
            return
        # 进锁前记下代次：之后任何 stop() 都会让这条播报作废
        gen = self._current_gen()
        with self._speak_lock:
            if gen != self._current_gen():
                log.debug("[TTSLocalPlayer] 播报已取消（排队中）: %s", text[:20])
                return
            try:
                wav_bytes = self._run_tts_to_bytes(text)
                data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
                if gen != self._current_gen():
                    log.debug("[TTSLocalPlayer] 播报已取消（合成期间打断）: %s", text[:20])
                    return
                sd.play(data, sr)
                while sd.is_playing() and gen == self._current_gen():
                    time.sleep(0.05)
                sd.stop()
            except Exception as e:
                log.error("[TTSLocalPlayer] speak 失败: %s", e)

    def stop(self) -> None:
        """打断当前播报，并让排队等锁的播报一并作废。"""
        with self._stop_gen_lock:
            self._stop_gen += 1

    def _current_gen(self) -> int:
        with self._stop_gen_lock:
            return self._stop_gen
