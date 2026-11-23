-- ============================================================
-- 景区智搜 · 数据底座（SQLite 版）
-- 11 张表对应设计方案附B：scenic_area / attraction / performance /
-- knowledge_doc / knowledge_chunk / tourist / visit_record /
-- qa_log / qa_log_chunk / feedback / api_key
-- ============================================================

PRAGMA foreign_keys = ON;

-- ---------- 1. 景区 ----------
CREATE TABLE IF NOT EXISTS scenic_area (
    id          TEXT PRIMARY KEY,              -- lingshan / nianhuawan / area_xxx
    name        TEXT NOT NULL UNIQUE,          -- 景区名称
    tag         TEXT    DEFAULT '',            -- 一句话标签（游客端选择页展示）
    level       TEXT    DEFAULT '',            -- 等级，如 国家AAAAA级
    intro       TEXT    DEFAULT '',            -- 简介
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------- 2. 景点（结构化数据集 22 行 × 11 字段） ----------
CREATE TABLE IF NOT EXISTS attraction (
    id                TEXT PRIMARY KEY,        -- LS-001 / NH-001
    area_id           TEXT NOT NULL REFERENCES scenic_area(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    location          TEXT,                    -- 具体位置
    params            TEXT,                    -- 建筑 / 景观参数
    core_function     TEXT,                    -- 核心功能
    culture           TEXT,                    -- 文化内涵
    detail            TEXT,                    -- 详细介绍
    highlights        TEXT,                    -- 游玩亮点
    performance_info  TEXT,                    -- 演艺 / 开放信息
    remark            TEXT,                    -- 备注
    sort_order        INTEGER DEFAULT 0
);

-- ---------- 3. 演出场次 ----------
CREATE TABLE IF NOT EXISTS performance (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attraction_id TEXT NOT NULL REFERENCES attraction(id) ON DELETE CASCADE,
    show_time     TEXT NOT NULL,               -- '10:00'
    duration_min  INTEGER,                     -- 时长（分钟），可空
    note          TEXT,                        -- 场次说明 / 来源原文
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------- 4. 原始文档 ----------
CREATE TABLE IF NOT EXISTS knowledge_doc (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id      TEXT NOT NULL REFERENCES scenic_area(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,                -- 文档名
    doc_type     TEXT NOT NULL,                -- long_doc / structured / detail
    source_file  TEXT DEFAULT '',              -- 原始文件名
    file_size    INTEGER DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'approved',  -- approved / pending / offline / error
    chunk_count  INTEGER DEFAULT 0,
    note         TEXT DEFAULT '',
    uploaded_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (area_id, name)
);

-- ---------- 5. 知识块（检索与引用的最小单元） ----------
CREATE TABLE IF NOT EXISTS knowledge_chunk (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id        INTEGER NOT NULL REFERENCES knowledge_doc(id) ON DELETE CASCADE,
    area_id       TEXT NOT NULL REFERENCES scenic_area(id) ON DELETE CASCADE,
    attraction_id TEXT REFERENCES attraction(id) ON DELETE SET NULL,
    seq           INTEGER NOT NULL DEFAULT 0,  -- 文档内块序号
    title         TEXT DEFAULT '',             -- 来源位置：章节 / 景点字段
    content       TEXT NOT NULL,               -- 块正文
    parent_text   TEXT DEFAULT '',             -- 父段落（沿用 lmam 切块元数据）
    vector        BLOB,                        -- 语义向量（首期直接存表内）
    embed_model   TEXT DEFAULT '',             -- 向量化所用模型标识
    char_count    INTEGER DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending / approved / offline
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------- 6. 游客 ----------
CREATE TABLE IF NOT EXISTS tourist (
    id        TEXT PRIMARY KEY,                -- U00001
    nickname  TEXT,
    age       INTEGER,
    gender    TEXT
);

-- ---------- 7. 游览记录（行为明细，17 列去重后的规范化事实表） ----------
CREATE TABLE IF NOT EXISTS visit_record (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    tourist_id         TEXT REFERENCES tourist(id) ON DELETE SET NULL,
    attraction_name    TEXT,
    attraction_type    TEXT,
    visit_date         TEXT,
    stay_duration      REAL,
    ticket_cost        REAL,
    food_cost          REAL,
    shopping_cost      REAL,
    transport_cost     REAL,
    entertainment_cost REAL,
    total_cost         REAL,
    group_size         INTEGER,
    satisfaction       INTEGER
);

-- ---------- 8. 问答日志（网页 / 豆包 / 第三方共用） ----------
CREATE TABLE IF NOT EXISTS qa_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id    TEXT REFERENCES scenic_area(id) ON DELETE CASCADE,
    source     TEXT NOT NULL DEFAULT 'web',    -- web / doubao / api
    ip         TEXT DEFAULT '',
    session_id TEXT DEFAULT '',                -- 多轮会话标识；空 = 单轮 / 检索日志
    question   TEXT NOT NULL,
    answer     TEXT,
    model      TEXT DEFAULT '',
    latency_ms INTEGER DEFAULT 0,
    satisfied  INTEGER,                        -- 1 / 0 / NULL 未评价
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------- 9. 命中关联（答案溯源的实现） ----------
CREATE TABLE IF NOT EXISTS qa_log_chunk (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    qa_id    INTEGER NOT NULL REFERENCES qa_log(id) ON DELETE CASCADE,
    chunk_id INTEGER REFERENCES knowledge_chunk(id) ON DELETE SET NULL,
    rank     INTEGER DEFAULT 0,
    score    REAL DEFAULT 0,
    UNIQUE (qa_id, chunk_id)
);

-- ---------- 10. 纠错反馈 ----------
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    qa_id       INTEGER REFERENCES qa_log(id) ON DELETE SET NULL,
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending / resolved / rejected
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    resolved_at TEXT
);

-- ---------- 11. 接口密钥 ----------
CREATE TABLE IF NOT EXISTS api_key (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL UNIQUE,
    client_name TEXT NOT NULL,                 -- 豆包 / 小程序 / 第三方
    daily_limit INTEGER DEFAULT 1000,
    status      TEXT NOT NULL DEFAULT 'active',-- active / disabled
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_used_at TEXT
);

-- ---------- 索引 ----------
CREATE INDEX IF NOT EXISTS idx_attraction_area      ON attraction(area_id);
CREATE INDEX IF NOT EXISTS idx_performance_attr     ON performance(attraction_id);
CREATE INDEX IF NOT EXISTS idx_doc_area             ON knowledge_doc(area_id, status);
CREATE INDEX IF NOT EXISTS idx_chunk_area_status    ON knowledge_chunk(area_id, status);
CREATE INDEX IF NOT EXISTS idx_chunk_doc            ON knowledge_chunk(doc_id, seq);
CREATE INDEX IF NOT EXISTS idx_visit_tourist        ON visit_record(tourist_id);
CREATE INDEX IF NOT EXISTS idx_visit_date           ON visit_record(visit_date);
CREATE INDEX IF NOT EXISTS idx_qa_area_time         ON qa_log(area_id, created_at);
CREATE INDEX IF NOT EXISTS idx_qa_question          ON qa_log(question);
-- 注意：qa_log.session_id 的索引由 db.migrate() 创建。
-- 旧库执行建表脚本时会跳过 CREATE TABLE IF NOT EXISTS，
-- 若在此处建 session_id 索引会先于 ALTER 执行而报错。
CREATE INDEX IF NOT EXISTS idx_qac_qa               ON qa_log_chunk(qa_id);
