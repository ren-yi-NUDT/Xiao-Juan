# -*- coding: utf-8 -*-
"""本地讲解音频播放器（替代原 Orin audio_control action）。

用 pygame.mixer.music 实现 mp3/wav 播放，语义对齐原 AudioControl：
- start(path)  开始播放
- pause()      暂停（断点保留）
- resume()     从断点续播
- stop()/interrupt()  停止（视为被打断）
自然播完回调 on_finished("finished")；stop/interrupt 回调 on_finished("interrupted")。
"""

import logging
import threading
import time

log = logging.getLogger("lmam.audio")


class AudioPlayer:
    def __init__(self, on_finished=None, poll_interval: float = 0.1):
        self.on_finished = on_finished or (lambda status: None)
        self.poll_interval = poll_interval
        self._lock = threading.Lock()
        self._paused = False
        self._stopped = True

    # ---- pygame 延迟初始化：导入/单测不触碰音频设备 ----
    @staticmethod
    def _music():
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return pygame.mixer.music

    # ---- 对外接口（对齐原 AudioControl 五个命令） ----
    def start(self, path: str) -> bool:
        music = self._music()
        try:
            music.load(path)
            music.play()
        except Exception as e:
            log.error("[AudioPlayer] start 失败: %s", e)
            return False
        with self._lock:
            self._paused = False
            self._stopped = False
        self._spawn_watcher()
        return True

    def pause(self) -> bool:
        with self._lock:
            if self._stopped or self._paused:
                return False
            self._paused = True
        self._music().pause()
        return True

    def resume(self) -> bool:
        with self._lock:
            if self._stopped or not self._paused:
                return False
            self._paused = False
        self._music().unpause()
        self._spawn_watcher()
        return True

    def stop(self) -> None:
        self._finish("interrupted")

    def interrupt(self) -> None:
        self._finish("interrupted")

    # ---- 内部 ----
    def _finish(self, status: str) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._paused = False
        try:
            self._music().stop()
        except Exception:  # noqa: BLE001
            pass
        self.on_finished(status)

    def _spawn_watcher(self):
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        while True:
            with self._lock:
                if self._stopped:
                    return
                paused = self._paused
            try:
                busy = self._music().get_busy()
            except Exception:  # noqa: BLE001
                busy = False
            if not busy:
                if paused:
                    return        # 暂停中：退出，resume 时重新起 watcher
                self._finish("finished")
                return
            time.sleep(self.poll_interval)
