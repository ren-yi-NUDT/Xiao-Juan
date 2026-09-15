# -*- coding: utf-8 -*-
from scripts.llm import is_valid_command, parse_command, parse_llm_result


def test_parse_command_no_param():
    assert parse_command("/start") == {"action": "start", "param": {"marker_id": ""}}


def test_parse_command_with_param():
    assert parse_command("/move_to Landmark1") == {
        "action": "move_to", "param": {"marker_id": "Landmark1"}}


def test_is_valid_command_accepts_whitelist():
    assert is_valid_command("好的。\n/move_to Landmark1") is True
    assert is_valid_command("好的。\n/start") is True


def test_is_valid_command_rejects_unknown():
    assert is_valid_command("好的。\n/destroy_world") is False


def test_parse_llm_result_intent_a():
    command, reply = parse_llm_result("A", "好的，带你去。\n/move_to Landmark2")
    assert command == {"action": "move_to", "param": {"marker_id": "Landmark2"}}
    assert reply == "好的，带你去。"


def test_parse_llm_result_intent_b_and_c():
    assert parse_llm_result("B", "答案")[0] == {"action": "talk_database", "param": ""}
    assert parse_llm_result("C", "哈喽")[0] == {"action": "talk", "param": ""}
