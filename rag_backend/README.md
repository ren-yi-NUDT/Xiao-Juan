# 小娟 · RAG 后端（软件工程大作业）

数字人景区导览项目的知识检索与问答服务，基于 FastAPI + SQLite。
数据底座与切块/检索思路来自同工作区的《数据库大作业》实现，但本目录是
**独立副本**：在这里改造大模型、多轮会话与流式回答，不影响
`数据库大作业-设计方案/backend` 的交付与演示。

本目录随 `xiao_juan_lmam` 仓库的 `rag_backend` 分支发布。`data/`（SQLite 库、
上传文件）已在 `.gitignore` 中排除；首次运行需用 `scripts/seed.py` 从
`示范景区公开资料包/` 重新导入，克隆到其他位置时用 `--package` 指定资料目录。

切块与向量检索思路同时参照 [Xiao-Juan 仓库 lmam 分支](https://github.com/ren-yi-NUDT/Xiao-Juan/tree/lmam)，
知识库、表结构、管理端均按“多景区 · 多资料形态”设计。

```
rag_backend/
├─ app/
│  ├─ main.py              FastAPI 入口（挂载管理页 / Swagger）
│  ├─ schema.sql           11 张表建表 SQL（可直接作为课程交付）
│  ├─ config.py/yaml       配置（沿用 lmam 的 yaml 约定）
│  ├─ db.py                SQLite 连接 / 初始化
│  ├─ security.py          管理端 HMAC token
│  ├─ routers/
│  │  ├─ admin.py          管理端 API（F5–F7）
│  │  └─ public.py         游客端 / AI 接入 API（F1–F4 的基础）
│  └─ services/
│     ├─ chunker.py        docx 解析与切块（段落 → 句子对 → 带父段落元数据）
│     ├─ embedding.py      可插拔向量：hash（默认）/ bge（可选）
│     ├─ retrieval.py      向量召回 + 关键词覆盖 + 字段意图加权
│     ├─ llm.py            大模型作答（未配置时抽取式回答）
│     ├─ importers.py      三份真实资料的导入
│     └─ docs.py           文档 / 知识块落库
├─ web/                    三端页面（管理端 / 游客端，均由设计阶段原型改造）
├─ scripts/
│  ├─ seed.py              首次导入资料包
│  ├─ check_llm.py         大模型配置校验与连通性自检
│  ├─ build_admin_page.py  由原型重新生成管理页
│  └─ build_visitor_page.py 由原型重新生成游客端
├─ data/                   SQLite 库与上传文件（运行时生成）
└─ tests/                  pytest
```

## 快速开始

```bash
cd rag_backend
pip install -r requirements.txt
python scripts/seed.py          # 首次导入（已导入过可跳过；重导加 --force）
python -m uvicorn app.main:app --reload --port 8765
```

- 游客端：<http://127.0.0.1:8765/visitor>
- 管理后台：<http://127.0.0.1:8765/admin>（默认 `admin / admin`，见 `config.yaml`）
- 接口文档：<http://127.0.0.1:8765/docs>
- 健康检查：<http://127.0.0.1:8765/health>

## 数据底座（11 张表）

| 表 | 内容 | 数据来源 |
| --- | --- | --- |
| `scenic_area` | 景区 | 景点结构化数据集 |
| `attraction` | 景点 22 条 × 11 字段 | 景点结构化数据集 |
| `performance` | 演出 / 讲解场次 20 条 | 从“演艺/开放信息”解析 |
| `knowledge_doc` | 原始文档 4 份 | 三份资料 + 按景区拆分 |
| `knowledge_chunk` | 知识块 208 个（含向量、状态、来源） | 自动切块 |
| `tourist` | 游客 50,000 人 | 行为明细 |
| `visit_record` | 游览记录 140,447 条 | 行为明细 |
| `qa_log` | 问答 / 检索日志（`session_id` 支撑多轮） | 系统运行产生 |
| `qa_log_chunk` | 问答命中的知识块（答案溯源） | 系统运行产生 |
| `feedback` | 纠错反馈 | 游客端产生 |
| `api_key` | 接口密钥 | 管理端签发（接口预留） |

导入结果（`python scripts/seed.py --force` 实测）：

```json
{"areas": 2, "attractions": 22, "performances": 20, "docs": 4,
 "chunks": 208, "tourists": 50000, "visits": 140447}
```

## 切块与向量（对齐 lmam 分支）

1. docx 按标题层级切出“父段落”，保留 `title`（章节路径）与 `parent_text`；
2. 父段落再按句切分，相邻两句合成一个知识块（`chunking.pair_sentences`）；
3. 景点数据集按“景点 × 字段”切块，块标题形如 `LS-006 九龙灌浴 · 演艺/开放信息`；
4. 表格按行切块，票种 / 键值表可直接检索；
5. 每个块写入 `knowledge_chunk.vector`（首期直接存表内，演进方向 pgvector）。

向量默认 `hash`（字 uni/bi-gram 哈希，纯 numpy，无需模型）。在 `config.yaml` 填入
`embedding.bge_model_path` 并把 `provider` 改为 `bge`，安装 `sentence-transformers`
后自动切换为真语义向量，接口与表结构不变。

## 功能对照

| 编号 | 功能 | 实现 |
| --- | --- | --- |
| F1 | AI 导游对话 | `POST /api/public/ask`（多轮 `session_id`；未配置大模型时抽取式回答，答案附引用，引用可点开看原文）与 `/ask/stream`（SSE 流式） |
| F2 | 语义检索 | `POST /api/public/search`（向量 + 关键词 + 字段意图，返回真实相关度与耗时） |
| F3 | 景点与演出查询 | `GET /api/public/areas/{id}/attractions`、`/attractions/{id}` |
| F4 | 纠错反馈 | 游客端点“有误” → `POST /api/public/feedback`；点“有帮助” → `PATCH /api/public/qa/{id}` |
| F5 | 景区与资料管理 | 管理端景区增删、docx/xlsx/txt 上传自动切块向量化 |
| F6 | 知识审核与上下架 | 逐块通过 / 下架 / 恢复待审 / 编辑并重新向量化 |
| F7 | 检索热词分析 | `GET /api/admin/stats/hot`（来自 qa_log 真实日志） |
| F8–F10 | MCP / REST / 密钥 | 下一阶段扩展；`api_key` 表与 `X-API-Key` 校验入口已预留 |

## 多轮会话与流式回答

`POST /api/public/ask` 接受可选 `session_id`：

- 不传时自动生成，并在响应里返回；后续请求带上同一个值即视为同一会话。
- 历史不另建表，直接从 `qa_log` 取同 `session_id` 且已有答案的最近若干轮；
  轮数与总字数上限见 `config.yaml` 的 `chat.history_turns` / `chat.max_history_chars`。
- 旧库首次启动会自动补 `qa_log.session_id` 列与索引（`app/db.py` 的 `migrate()`）。

流式回答 `POST /api/public/ask/stream` 返回 SSE：

```
event: meta   {"qa_id":1,"session_id":"...","citations":[...]}
event: delta  {"text":"..."}
event: done   {"qa_id":1,"session_id":"...","answer":"...","model":"...","took_ms":123}
event: error  {"detail":"生成失败，请重试"}
```

```bash
curl -N -X POST http://127.0.0.1:8765/api/public/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"area_id":"lingshan","q":"演出几点开始"}'
```

## 大模型接入（云 API）

在 `config.yaml` 填 `llm.api_base` 与 `llm.model`，密钥建议用环境变量
`XJ_LLM_API_KEY`，不要写进文件：

| 服务 | api_base | model 示例 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Qwen（DashScope 兼容模式） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

```bash
python scripts/check_llm.py                 # 打印配置 + 发一句最小请求
python scripts/check_llm.py --ask "灵山门票多少钱" --area lingshan
                                            # 走完整 RAG 链路验证答案与引用
```

未配置或调用失败时自动降级为抽取式回答（`model` 字段为 `extractive`），
接口、日志、引用与页面都不受影响；流式接口在中断时也会以 `done` 正常收尾。

## 三端页面

- `web/admin.html`：由 `scripts/build_admin_page.py` 从 `管理端原型.html` 生成，
  数据层换成 `/api/admin/*`。
- `web/visitor.html`：由 `scripts/build_visitor_page.py` 从 `游客端原型.html` 生成，
  景区选择、AI 对话、语义检索、景点导览/详情全部接 `/api/public/*`；
  对话来源可点开核对原文，“有误/有帮助”会写回 `feedback` 与 `qa_log.satisfied`。
- 问答当前为**抽取式回答**（检索原文 + 引用），在 `config.yaml` 填 `llm.api_base`
  与 `llm.model` 后自动升级为大模型生成，页面上的“回答方式”会同步显示模型名。

修改原型后重新运行对应的 `build_*.py` 即可。

## 配置

见 `config.yaml`：

- `app`：端口、管理账号、数据库路径、上传目录
- `embedding`：`hash` / `bge`
- `llm`：OpenAI 兼容地址、模型、温度、`max_tokens`、超时；留空则抽取式回答
- `chat`：多轮历史轮数与总字数上限
- `retrieval`：`top_k`、`min_score`
- `chunking`：单块最大字数、句子配对开关

## 测试

```bash
python -m pytest tests/ -v
```

测试使用独立的临时 SQLite 库，不会改动 `data/xiaojuan.db`。

## 下一步

- MCP 端点与 REST 密钥配额（F8–F10）；游客端接入页目前标注为“下一阶段”，
  已给出真实 REST 接口说明
- 把语音端（`xiao_juan_lmam`）的 RAG 从本地 FAISS 切到 `/api/public/ask`，统一知识源
- 正式 ER 图、关系说明与答辩用查询示例
