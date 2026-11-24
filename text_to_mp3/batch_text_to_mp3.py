#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量把 text_input/*.txt 合成为讲解 mp3（CosyVoice2，可选依赖）。

CosyVoice 不在 requirements.txt 中，需要按官方说明单独安装；本脚本只做
路径参数化，默认值可按机器覆盖。

用法：
  python batch_text_to_mp3.py --model /path/CosyVoice2-0.5B \
      --prompt-wav /path/prompt.wav --prompt-text "参考音频对应的文字" \
      --input-dir text_input --output-dir audio_output
"""

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="批量文本转讲解 mp3（CosyVoice2）")
    parser.add_argument("--cosyvoice-dir", default=os.environ.get("COSYVOICE_DIR", "models/CosyVoice"),
                        help="CosyVoice 源码目录（会加入 sys.path）")
    parser.add_argument("--matcha-dir", default="",
                        help="Matcha-TTS 目录（需要时填写，默认 <cosyvoice-dir>/third_party/Matcha-TTS）")
    parser.add_argument("--model", default="models/CosyVoice2-0.5B", help="CosyVoice2 模型目录")
    parser.add_argument("--prompt-wav", required=True, help="参考音频 wav（音色克隆）")
    parser.add_argument("--prompt-text", required=True, help="参考音频对应的文字")
    parser.add_argument("--input-dir", default="text_input", help="待合成 txt 目录")
    parser.add_argument("--output-dir", default="audio_output", help="mp3 输出目录")
    parser.add_argument("--fp16", action="store_true", help="GPU 上启用 fp16")
    args = parser.parse_args()

    cosyvoice_dir = os.path.abspath(args.cosyvoice_dir)
    matcha_dir = os.path.abspath(args.matcha_dir or
                                 os.path.join(cosyvoice_dir, "third_party", "Matcha-TTS"))
    if not os.path.isdir(cosyvoice_dir):
        print(f"错误：CosyVoice 目录不存在: {cosyvoice_dir}")
        return 1
    if not os.path.isdir(args.model):
        print(f"错误：模型路径不存在: {args.model}")
        return 1
    if not os.path.exists(args.prompt_wav):
        print(f"错误：参考音频路径不存在: {args.prompt_wav}")
        return 1

    sys.path.insert(0, cosyvoice_dir)
    if os.path.isdir(matcha_dir):
        sys.path.insert(0, matcha_dir)

    import torch
    import torchaudio
    from pydub import AudioSegment
    from cosyvoice.cli.cosyvoice import CosyVoice2
    from cosyvoice.utils.file_utils import load_wav

    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    print(f"[Model] 正在从 {os.path.abspath(args.model)} 加载模型...")
    cosyvoice = CosyVoice2(args.model, load_jit=False, load_trt=False, fp16=args.fp16)

    print(f"正在加载参考音频: {args.prompt_wav}")
    prompt_speech_16k = load_wav(args.prompt_wav, 16000)

    txt_files = sorted(f for f in os.listdir(input_dir) if f.endswith(".txt"))
    if not txt_files:
        print(f"警告：在 {input_dir} 下未找到任何 .txt 文件")
        return 0

    print(f"共找到 {len(txt_files)} 个文本文件待处理: {txt_files}")
    for txt_file in txt_files:
        print(f"\n>>> 正在处理文件: {txt_file}")
        text_path = os.path.join(input_dir, txt_file)
        stem = os.path.splitext(txt_file)[0]
        wav_path = os.path.join(output_dir, f"{stem}.wav")
        mp3_path = os.path.join(output_dir, f"{stem}.mp3")

        with open(text_path, "r", encoding="utf-8") as f:
            processed_text = f.read().replace("\n", "。").replace("——", "。")

        print("[Model] 开始进行文本转语音推理...")
        audio_chunks = []
        try:
            for i, chunk in enumerate(cosyvoice.inference_zero_shot(
                    processed_text, args.prompt_text, prompt_speech_16k, stream=False)):
                audio_chunks.append(chunk["tts_speech"])
                print(f"已生成第 {i + 1} 个音频片段...")
        except Exception as e:  # noqa: BLE001
            print(f"处理文件 {txt_file} 时发生错误: {e}")
            continue

        if not audio_chunks:
            print(f"警告：文件 {txt_file} 没有生成任何音频片段")
            continue

        final_audio = torch.cat(audio_chunks, dim=1)
        torchaudio.save(wav_path, final_audio, cosyvoice.sample_rate)
        AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")
        os.remove(wav_path)
        print(f"[mp3 save] 保存至: {mp3_path}")

    print("\n--- 执行完毕 ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
