# -*- coding: utf-8 -*-
"""本地 TTS 播放器：MeloTTS 生成 wav + sounddevice 本机扬声器播放。

由 scripts/tts_ws_streamer.py 改造：删除 WebSocket 推流，改为本机播放。
speak(text) 阻塞至播完（与原 await 语义一致）；stop() 可从其它线程打断。
"""

import io
import logging
import tempfile
import threading
import time

import sounddevice as sd
import soundfile as sf

log = logging.getLogger("lmam.tts")


class TTSLocalPlayer:
    def __init__(
        self,
        config_path: str,
        ckpt_path: str,
        device: str = "cuda",
        language: str = "ZH",
        speaker_key: str = "ZH",
        speed: float = 1.0,
        sample_rate: int = 22050,
    ):
        self.speed = speed
        self.sample_rate = sample_rate
        # 延迟导入：melo 加载很重，--check/单测不需要
        from melo.api import TTS
        self.tts = TTS(
            language=language,
            device=device,
            use_hf=False,
            config_path=config_path,
            ckpt_path=ckpt_path,
        )
        self.speaker_ids = self.tts.hps.data.spk2id
        if speaker_key not in self.speaker_ids:
            raise ValueError(
                f"speaker_key='{speaker_key}' not in {list(self.speaker_ids.keys())}")
        self.speaker_id = self.speaker_ids[speaker_key]
        self._stop_flag = threading.Event()
        # 串行化 speak：melo 推理非线程安全，sd.play 是全局流（原版由 asyncio 串行）
        self._speak_lock = threading.Lock()

    def _run_tts_to_bytes(self, text: str) -> bytes:
        """同步：TTS -> wav bytes（与原实现一致，临时文件放系统临时目录）。"""
        tmp_wav = f"{tempfile.gettempdir()}/tts_{int(time.time() * 1000)}.wav"
        self.tts.tts_to_file(text, self.speaker_id, tmp_wav, speed=self.speed)
        with open(tmp_wav, "rb") as f:
            wav_bytes = f.read()
        return wav_bytes

    def speak(self, text: str) -> None:
        """阻塞式播报；stop() 可打断。多线程调用时按先后串行播报。"""
        if not text:
            return
        with self._speak_lock:
            try:
                wav_bytes = self._run_tts_to_bytes(text)
                data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
                self._stop_flag.clear()
                sd.play(data, sr)
                while sd.is_playing() and not self._stop_flag.is_set():
                    time.sleep(0.05)
                sd.stop()
            except Exception as e:
                log.error("[TTSLocalPlayer] speak 失败: %s", e)

    def stop(self) -> None:
        self._stop_flag.set()
