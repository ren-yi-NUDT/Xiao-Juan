# -*- coding: utf-8 -*-
from prompts import chat_exec


def test_all_constants_exist():
    for name in ("SYSTEM_PROMPT0", "SYSTEM_PROMPT1", "SYSTEM_PROMPT3",
                 "SYSTEM_PROMPT4", "SYSTEM_PROMPT_DATABASE",
                 "USER_PROMPT_DATABASE", "SYSTEM_PROMPT_LANDMARK_NAV"):
        value = getattr(chat_exec, name)
        assert isinstance(value, str) and value.strip(), f"{name} 为空"


def test_user_prompt_database_format():
    out = chat_exec.USER_PROMPT_DATABASE.format(
        sentences="- 句子一", paragraphs="段落", user_question="问题")
    assert "句子一" in out and "段落" in out and "问题" in out


def test_user_prompt_has_no_extra_placeholders():
    # 除三个已知占位符外不应有其它 {}，否则 .format 会炸
    text = (chat_exec.USER_PROMPT_DATABASE
            .replace("{sentences}", "").replace("{paragraphs}", "")
            .replace("{user_question}", ""))
    assert "{" not in text and "}" not in text


def test_system_prompt1_mentions_two_line_format():
    # SYSTEM_PROMPT1 要求"第一行回复 + 第二行 /指令"
    assert "/" in chat_exec.SYSTEM_PROMPT1
