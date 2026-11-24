#!/usr/bin/env python3
"""把「灵山胜境」资料包的两份 docx 转成 OpenTalking 知识库用的 Markdown。

策略：
  * 结构化数据集：一行一个景点 → 一个 .md（项目规范：一景点一文件）
  * 游览指南：按主题切成 5 个 .md（总览/文化/其他景点/路线/实用信息）
  * 指南里「核心景点要点表」按景点名并入对应的景点文件，不单独成篇（避免重复召回）

输出到 knowledge/灵山胜境/
"""
from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PROJECT_DIR = Path(__file__).resolve().parents[1]
# 源 docx 随仓库放在 source-data/；老位置（上级的“示范景区公开资料包”）作为兜底
PKG = PROJECT_DIR / "source-data"
if not PKG.is_dir():
    PKG = PROJECT_DIR.parent.parent / "示范景区公开资料包"
DATASET = PKG / "灵山胜境 景点结构化数据集.docx"
GUIDE = PKG / "灵山胜境：历史、文化、景点特色与个性化游览指南.docx"
OUT = PROJECT_DIR / "knowledge" / "灵山胜境"

FIELDS = ["景区名称", "景点ID", "景点名称", "具体位置", "建筑/景观参数", "核心功能",
          "文化内涵", "详细介绍", "游玩亮点", "演艺/开放信息", "备注"]

# 指南要点表 → 景点 ID
GUIDE_TABLE_TO_ID = {
    "灵山大佛": "LS-011",
    "灵山梵宫": "LS-013",
    "九龙灌浴": "LS-006",
    "五印坛城": "LS-014",
    "祥符禅寺": "LS-010",
}


def para_text(p) -> str:
    parts = []
    for node in p.iter():
        if node.tag == W + "t" and node.text:
            parts.append(node.text)
        elif node.tag == W + "br":
            parts.append("\n")
    return "".join(parts).strip()


def cell_text(tc) -> str:
    lines = [para_text(p) for p in tc.iter(W + "p")]
    return " ".join(x for x in lines if x).strip()


def body_blocks(path: Path):
    """按文档顺序产出 ('p', 文本) 和 ('tbl', 行列表)。"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    for child in body:
        if child.tag == W + "p":
            txt = para_text(child)
            if txt:
                yield ("p", txt)
        elif child.tag == W + "tbl":
            rows = [[cell_text(tc) for tc in tr.iter(W + "tc")] for tr in child.iter(W + "tr")]
            if rows:
                yield ("tbl", rows)


def spot_tables(path: Path):
    """取出「景点ID」开头的结构化表，返回 [dict]。"""
    out = []
    for kind, payload in body_blocks(path):
        if kind != "tbl":
            continue
        header = payload[0]
        if "景点ID" not in header:
            continue
        idx = {name: header.index(name) for name in FIELDS if name in header}
        for row in payload[1:]:
            rec = {name: (row[i].strip() if i < len(row) else "") for name, i in idx.items()}
            if rec.get("景点名称") and rec.get("景点ID"):
                out.append(rec)
    return out


def guide_points(path: Path) -> dict[str, list[str]]:
    """把指南里「项目 | 详细信息」两列表，按上面最近的标题挂到景点 ID 上。"""
    result: dict[str, list[str]] = {}
    last_heading = ""
    for kind, payload in body_blocks(path):
        if kind == "p":
            last_heading = payload
            continue
        if len(payload[0]) != 2 or payload[0][0].strip() != "项目":
            continue
        sid = next((v for k, v in GUIDE_TABLE_TO_ID.items() if k in last_heading), None)
        if not sid:
            continue
        bullets = []
        for r in payload[1:]:
            if len(r) >= 2 and r[0].strip():
                bullets.append(f"- **{r[0].strip()}**：{r[1].strip()}")
        if bullets:
            result.setdefault(sid, []).extend(bullets)
    return result


def short(text: str, sep: str = "，") -> str:
    return text.split(sep)[0].strip().strip("。")


def spot_markdown(rec: dict, extra: list[str] | None = None) -> str:
    name = rec["景点名称"]
    area = rec.get("景区名称", "")
    sid = rec.get("景点ID", "")
    loc = rec.get("具体位置", "")
    func = rec.get("核心功能", "")

    bits = []
    if loc:
        bits.append(loc if loc.startswith("位于") else f"位于{short(loc)}")
    if func:
        bits.append(short(func))
    summary = "；".join(b for b in bits if b)
    summary = summary + "。" if summary else ""

    out = [f"# {name}", ""]
    if summary:
        out += [f"**一句话结论**：{summary}", ""]
    out += [f"**所属区域**：{area}　**景点编号**：{sid}", ""]

    for key, title in [
        ("具体位置", "位置"),
        ("建筑/景观参数", "规模与参数"),
        ("核心功能", "功能定位"),
        ("文化内涵", "文化内涵"),
        ("详细介绍", "详细介绍"),
        ("游玩亮点", "游玩亮点"),
        ("演艺/开放信息", "开放与演艺"),
        ("备注", "备注"),
    ]:
        val = rec.get(key, "").strip()
        if val:
            out += [f"## {title}", val, ""]

    if extra:
        out.append("## 补充要点（来自游览指南）")
        out += extra
        out.append("")

    out += ["> 票价、开放时间、演出场次等易变信息，以景区现场公示为准。", ""]
    return "\n".join(out)


GUIDE_SECTIONS = [
    ("00-景区总览与历史", "景区概况与千年历史渊源", "核心文化内涵：佛教传承与艺术融合的典范"),
    ("01-文化内涵与祈福体验", "核心文化内涵：佛教传承与艺术融合的典范", "核心景点特色详解：佛教艺术的殿堂"),
    ("02-其他特色景点", "其他特色景点", "个性化游览路线推荐：深度体验灵山胜境"),
    ("03-个性化游览路线", "个性化游览路线推荐：深度体验灵山胜境", "实用游览贴士：全方位保障你的灵山之旅"),
    ("04-实用信息与贴士", "实用游览贴士：全方位保障你的灵山之旅", None),
]


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    paras = [p for k, p in body_blocks(GUIDE) if k == "p"]
    points = guide_points(GUIDE)
    spots = spot_tables(DATASET)
    print(f"景点 {len(spots)} 个；指南要点表挂载 {len(points)} 处")

    by_id = {r["景点ID"]: r for r in spots}
    for sid, bullets in points.items():
        if sid in by_id:
            print(f"  并表 {sid} {by_id[sid]['景点名称']}：+{len(bullets)} 条要点")
        else:
            print(f"  !! 指南要点找不到对应景点 {sid}", file=sys.stderr)

    n = 0
    for rec in spots:
        area = "拈花湾" if "拈花湾" in rec.get("景区名称", "") else "灵山"
        fname = f"{area}-{rec['景点ID']}-{rec['景点名称']}.md"
        (OUT / fname).write_text(spot_markdown(rec, points.get(rec["景点ID"])), encoding="utf-8")
        n += 1

    for fname, start, end in GUIDE_SECTIONS:
        try:
            i = paras.index(start)
        except ValueError:
            print(f"!! 找不到小节：{start}", file=sys.stderr)
            continue
        j = paras.index(end) if end and end in paras else len(paras)
        md = [f"# {start}", ""] + paras[i + 1:j] + [""]
        (OUT / f"{fname}.md").write_text("\n".join(md), encoding="utf-8")
        n += 1

    print(f"\n写出 {n} 个文件 → {OUT}")
    total = sum(len(f.read_text(encoding='utf-8')) for f in OUT.glob('*.md'))
    print(f"合计 {total} 字")


if __name__ == "__main__":
    main()
