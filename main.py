#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LMAM 本地运行入口。

用法：
    python main.py            # 启动语音交互（需音频设备与模型文件）
    python main.py --check    # 只校验配置与模块导入，不加载模型、不开音频

调试 CLI（stdin）：
    audio_start <mp3路径>     # 播放讲解音频（验证打断/续播）
    stop                      # 打断全部本地播放
    quit                      # 退出
"""

import argparse
import importlib
import logging
import os
import sys
import threading

from scripts.config import PATH_KEYS, load_config


def setup_logging(level=logging.INFO):
    # Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def run_check() -> int:
    """轻量自检：配置 + 模块导入。不加载任何模型。

    轻量模块（command_bus/audio_player，仅依赖标准库/已装基础包）必须可导入，
    否则退出码 1；其余模块依赖 cn2an/rapidfuzz/sounddevice/torch/funasr 等
    第三方库，允许缺失，仅提示——它们在真机环境才就绪。
    """
    try:
        cfg = load_config(check_paths=False)
    except Exception as e:
        print(f"[check] FAIL: {e}")
        return 1
    print("[check] OK: config 加载成功")
    print(f"[check] 唤醒词: {cfg.wake_word}")

    light = ["scripts.command_bus", "scripts.audio_player"]
    heavy = ["scripts.matcher", "scripts.tts_local_player",
             "scripts.llm", "scripts.local_listener", "scripts.wakeup", "lmam.app"]
    failed_light = []
    for mod_name in light + heavy:
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            if mod_name in light:
                failed_light.append(f"{mod_name}: {e}")
            else:
                print(f"[check] 跳过 {mod_name}（依赖未安装，真机环境需就绪）: {type(e).__name__}")
    if failed_light:
        for line in failed_light:
            print(f"[check] FAIL: {line}")
        return 1

    missing = [k for k in PATH_KEYS
               if cfg.get(k) and not os.path.exists(cfg.get(k))]
    if missing:
        print(f"[check] 提示: 以下模型/数据路径在本机不存在（真机运行前需就绪）: {missing}")
    print("[check] DONE")
    return 0


def cli_loop(app):
    """调试 CLI：驱动音频播放/打断，验证打断续播体验。"""
    while True:
        try:
            line = input().strip()
        except (EOFError, KeyboardInterrupt):
            line = "quit"
        if not line:
            continue
        if line == "quit":
            app.shutdown()
            return
        if line.startswith("audio_start "):
            path = line.split(" ", 1)[1].strip()
            print(f"[cli] audio_start -> {app.audio_start(path)}")
        elif line == "stop":
            app.audio_stop()
            print("[cli] stop sent")
        else:
            print("[cli] 可用命令: audio_start <路径> | stop | quit")


def main():
    parser = argparse.ArgumentParser(description="LMAM local voice app")
    parser.add_argument("--check", action="store_true", help="只校验配置与导入")
    args = parser.parse_args()

    setup_logging()
    if args.check:
        sys.exit(run_check())

    cfg = load_config(check_paths=True)  # 路径不就绪直接报错退出
    from lmam.app import LMAMApp
    app = LMAMApp(cfg)
    app.start()

    cli_thread = threading.Thread(target=cli_loop, args=(app,), daemon=True)
    cli_thread.start()
    try:
        cli_thread.join()  # 生命周期跟随调试 CLI（quit/EOF 即退出）
    except KeyboardInterrupt:
        app.shutdown()


if __name__ == "__main__":
    main()
