# -*- coding: utf-8 -*-
"""校验大模型配置并做一次最小连通性测试。

用法（在 backend/ 目录下）：
    python scripts/check_llm.py          # 打印配置并发一句“只回复 OK”
    python scripts/check_llm.py --ask "灵山门票多少钱" --area lingshan
                                         # 走完整 RAG 链路验证答案与引用

未配置 api_base / model 时返回码 2，并提示怎么填；不会发起网络请求。
"""
from __future__ import annotations

import argparse
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.config import get_config  # noqa: E402
from app.db import session  # noqa: E402
from app.services.llm import (  # noqa: E402
    generate_answer,
    is_configured,
    llm_settings,
)
from app.services.retrieval import retrieve_for_answer  # noqa: E402


def _mask(key: str) -> str:
    if not key:
        return "（未设置）"
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def main() -> int:
    parser = argparse.ArgumentParser(description="校验大模型配置")
    parser.add_argument("--ask", help="用完整 RAG 链路试问一句")
    parser.add_argument("--area", default="lingshan", help="景区 id，默认 lingshan")
    args = parser.parse_args()

    settings = llm_settings()
    print(f"[config] api_base : {settings['api_base'] or '（未设置）'}")
    print(f"[config] model    : {settings['model'] or '（未设置）'}")
    print(f"[config] api_key  : {_mask(settings['api_key'])}")
    print(f"[config] timeout  : {settings['timeout']}s")

    if not is_configured():
        print("\n[check] 尚未配置大模型。请在 config.yaml 填写 llm.api_base 与 llm.model，")
        print("        或设置环境变量 XJ_LLM_API_KEY 后重试。")
        print("        DeepSeek: https://api.deepseek.com/v1  / deepseek-chat")
        print("        Qwen    : https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen-plus")
        return 2

    if not settings["api_key"]:
        print("\n[check] 缺少 API Key：请在 config.yaml 填 llm.api_key 或设置 XJ_LLM_API_KEY。")
        return 2

    if args.ask:
        with session() as conn:
            hits = retrieve_for_answer(conn, args.area, args.ask)
        if not hits:
            print(f"[check] 景区 {args.area} 没有可检索的知识块，请先运行 scripts/seed.py。")
            return 1
        answer, model = generate_answer(args.ask, hits)
        print(f"\n[ask] 问题：{args.ask}")
        print(f"[ask] 模型：{model}")
        print(f"[ask] 答案：{answer}")
        print(f"[ask] 引用：{[hit['title'] for hit in hits]}")
        return 0

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=settings["api_base"],
            api_key=settings["api_key"],
            timeout=settings["timeout"],
        )
        response = client.chat.completions.create(
            model=settings["model"],
            messages=[{"role": "user", "content": "只回复 OK"}],
            max_tokens=8,
            temperature=0,
        )
        text = (response.choices[0].message.content or "").strip()
        print(f"\n[check] 连通成功，模型回复：{text!r}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\n[check] 调用失败：{type(exc).__name__}: {exc}")
        print("        检查网络、base_url、模型名与密钥是否正确。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
