# -*- coding: utf-8 -*-
"""切块、场次解析、检索与库迁移的单元测试。"""
import sqlite3

from app.db import migrate
from app.services.chunker import chunks_from_text
from app.services.importers import parse_performances
from app.services.retrieval import expand_query, normalize_query
from app.services.textutil import cut_long, pair_sentences


def test_pair_sentences_merges_neighbours():
    text = "第一句话。第二句话。第三句话。"
    assert pair_sentences(text) == ["第一句话。第二句话。", "第三句话。"]


def test_cut_long_respects_limit():
    text = "。".join(["这是一个用于测试切块长度限制的句子"] * 20) + "。"
    pieces = cut_long(text, max_chars=60)
    assert pieces
    assert all(len(piece) <= 60 for piece in pieces)
    assert "".join(pieces) == text


def test_parse_performances_extracts_show_times():
    info = ("9:00-17:00开放，冬季闭馆时间提前至16:30；"
            "《灵山吉祥颂》演出时间为10:35、11:30、14:00、16:00，每场时长约20分钟。")
    shows = parse_performances(info)
    assert [s["show_time"] for s in shows] == ["10:35", "11:30", "14:00", "16:00"]
    assert shows[0]["duration_min"] == 20


def test_parse_performances_ignores_opening_hours():
    assert parse_performances("全天开放，无时间限制，适合各类时段入园游客观赏。") == []


def test_query_normalization_and_expansion():
    assert normalize_query("请问今天门票多少钱？") == "门票多少钱？"
    expanded = expand_query("带老人半天怎么逛灵山？")
    assert "休息" in expanded and "路线" in expanded


def test_chunks_from_text_keeps_blocks():
    text = "灵山胜境简介\n灵山胜境是国家 5A 级景区。\n\n门票信息\n成人票 210 元。"
    chunks = chunks_from_text(text, title="正文")
    assert len(chunks) >= 2
    assert any("210 元" in c.content for c in chunks)


def test_migrate_adds_session_id_to_old_qa_log():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE qa_log (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL)")
    migrate(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(qa_log)")}
    assert "session_id" in columns
