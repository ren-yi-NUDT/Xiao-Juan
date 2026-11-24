# text_to_mp3

讲解音频生成工具（与语音主链路解耦，按需使用）。

- `batch_text_to_mp3.py`：批量把 `text_input/*.txt` 合成为 `audio_output/*.mp3`（CosyVoice2）。
  CosyVoice 需单独安装，示例：

  ```bash
  python batch_text_to_mp3.py \
    --cosyvoice-dir /path/to/CosyVoice \
    --model /path/to/CosyVoice2-0.5B \
    --prompt-wav /path/to/prompt.wav \
    --prompt-text "参考音频对应的文字" \
    --input-dir text_input --output-dir audio_output
  ```

  生成的 mp3 可通过主程序调试命令 `audio_start <mp3路径>` 播放，验证唤醒打断/续播。

原先的 `create_faiss_database_vector.py` 已删除：知识库检索统一由 `rag_backend` 提供，
语音前端不再在本地构建 FAISS。
