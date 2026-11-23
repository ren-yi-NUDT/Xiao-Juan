# -*- coding: utf-8 -*-
"""首次导入示范景区公开资料包。

用法（在 backend/ 目录下）：
    python scripts/seed.py            # 空库导入
    python scripts/seed.py --force    # 删除旧库后重新导入
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.config import get_config  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.services.importers import seed_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="导入景区公开资料包")
    parser.add_argument("--package", default=None, help="资料包目录（默认取 config.yaml）")
    parser.add_argument("--force", action="store_true", help="删除旧数据库后重新导入")
    parser.add_argument("--max-chars", type=int, default=None, help="单块最大字数")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    cfg = get_config()
    db_path = cfg.app.db_path

    if args.force and os.path.exists(db_path):
        for suffix in ("", "-wal", "-shm"):
            path = db_path + suffix
            if os.path.exists(path):
                os.remove(path)
        print(f"已删除旧数据库：{db_path}")

    init_db()
    package_dir = args.package or cfg.seed.package_dir
    max_chars = args.max_chars or int(getattr(cfg.chunking, "max_chars", 500))

    with session() as conn:
        report = seed_all(
            conn, package_dir, max_chars=max_chars,
            pair=bool(getattr(cfg.chunking, "pair_sentences", True)))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("skipped"):
        print("库中已有景区数据，未重复导入；如需重导请加 --force。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
