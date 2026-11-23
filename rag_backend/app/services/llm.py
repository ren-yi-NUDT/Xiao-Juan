# -*- coding: utf-8 -*-
"""答案生成：OpenAI 兼容云模型 + 抽取式降级。

配置 `llm.api_base` + `llm.model` 后调用云模型（DeepSeek / Qwen 等兼容接口）；
未配置、超时或调用失败时退化为抽取式回答，保证问答链路始终可用。
多轮历史由调用方从 qa_log 取出后以 messages 形式传入，本模块不碰数据库。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator

from app.config import get_config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是景区官方资料库的问答助手。只能依据给定的资料片段回答，"
    "不得使用资料之外的知识，也不得编造；资料没有覆盖时直接说明“资料库暂未收录”。"
    "对话历史只用于理解指代和上下文，事实仍以资料片段为准。"
    "回答简洁、口语化，引用资料处标注 [1][2] 这样的序号。"
)


def _settings() -> dict:
    """读取大模型配置；api_key 留空时回退到环境变量 XJ_LLM_API_KEY。"""
    cfg = get_config().llm
    api_key = str(getattr(cfg, "api_key", "") or "").strip()
    if not api_key:
        api_key = os.environ.get("XJ_LLM_API_KEY", "").strip()
    return {
        "api_base": str(getattr(cfg, "api_base", "") or "").strip(),
        "api_key": api_key,
        "model": str(getattr(cfg, "model", "") or "").strip(),
        "timeout": float(getattr(cfg, "timeout_sec", 30) or 30),
        "temperature": float(getattr(cfg, "temperature", 0.2) or 0.0),
        "max_tokens": int(getattr(cfg, "max_tokens", 800) or 800),
    }


def llm_settings() -> dict:
    """供自检脚本 / 管理端展示使用（含密钥，调用方自行脱敏）。"""
    return _settings()


def is_configured() -> bool:
    settings = _settings()
    return bool(settings["api_base"] and settings["model"])


def _extractive_answer(hits: list[dict]) -> str:
    if not hits:
        return "抱歉，知识库中暂时没有找到与这个问题相关的资料。"
    lines = []
    for i, hit in enumerate(hits[:2], start=1):
        lines.append(f"{hit['content']} [{i}]")
    return ("根据景区资料：\n" + "\n\n".join(lines)
            + "\n\n（当前未配置大模型，以上为检索到的资料原文摘要。）")


def _build_messages(question: str, hits: list[dict],
                    history: list[dict] | None) -> list[dict]:
    context = "\n\n".join(
        f"[{i}]（{hit['title']}）{hit['content']}"
        for i, hit in enumerate(hits, start=1))
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history or []:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({
        "role": "user",
        "content": f"资料片段：\n{context}\n\n游客问题：{question}",
    })
    return messages


def _client(settings: dict):
    from openai import OpenAI

    return OpenAI(
        base_url=settings["api_base"],
        api_key=settings["api_key"] or "EMPTY",
        timeout=settings["timeout"],
    )


def _chat(settings: dict, messages: list[dict]) -> str:
    response = _client(settings).chat.completions.create(
        model=settings["model"],
        messages=messages,
        temperature=settings["temperature"],
        max_tokens=settings["max_tokens"],
    )
    return (response.choices[0].message.content or "").strip()


def _stream_chat(settings: dict, messages: list[dict]) -> Iterator[str]:
    stream = _client(settings).chat.completions.create(
        model=settings["model"],
        messages=messages,
        temperature=settings["temperature"],
        max_tokens=settings["max_tokens"],
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None)
        if text:
            yield text


def generate_answer(question: str, hits: list[dict],
                    history: list[dict] | None = None) -> tuple[str, str]:
    """返回 (答案, 使用模型标识)。配置缺失或调用失败时自动降级为抽取式。"""
    if not hits:
        return _extractive_answer(hits), "extractive"

    if is_configured():
        settings = _settings()
        try:
            answer = _chat(settings, _build_messages(question, hits, history))
            if answer:
                return answer, settings["model"]
        except Exception as exc:  # 网络 / 密钥 / 模型不可用时不阻断问答
            logger.warning("大模型调用失败，降级为抽取式回答：%s", exc)

    return _extractive_answer(hits), "extractive"


def stream_answer(question: str, hits: list[dict],
                  history: list[dict] | None = None
                  ) -> Iterator[tuple[str, str]]:
    """流式回答，产出 ("delta", 文本) 与 ("done", 模型标识)。

    任何失败都收敛为完整可读的回答：未输出内容时整段降级为抽取式；
    已输出部分内容时补一句中断提示，保证 SSE 流以 done 正常收尾。
    """
    if not hits:
        yield "delta", _extractive_answer(hits)
        yield "done", "extractive"
        return

    if not is_configured():
        yield "delta", _extractive_answer(hits)
        yield "done", "extractive"
        return

    settings = _settings()
    emitted = False
    try:
        for text in _stream_chat(
                settings, _build_messages(question, hits, history)):
            emitted = True
            yield "delta", text
        if not emitted:
            yield "delta", _extractive_answer(hits)
            yield "done", "extractive"
            return
        yield "done", settings["model"]
    except Exception as exc:  # 流式中断
        logger.warning("大模型流式调用失败：%s", exc)
        if not emitted:
            yield "delta", _extractive_answer(hits)
            yield "done", "extractive"
        else:
            yield "delta", "\n\n（大模型连接中断，请重试。）"
            yield "done", settings["model"]
