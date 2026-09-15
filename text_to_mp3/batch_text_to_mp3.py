import sys
import os
import torch
import torchaudio
from pydub import AudioSegment

# 步骤 1: 同步路径并导入CosyVoice模块
sys.path.append("/home/igraperobot3/Model/CosyVoice")
sys.path.append('/home/igraperobot3/Model/CosyVoice/third_party/Matcha-TTS') # Uncomment if needed
from cosyvoice.cli.cosyvoice import CosyVoice2
from cosyvoice.utils.file_utils import load_wav

print("--- 开始执行长文本转语音任务[mp3] ---")

# 步骤 2: 定义文件路径和模型参数
MODEL_PATH = "/home/igraperobot3/Model/CosyVoice2-0.5B"
PROMPT_WAV_PATH = '/home/igraperobot3/Model/audio_prompt_melo.wav'   # audio_prompt_cosyvoice.wav
prompt_text = '好的呀，计算机学院是在一九五八年哈尔滨军事工程学院创建我军第一个电子数字计算机研制组的基础上发展起来的。'
# 定义输入和输出文件夹路径
BASE_DIR = '/home/igraperobot3/Desktop/text_to_mp3/'
INPUT_DIR = os.path.join(BASE_DIR, 'text_input')
OUTPUT_DIR = os.path.join(BASE_DIR, 'audio_output')

# 修改：创建输入和输出文件夹（如果不存在）
if not os.path.exists(INPUT_DIR):
    os.makedirs(INPUT_DIR)
    print(f"已创建输入文件夹: {INPUT_DIR}")
else:
    print(f"\n[Text Input Dir]: {INPUT_DIR}\n")

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
    print(f"已创建输出文件夹: {OUTPUT_DIR}")
else:
    print(f"\n[Audio mp3 Output Dir]: {OUTPUT_DIR}\n")

if not os.path.exists(MODEL_PATH):
    print(f"错误：模型路径不存在: {MODEL_PATH}")
    sys.exit(1)
if not os.path.exists(PROMPT_WAV_PATH):
    print(f"错误：参考音频路径不存在: {PROMPT_WAV_PATH}")
    sys.exit(1)

print(f"[Model]正在从 {MODEL_PATH} 加载模型...")
cosyvoice = CosyVoice2(MODEL_PATH, load_jit=False, load_trt=False, fp16=False)

# 步骤 4: 加载参考音频 (Prompt)
print(f"正在加载参考音频: {PROMPT_WAV_PATH}")
prompt_speech_16k = load_wav(PROMPT_WAV_PATH, 16000)

# 修改：获取text_input目录下所有的txt文件
txt_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.txt')]

if not txt_files:
    print(f"警告：在 {INPUT_DIR} 下未找到任何 .txt 文件，请将需要转换的文本文件放入该目录。")
else:
    print(f"共找到 {len(txt_files)} 个文本文件待处理: {txt_files}")

    # 修改：开始遍历处理每个文件
    for txt_file in txt_files:
        print(f"\n>>> 正在处理文件: {txt_file}")

        # 构造输入输出路径
        TEXT_FILE_PATH = os.path.join(INPUT_DIR, txt_file)
        file_name_no_ext = os.path.splitext(txt_file)[0]
        OUTPUT_WAV_PATH = os.path.join(OUTPUT_DIR, f"{file_name_no_ext}.wav")
        OUTPUT_MP3_PATH = os.path.join(OUTPUT_DIR, f"{file_name_no_ext}.mp3")

        # # 步骤 5: 读取并预处理文本文件
        print(f"[预处理]文本文件: {TEXT_FILE_PATH}")
        with open(TEXT_FILE_PATH, 'r', encoding='utf-8') as f:
            long_text = f.read()

        processed_text = long_text.replace('\n', '。').replace('——', '。')

        # processed_text="欢迎来到我们的展馆！我是您的讲解助手，接下来就由我陪伴您开启一段精彩的探索之旅吧！在这里，您可以近距离了解珍贵的历史文物，也可以感受前沿科技的魅力。如果您在参观过程中有任何问题，随时都可以问我哦！现在，让我们一起开始吧！"
        # processed_text="您这边请，请跟紧我哦。"
        # zhanpinname="宋代青瓷"
        # processed_text=f"以上是关于{zhanpinname}的全部内容，如果您有什么问题，可以随时向我提问哦。"

        # 步骤 6: 执行推理并将所有音频片段收集到列表中
        print("[Model]开始进行文本转语音推理...")
        audio_chunks = []

        # cosyvoice.inference_zero_shot返回一个生成器，我们迭代它来获取所有音频片段
        try:
            for i, chunk in enumerate(
                    cosyvoice.inference_zero_shot(processed_text, prompt_text, prompt_speech_16k, stream=False)):
                # chunk['tts_speech'] 是一个torch.Tensor
                audio_chunks.append(chunk['tts_speech'])
                print(f"已生成第 {i + 1} 个音频片段...")
        except Exception as e:
            print(f"处理文件 {txt_file} 时发生错误: {e}")
            continue

        # 步骤 7: 检查是否生成了音频，然后拼接它们
        if not audio_chunks:
            print(f"警告：文件 {txt_file} 没有生成任何音频片段。请检查输入文本是否为空或模型是否正常工作。")
        else:
            print(f"共生成 {len(audio_chunks)} 个音频片段，正在拼接...")

            final_audio_tensor = torch.cat(audio_chunks, dim=1)

            # 步骤 8: 保存拼接后的完整音频文件
            torchaudio.save(
                OUTPUT_WAV_PATH,
                final_audio_tensor,
                cosyvoice.sample_rate
            )
            # step 9: Convert wav to mp3
            wav_path = OUTPUT_WAV_PATH
            mp3_path = OUTPUT_MP3_PATH

            audio = AudioSegment.from_wav(wav_path)
            audio.export(mp3_path, format="mp3")
            os.remove(wav_path)
            print(f"\n[mp3 save]保存至: {OUTPUT_MP3_PATH}\n")

print("\n--- 执行完毕 ---")
