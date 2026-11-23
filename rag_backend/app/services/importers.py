# -*- coding: utf-8 -*-
"""把示范景区公开资料包导入 11 张表。

三类资料各有归宿：
  * 景点结构化数据集（docx 表格）-> scenic_area / attraction / performance + 字段级知识块
  * 游览指南（docx 长文档）      -> knowledge_doc / knowledge_chunk（按章节切块）
  * 游客行为明细（xlsx）          -> tourist / visit_record（直接入库，不切块）
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import openpyxl

from app.services.chunker import Chunk, chunks_from_docx, load_docx
from app.services.docs import add_chunks, create_doc
from app.services.textutil import clean_text, cut_long

logger = logging.getLogger(__name__)

ATTRACTION_FILE = "灵山胜境 景点结构化数据集.docx"
GUIDE_FILE = "灵山胜境：历史、文化、景点特色与个性化游览指南.docx"
BEHAVIOR_FILE = "景点景区旅游数据行为分析数据.xlsx"

AREA_META = {
    "灵山胜境": {
        "id": "lingshan",
        "tag": "国家 5A · 世界佛教论坛永久会址",
        "level": "国家AAAAA级旅游景区",
        "intro": "集佛教文化、自然景观、人文体验于一体的综合性景区，灵山胜境与拈花湾禅意小镇两大板块。",
    },
    "拈花湾禅意小镇": {
        "id": "nianhuawan",
        "tag": "禅意小镇 · 东方禅意度假目的地",
        "level": "",
        "intro": "以禅意文化为主题的度假小镇，与灵山胜境相邻，侧重禅意休闲体验。",
    },
}

FIELD_ORDER = [
    "景区名称", "景点ID", "景点名称", "具体位置", "建筑/景观参数",
    "核心功能", "文化内涵", "详细介绍", "游玩亮点", "演艺/开放信息", "备注",
]

# 只对“有检索价值”的字段建块；景区名 / 景点 ID / 名称本身已写在标题里，单独成块只会干扰召回。
CHUNK_FIELDS = [
    "具体位置", "建筑/景观参数", "核心功能", "文化内涵",
    "详细介绍", "游玩亮点", "演艺/开放信息", "备注",
]

_PERF_KEYWORDS = ("演出", "表演", "场次", "讲解", "讲座", "仪式", "禅行",
                  "灯光秀", "秀", "开园", "加演", "场")
_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
_RANGE_RE = re.compile(
    r"([01]?\d|2[0-3]):[0-5]\d\s*[-–—~至]\s*([01]?\d|2[0-3]):[0-5]\d")
_DURATION_RE = re.compile(r"时长约?\s*(\d+)\s*分钟")


def area_for_name(name: str) -> dict:
    if name in AREA_META:
        return {**AREA_META[name], "name": name}
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    return {"id": f"area_{digest}", "name": name, "tag": "", "level": "", "intro": ""}


def read_attractions(path: str | Path) -> list[dict]:
    doc = load_docx(path)
    records: list[dict] = []
    for table in doc.tables:
        rows = [[clean_text(cell.text) for cell in row.cells] for row in table.rows]
        if not rows or "景点ID" not in rows[0]:
            continue
        headers = rows[0]
        for row in rows[1:]:
            record = dict(zip(headers, row))
            if record.get("景点ID"):
                records.append(record)
    return records


def parse_performances(info: str) -> list[dict]:
    """从“演艺/开放信息”里抽取演出 / 讲解场次。

    先按标点切段，只保留含演出关键词的段；段内的开放时间段（9:00-17:00）整体剔除，
    避免把闭馆时间误当成演出场次。
    """
    info = clean_text(info)
    if not info:
        return []
    duration_match = _DURATION_RE.search(info)
    duration = int(duration_match.group(1)) if duration_match else None

    found: list[tuple[str, str]] = []
    for segment in re.split(r"[；;。]", info):
        if not any(keyword in segment for keyword in _PERF_KEYWORDS):
            continue
        masked = _RANGE_RE.sub(" ", segment)
        for match in _TIME_RE.finditer(masked):
            hour = int(match.group(1))
            found.append((f"{hour:02d}:{match.group(2)}", segment.strip()))

    result: list[dict] = []
    seen: set[str] = set()
    for show_time, note in found:
        if show_time in seen:
            continue
        seen.add(show_time)
        result.append({
            "show_time": show_time,
            "duration_min": duration,
            "note": note[:300],
        })
    return result


def attraction_field_chunks(records: list[dict], max_chars: int = 500,
                            pair: bool = True) -> list[Chunk]:
    out: list[Chunk] = []
    for record in records:
        rid = record.get("景点ID", "")
        name = record.get("景点名称", "")
        parent = "；".join(
            f"{key}：{value}" for key, value in record.items() if value)
        for field_name in CHUNK_FIELDS:
            value = record.get(field_name, "")
            if not value:
                continue
            for piece in cut_long(value, max_chars, pair):
                out.append(Chunk(
                    title=f"{rid} {name} · {field_name}".strip(),
                    content=piece,
                    parent_text=parent,
                    attraction_id=rid or None,
                ))
    return out


def _to_int(value):
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def import_behavior_xlsx(conn, path: str | Path, doc_id: int,
                         batch_size: int = 2000) -> int:
    """行为明细 -> tourist + visit_record。返回导入的明细行数。"""
    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    row_iter = sheet.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(row_iter)]
    index = {name: i for i, name in enumerate(header)}
    if not {"tourist_id", "attraction_name", "visit_date"}.issubset(index):
        raise ValueError("明细表缺少必需列：tourist_id / attraction_name / visit_date")

    def value(row, key):
        i = index.get(key)
        return row[i] if i is not None and i < len(row) else None

    tourists: list[tuple] = []
    seen_tourists: set[str] = set()
    visits: list[tuple] = []
    total = 0

    def flush():
        nonlocal tourists, visits
        if tourists:
            conn.executemany(
                "INSERT OR IGNORE INTO tourist (id, nickname, age, gender) VALUES (?, ?, ?, ?)",
                tourists)
            tourists = []
        if visits:
            conn.executemany(
                """INSERT INTO visit_record
                   (tourist_id, attraction_name, attraction_type,
                    visit_date, stay_duration, ticket_cost, food_cost, shopping_cost,
                    transport_cost, entertainment_cost, total_cost, group_size, satisfaction)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                visits)
            visits = []

    for row in row_iter:
        tourist_id = str(value(row, "tourist_id") or "").strip()
        if not tourist_id:
            continue
        if tourist_id not in seen_tourists:
            seen_tourists.add(tourist_id)
            tourists.append((
                tourist_id,
                value(row, "user_nickname"),
                _to_int(value(row, "age")),
                value(row, "gender"),
            ))
        visit_date = value(row, "visit_date")
        visits.append((
            tourist_id,
            value(row, "attraction_name"),
            value(row, "attraction_type"),
            str(visit_date)[:10] if visit_date is not None else None,
            _to_float(value(row, "stay_duration")),
            _to_float(value(row, "ticket_cost")),
            _to_float(value(row, "food_cost")),
            _to_float(value(row, "shopping_cost")),
            _to_float(value(row, "transport_cost")),
            _to_float(value(row, "entertainment_cost")),
            _to_float(value(row, "total_cost")),
            _to_int(value(row, "group_size")),
            _to_int(value(row, "satisfaction")),
        ))
        total += 1
        if len(visits) >= batch_size:
            flush()
    flush()
    workbook.close()
    conn.execute(
        "UPDATE knowledge_doc SET note=? WHERE id=?",
        (f"{total:,} 行行为明细直接入库（tourist / visit_record），不参与知识切块", doc_id))
    return total


def seed_all(conn, package_dir: str | Path, max_chars: int = 500,
             pair: bool = True) -> dict:
    package_dir = Path(package_dir)
    report = {"skipped": False, "areas": 0, "attractions": 0, "performances": 0,
              "docs": 0, "chunks": 0, "tourists": 0, "visits": 0}

    if conn.execute("SELECT COUNT(*) FROM scenic_area").fetchone()[0]:
        report["skipped"] = True
        return report

    attraction_path = package_dir / ATTRACTION_FILE
    guide_path = package_dir / GUIDE_FILE
    behavior_path = package_dir / BEHAVIOR_FILE
    for path in (attraction_path, guide_path, behavior_path):
        if not path.exists():
            raise FileNotFoundError(f"资料包缺少文件：{path}")

    records = read_attractions(attraction_path)
    logger.info("读取景点 %d 个", len(records))

    # ---------- 景区 ----------
    areas: dict[str, dict] = {}
    for record in records:
        meta = area_for_name(record["景区名称"])
        if meta["id"] in areas:
            continue
        areas[meta["id"]] = meta
        conn.execute(
            """INSERT INTO scenic_area (id, name, tag, level, intro)
               VALUES (?, ?, ?, ?, ?)""",
            (meta["id"], meta["name"], meta["tag"], meta["level"], meta["intro"]))
        report["areas"] += 1

    # ---------- 景点 + 演出场次 ----------
    performance_rows = []
    for order, record in enumerate(records):
        meta = area_for_name(record["景区名称"])
        conn.execute(
            """INSERT INTO attraction
               (id, area_id, name, location, params, core_function, culture,
                detail, highlights, performance_info, remark, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record["景点ID"], meta["id"], record.get("景点名称", ""),
             record.get("具体位置", ""), record.get("建筑/景观参数", ""),
             record.get("核心功能", ""), record.get("文化内涵", ""),
             record.get("详细介绍", ""), record.get("游玩亮点", ""),
             record.get("演艺/开放信息", ""), record.get("备注", ""), order))
        report["attractions"] += 1
        for perf in parse_performances(record.get("演艺/开放信息", "")):
            performance_rows.append(
                (record["景点ID"], perf["show_time"], perf["duration_min"], perf["note"]))
    if performance_rows:
        conn.executemany(
            """INSERT INTO performance (attraction_id, show_time, duration_min, note)
               VALUES (?, ?, ?, ?)""", performance_rows)
        report["performances"] = len(performance_rows)

    # ---------- 结构化资料：按景区各建一份文档，按字段切块 ----------
    for area_id, meta in areas.items():
        subset = [r for r in records if area_for_name(r["景区名称"])["id"] == area_id]
        doc_name = (ATTRACTION_FILE if area_id == "lingshan"
                    else f"{meta['name']} 景点结构化数据集.docx")
        doc_id = create_doc(
            conn, area_id, doc_name, "structured",
            source_file=ATTRACTION_FILE,
            file_size=attraction_path.stat().st_size,
            status="approved",
            note=f"{len(subset)} 个景点的 11 个字段按字段切块")
        count = add_chunks(conn, doc_id, area_id,
                           attraction_field_chunks(subset, max_chars, pair),
                           status="approved")
        conn.execute("UPDATE knowledge_doc SET chunk_count=? WHERE id=?", (count, doc_id))
        report["docs"] += 1
        report["chunks"] += count

    # ---------- 游览指南：长文档按章节切块 ----------
    guide_doc_id = create_doc(
        conn, "lingshan", GUIDE_FILE, "long_doc",
        source_file=GUIDE_FILE,
        file_size=guide_path.stat().st_size,
        status="approved",
        note="约万字游览指南，按章节/句子切块")
    guide_chunks = chunks_from_docx(guide_path, "long_doc", max_chars, pair)
    count = add_chunks(conn, guide_doc_id, "lingshan", guide_chunks, status="approved")
    conn.execute("UPDATE knowledge_doc SET chunk_count=? WHERE id=?", (count, guide_doc_id))
    report["docs"] += 1
    report["chunks"] += count

    # ---------- 行为明细：直接入库 ----------
    behavior_doc_id = create_doc(
        conn, "lingshan", BEHAVIOR_FILE, "detail",
        source_file=BEHAVIOR_FILE,
        file_size=behavior_path.stat().st_size,
        status="approved",
        note="明细表直接入库，不参与知识切块")
    report["visits"] = import_behavior_xlsx(conn, behavior_path, behavior_doc_id)
    report["tourists"] = conn.execute("SELECT COUNT(*) FROM tourist").fetchone()[0]
    report["docs"] += 1

    return report
