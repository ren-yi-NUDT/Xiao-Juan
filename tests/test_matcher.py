# -*- coding: utf-8 -*-
from scripts.matcher import ExhibitIntentMatcher

CFG = {
    "area_name": "NG展区",
    "global_excludes": ["机器人"],
    "settings": {"fuzzy_threshold": 50},
    "products": [
        {"id": "P1", "names": ["智能分拣机"], "anchors": ["分拣"], "exclude_words": ["坏了"]},
        {"id": "P2", "names": ["机械臂"], "anchors": ["手臂", "机械臂"], "exclude_words": []},
    ],
}


def test_anchor_and_name_hit():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("这个分拣的智能分拣机叫什么")
    assert r["success"] is True and r["product_id"] == "P1"


def test_global_exclude_blocks():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("机器人分拣机怎么样")
    assert r["success"] is False


def test_product_exclude_blocks():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("分拣机坏了怎么修")
    assert r["success"] is False


def test_no_anchor_no_match():
    m = ExhibitIntentMatcher(CFG)
    r = m.predict("天气怎么样")
    assert r["success"] is False
