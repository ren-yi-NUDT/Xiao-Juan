import speech_recognition as sr
import pyaudio
import os
import tempfile
import sys
import numpy as np
import audioop
import time
import math
from contextlib import contextmanager
from faster_whisper import WhisperModel
import sounddevice as sd

@contextmanager
def ignore_stderr():
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        sys.stderr.flush()
        os.dup2(devnull, 2)
        os.close(devnull)
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)

class VoiceListener:
    def __init__(self, model_path_or_size="small", device="auto"):
        print(f"🔄 正在加载 Whisper 模型: {model_path_or_size} (Device: {device})...")
        try:
            with ignore_stderr():
                self.model = WhisperModel(model_path_or_size, device=device, compute_type="int8")
        except Exception as e:
            print(f"❌ 模型加载失败: {e}")
            print("⚠️ 尝试加载默认 'base' 模型...")
            self.model = WhisperModel("base", device=device, compute_type="int8")
        
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 2000
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.pause_threshold = 0.5
        
        self.mic_index = self._find_sdd_device_index()
        self._calibrate_noise()

        self.pya = pyaudio.PyAudio()
        self.kws_target_sr = 16000
        self.kws_stream = None
        self.kws_input_sr = None
        self.kws_frames_per_buffer = None

        # 让 ASR 的 sr.Microphone 也用一个“更可能成功”的采样率（可选）
        self.asr_sr = self._pick_input_rate(self.mic_index, prefer=[16000, 48000, 44100, 32000, 22050])

        print(f"[Audio] mic_index={self.mic_index}, asr_sr={self.asr_sr}")

    def _find_sdd_device_index(self):
        devices = sd.query_devices()
        device_index=None
        for i, dev in enumerate(devices):
            if "Wireless microphone" in dev['name']:
                print(f"找到设备: 索引={i}")
                device_index = i
                break
        return device_index

    def _find_ugreen_device_index(self):
        with ignore_stderr():
            p = pyaudio.PyAudio()
            target_index = None
            keywords = ["UGREEN", "CM379", "USB Audio", "USB PnP"]
            print("🔍 正在扫描音频设备...")
            try:
                info = p.get_host_api_info_by_index(0)
                numdevices = info.get('deviceCount')
                for i in range(0, numdevices):
                    device_info = p.get_device_info_by_host_api_device_index(0, i)
                    if device_info.get('maxInputChannels') > 0:
                        raw_name = device_info.get('name')
                        try:
                            name = raw_name.encode('latin-1').decode('gbk')
                        except:
                            name = raw_name
                        for k in keywords:
                            if k.lower() in name.lower():
                                target_index = i
                                print(f"✅ 锁定设备: [{i}] {name}")
                                return target_index
            except Exception:
                pass
            finally:
                p.terminate()
        
        if target_index is None:
            print("⚠️ 未找到 UGREEN 设备，使用系统默认麦克风")
        return target_index
    def _pick_input_rate(self, device_index, prefer):
        """挑一个设备能 open 的 rate；都不行就用 defaultSampleRate"""
        info = self.pya.get_device_info_by_index(device_index) if device_index is not None \
               else self.pya.get_default_input_device_info()

        default_sr = int(info.get("defaultSampleRate", 48000))
        candidates = list(prefer)
        if default_sr not in candidates:
            candidates.append(default_sr)

        last_err = None
        for sr in candidates:
            try:
                # 用 is_format_supported 探测（最靠谱）
                ok = self.pya.is_format_supported(
                    sr,
                    input_device=device_index,
                    input_channels=1,
                    input_format=pyaudio.paInt16,
                )
                if ok:
                    return int(sr)
            except Exception as e:
                last_err = e
                continue

        # 实在探不到，就回退 default_sr（即使之后 open 失败，也能看到更明确的信息）
        print(f"[KWS] Warning: could not verify supported sr, fallback default_sr={default_sr}, err={last_err}")
        return default_sr
    def _calibrate_noise(self):
        if self.mic_index is not None:
            print("🔇 正在校准环境噪音 (请保持安静 1 秒)...")
            try:
                with ignore_stderr():
                    with sr.Microphone(device_index=self.mic_index) as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                print("✅ 校准完成")
            except Exception as e:
                print(f"⚠️ 校准失败: {e}")

    # ---------- KWS stream control ----------
    def ensure_kws_stream(self):
        """IDLE 模式调用：确保 KWS 的 PyAudio 输入流已打开"""
        if self.kws_stream is not None:
            return

        self.kws_input_sr = self._pick_input_rate(self.mic_index, prefer=[16000, 48000, 44100, 32000, 22050])
        self.kws_frames_per_buffer = int(self.kws_input_sr * 0.1)  # 0.1s

        print(f"[KWS] open stream: input_sr={self.kws_input_sr}, fpb={self.kws_frames_per_buffer}")

        self.kws_stream = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.kws_input_sr,
            input=True,
            input_device_index=self.mic_index,
            frames_per_buffer=self.kws_frames_per_buffer,
        )

    def close_kws_stream(self):
        """ACTIVE 模式调用：关闭 KWS 流，释放设备给 speech_recognition"""
        if self.kws_stream is None:
            return
        try:
            self.kws_stream.stop_stream()
        except Exception:
            pass
        try:
            self.kws_stream.close()
        except Exception:
            pass
        self.kws_stream = None
        print("[KWS] stream closed")

    def read_kws_pcm_16k(self, duration_sec=0.2) -> bytes:
        """
        连续读 PCM（不做 VAD/切句），并重采样到 16k int16 bytes 给 KWS。
        """
        self.ensure_kws_stream()
        if self.kws_stream is None:
            return b""

        n_reads = max(1, int(math.ceil(duration_sec / 0.1)))
        chunks = []
        for _ in range(n_reads):
            try:
                chunks.append(self.kws_stream.read(self.kws_frames_per_buffer, exception_on_overflow=False))
            except Exception as e:
                print(f"[KWS] stream.read error: {e}")
                return b""

        raw = b"".join(chunks)

        # 设备采样率 != 16k 时，用 audioop.ratecv 重采样（不依赖 scipy）
        if self.kws_input_sr != self.kws_target_sr:
            try:
                raw, _ = audioop.ratecv(raw, 2, 1, self.kws_input_sr, self.kws_target_sr, None)
            except Exception as e:
                print(f"[KWS] resample error: {e}")
                return b""

        return raw

    # ---------- ASR ----------
    def listen_and_transcribe(self):
        """
        只在 ACTIVE 模式调用。
        注意：调用前务必 close_kws_stream()，避免设备被占用。
        """
        try:
            # with ignore_stderr():
                with sr.Microphone(device_index=self.mic_index) as source:
                    print("\n👂 聆听中...", end="\r")
                    audio_data = self.recognizer.listen(source, timeout=1, phrase_time_limit=10)
                    print("⚡ 处理中...   ", end="\r")
        except sr.WaitTimeoutError:
            return ""
        except Exception as e:
            print(f"\n❌ 录音错误: {e}")
            return ""

        temp_wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                temp_wav.write(audio_data.get_wav_data())
                temp_wav_path = temp_wav.name

            segments, info = self.model.transcribe(temp_wav_path, beam_size=5, language="zh")
            text_output = "".join(seg.text for seg in segments)
            if text_output:
                print(f"📝 识别结果: {text_output}")
            return text_output
        except Exception as e:
            print(f"\n❌ 识别错误: {e}")
            return ""
        finally:
            if temp_wav_path and os.path.exists(temp_wav_path):
                os.remove(temp_wav_path)

    def destroy(self):
        """程序退出前调用"""
        self.close_kws_stream()
        try:
            self.pya.terminate()
        except Exception:
            pass

if __name__ == "__main__":
    model_path = "/home/igraperobot3/Model/faster-whisper-large-v3"
    
    listener = VoiceListener(model_path_or_size=model_path, device="cuda")
    listener.close_kws_stream()
    print("=======================================")
    print("   语音控制系统已启动 (极速优化版)")
    print("=======================================")
    
    while True:
        try:
            start = time.time()
            result_text = listener.listen_and_transcribe()
            end = time.time()
            print(f"⏱️ 处理时长: {end - start:.2f} 秒", end="\r")
            if result_text and len(result_text.strip()) > 0:
                pass
        except KeyboardInterrupt:
            print("\n🛑 程序停止")
            break