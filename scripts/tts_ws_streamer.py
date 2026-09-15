import asyncio
import json
import os
import time
import websockets
from melo.api import TTS


class TTSWsStreamer:
    """
    负责：
    1) 初始化 MeloTTS（一次）
    2) 同步生成 wav bytes（放线程池跑）
    3) 按你既定协议发 header + wav chunks + [AUTO_ACTIVE]
    """

    def __init__(
        self,
        config_path: str,
        ckpt_path: str,
        device: str = "cuda",
        language: str = "ZH",
        speaker_key: str = "ZH",
        speed: float = 1.0,
        chunk_size: int = 64 * 1024,
        sample_rate: int = 22050,  # 你现在写死 22050,就先保留
    ):
        self.chunk_size = chunk_size
        self.speed = speed
        self.sample_rate = sample_rate

        self.tts = TTS(
            language=language,
            device=device,
            use_hf=False,
            config_path=config_path,
            ckpt_path=ckpt_path,
        )
        self.speaker_ids = self.tts.hps.data.spk2id
        if speaker_key not in self.speaker_ids:
            raise ValueError(f"speaker_key='{speaker_key}' not in {list(self.speaker_ids.keys())}")
        self.speaker_id = self.speaker_ids[speaker_key]

    def _run_tts_to_bytes(self, text: str) -> bytes:
        """同步：TTS -> wav bytes"""
        tmp_wav = f"/tmp/tts_{int(time.time() * 1000)}.wav"
        self.tts.tts_to_file(text, self.speaker_id, tmp_wav, speed=self.speed)
        with open(tmp_wav, "rb") as f:
            wav_bytes = f.read()
        # try:
        #    os.remove(tmp_wav)
        # except OSError:
        #     pass
        return wav_bytes

    async def speak(self, text: str, websocket, send_lock: asyncio.Lock):
        """
        异步：生成 + 发送（不会阻塞 event loop）
        """
        if not text:
            return
        if websocket is None:
            return

        try:
            t0 = time.time()
            wav_bytes = await asyncio.to_thread(self._run_tts_to_bytes, text)
            t1 = time.time()

            total_len = len(wav_bytes)
            header = {
                "type": "tts_wav",
                "format": "wav",
                "sample_rate": self.sample_rate,
                "num_channels": 1,
                "num_bytes": total_len,
                "chunk_size": self.chunk_size,
            }
            header_str = json.dumps(header, ensure_ascii=False)

            async with send_lock:
                await websocket.send(f"[LLM]:{text}")
                await websocket.send(f"[Server] FIXED TTS processing time: {t1 - t0:.2f} seconds.")
                await websocket.send(f"[TTS_HEADER]{header_str}")

                sent = 0
                while sent < total_len:
                    chunk = wav_bytes[sent : sent + self.chunk_size]
                    await websocket.send(chunk)
                    sent += len(chunk)

                await websocket.send("[AUTO_ACTIVE]")

        except websockets.ConnectionClosed:
            print("[TTSWsStreamer] Connection closed while speaking.")
        except Exception as e:
            print("[TTSWsStreamer] ERROR:", e)
