#!/home/igraperobot3/anaconda3/envs/audio/bin/python3
IDLE_TIMEOUT = 10.0
import subprocess
from dataclasses import dataclass, field
from threading import Lock, Thread
from funasr import AutoModel
from contextlib import contextmanager
from typing import Optional
import numpy as np
import os
import sys
import time
@dataclass
class SharedState:
    mode: str = "IDLE"
    tts_playing: bool = False
    audio_playing: bool = False
    tts_proc: Optional[subprocess.Popen] = None
    last_user_activity: float = field(default_factory=time.time)
    lock: Lock = field(default_factory=Lock)

    def set_mode(self, mode: str):
        if mode not in ("IDLE", "ACTIVE"):
            return
        with self.lock:
            if self.mode != mode:
                print(f"[State] mode: {self.mode} -> {mode}")
            self.mode = mode

    def wake(self):
        with self.lock:
            if self.mode != "ACTIVE":
                print("[State] Wake: IDLE -> ACTIVE")
            self.mode = "ACTIVE"
            self.last_user_activity = time.time()

    def on_user_voice(self):
        with self.lock:
            self.last_user_activity = time.time()

    def maybe_back_to_idle(self):
        # ✅ 先读状态,决定要不要切模式；不要在持锁时再调用 set_mode
        with self.lock:
            if self.mode != "ACTIVE" or self.tts_playing:
                return None
            elapsed = time.time() - float(self.last_user_activity)
            need_idle = elapsed > IDLE_TIMEOUT
        if need_idle:
            print(f"[State] No activity for {elapsed:.1f}s (> {IDLE_TIMEOUT}s), back to IDLE.")
            self.set_mode("IDLE")  # ✅ 此时不在锁里
            return time.time()
    def set_tts_playing(self, playing: bool, proc: Optional[subprocess.Popen] = None):
        with self.lock:
            self.tts_playing = playing
            if proc is not None:
                self.tts_proc = proc
            elif not playing:
                self.tts_proc = None
            print(f"[State] tts_playing -> {playing}")
    def set_audio_playing(self, playing: bool, proc: Optional[subprocess.Popen] = None):
        with self.lock:
            self.audio_playing = playing
            if proc is not None:
                self.tts_proc = proc
            elif not playing:
                self.tts_proc = None
            print(f"[State] audio_playing -> {playing}")

    def stop_tts(self):
        with self.lock:
            self._stop_tts_nolock()

    def is_active(self) -> bool:
        with self.lock:
            return self.mode == "ACTIVE"

    def is_idle(self) -> bool:
        with self.lock:
            return self.mode == "IDLE"
# ================== Client 控制防抖：WAKE / INTERRUPT 共用 2 秒窗口 ==================
class ClientControlState:
    """
    客户端侧 WAKE / INTERRUPT 防抖：
    - WAKE / INTERRUPT 共用一个时间戳
    - 2 秒内只允许一个控制指令真正发给 server
    """

    def __init__(self):
        self.last_control_ts: float = 0.0
        self.last_type: str = ""
        self.lock = Lock()

    def can_send(self, kind: str, min_interval: float = 2.0) -> bool:
        """
        kind: "WAKE" or "INTERRUPT"
        返回 True: 允许这次发送
        返回 False: 两秒内重复控制,丢弃
        """
        now = time.time()
        with self.lock:
            if now - self.last_control_ts < min_interval:
                # 调试时可以看到被丢弃了什么
                print(f"[Ctrl] Skip {kind}: too frequent, last={self.last_type}")
                return False
            self.last_control_ts = now
            self.last_type = kind
            print(f"[Ctrl] Accept {kind}")
            return True
@contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

# ================== FunASR KWS: iic/speech_charctc_kws_phone-xiaoyun ==================
class XiaoYunKWS:
    """
    使用 FunASR 的“小云小云”唤醒模型：
      - 模型: iic/speech_charctc_kws_phone-xiaoyun
      - 默认唤醒词: "小云小云"
    """

    def __init__(self, sample_rate: int = 16000, keyword: str = "小云小云"):
        self.sample_rate = sample_rate
        self.keyword = keyword

        print("[KWS] Loading FunASR KWS model (xiaoyun)...")
        # 如果 offline,可将 model 换成本地路径、device 改成 "cuda" 视情况
        self.model = AutoModel(
            model="/home/igraperobot3/Model/speech_charctc_kws_phone-xiaoyun",
            keywords=keyword,
            disable_update=True,
            output_dir="./outputs/debug",
            device="cuda",  # KWS 很轻,CPU 即可；如需可改 "cuda"
        )
        print("[KWS] Model loaded.")
        # 为了降低延迟 + 不让 buffer 无限制增长

        self.buffer = bytearray()
        self.window_sec = 0.8      # 每 0.8 s 做一次检测
        self.max_buffer_sec = 2.0  # 最多保留 2 s 历史

    def feed(self, pcm_bytes: bytes) -> bool:
        """
        喂入一小段 int16 PCM,
        检测到唤醒词时返回 True。
        """
        if not pcm_bytes:
            return False

        self.buffer.extend(pcm_bytes)

        # 控制 buffer 长度
        max_len = int(self.max_buffer_sec * self.sample_rate) * 2  # int16 -> *2
        if len(self.buffer) > max_len:
            self.buffer = self.buffer[-max_len:]

        # 至少积累 window_sec 再检测
        need_len = int(self.window_sec * self.sample_rate) * 2
        if len(self.buffer) < need_len:
            return False

        # 取最近 window_sec 音频
        chunk = self.buffer[-need_len:]
        audio = np.frombuffer(chunk, dtype=np.int16).astype("float32") / 32768.0

        try:
            with suppress_stdout():
                res = self.model.generate(
                    input=audio,
                    cache={}
                )
        except Exception as e:
            print(f"[KWS] FunASR generate error: {e}")
            return False
        import re
        score = 0.0
        detected = False
        try:
            if isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
                info = res[0]
                text_raw = str(info.get("text", ""))
                text = text_raw.lower()

                # 1) 先尝试直接取 score 字段（如果未来有）
                if "score" in info:
                    try:
                        score = float(info.get("score", 0.0))
                    except Exception:
                        score = 0.0

                # 2) 如果没有 score 字段,就从 text 末尾解析浮点数
                #    你的格式：'detected 小云小云 0.2672964678'
                if score == 0.0:
                    m = re.search(r'(-?\d+\.\d+|\d+)(?:\s*)$', text_raw.strip())
                    if m:
                        try:
                            score = float(m.group(1))
                        except Exception:
                            score = 0.0

                # 3) 判断是否命中 keyword（你的 text 里包含“小云小云”）
                hit_kw = (self.keyword in text_raw) or (self.keyword in text)

                # 4) 判断 detected
                hit_detect = ("detected" in text)

                # 5) 最终门限：命中 + score >= 0.7 才触发
                TH = 0.2
                if (hit_detect and hit_kw and score >= TH):
                    detected = True
                else:
                    # 命中了但分数不够：只打印,不触发
                    if hit_detect and hit_kw:
                        print(f"[KWS] hit but score too low: {score:.3f} < {TH}")

            else:
                print("[KWS] Unrecognized result format:", res)

        except Exception as e:
            print(f"[KWS] Parse result error: {e}")
            detected = False

        if detected:
            print(f"[KWS] Keyword '{self.keyword}' accepted! score={score:.3f}")

        return detected
