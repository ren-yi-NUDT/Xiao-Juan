# -*- coding: utf-8 -*-
"""由设计阶段的《游客端原型.html》生成接入真实 API 的游客端页面。

只替换数据层与接入说明，界面样式保持原型不变。
运行：python scripts/build_visitor_page.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # rag_backend/
SOURCE = ROOT / "design" / "游客端原型.html"            # 随本目录独立保存的设计原型
TARGET = ROOT / "web" / "visitor.html"

CONNECT_MODAL_OLD = '''<div class="modal-mask" id="connectMask" onclick="if(event.target===this)closeConnect()">
  <div class="modal">
    <h3>把豆包变成灵山专业导游</h3>
    <p class="msub">本系统对 AI 开放 MCP 接口：三步接入，豆包即可检索景区知识库回答问题。</p>
    <div class="mstep"><i>1</i><div><b>复制本系统网址</b><p>mcp://lingshan.example/sse</p></div></div>
    <div class="mstep"><i>2</i><div><b>添加到豆包</b><p>豆包 → 设置 → MCP 工具 → 添加，粘贴网址</p></div></div>
    <div class="mstep"><i>3</i><div><b>开聊</b><p>问豆包任何灵山问题，它已"持证上岗"</p></div></div>
    <div class="tools">豆包获得的工具：<code>search_knowledge(q)</code><code>get_attraction(id)</code><code>get_performances(date)</code><code>plan_route(prefs)</code></div>
    <button class="btn btn-primary" style="width:100%;margin-top:16px" onclick="copyUrl()">复制 MCP 网址</button>
  </div>
</div>'''

CONNECT_MODAL_NEW = '''<div class="modal-mask" id="connectMask" onclick="if(event.target===this)closeConnect()">
  <div class="modal">
    <h3>把豆包 / 其他 AI 接入知识库</h3>
    <p class="msub">当前已开放 REST 接口；MCP 工具接入将在下一阶段提供。</p>
    <div class="mstep"><i>1</i><div><b>复制接口地址</b><p id="apiBase">/api/public</p></div></div>
    <div class="mstep"><i>2</i><div><b>检索知识块</b><p><code>POST /search</code> {"area_id":"lingshan","q":"门票多少钱"}</p></div></div>
    <div class="mstep"><i>3</i><div><b>直接问答</b><p><code>POST /ask</code> 返回答案、引用与命中的知识块</p></div></div>
    <div class="tools">已开放：<code>GET /areas</code><code>GET /attractions/{id}</code><code>POST /search</code><code>POST /ask</code><br>MCP 工具（search_knowledge 等）下一阶段上线。</div>
    <button class="btn btn-primary" style="width:100%;margin-top:16px" onclick="copyUrl()">复制接口地址</button>
  </div>
</div>'''

SOURCE_MODAL = '''
<!-- 知识块原文弹窗 -->
<div class="modal-mask" id="sourceMask" onclick="if(event.target===this)closeSource()">
  <div class="modal">
    <h3 id="srcTitle">知识块原文</h3>
    <p class="msub" id="srcMeta"></p>
    <div class="src-body" id="srcBody"></div>
    <button class="btn btn-ghost" style="width:100%;margin-top:16px" onclick="closeSource()">关闭</button>
  </div>
</div>
'''

REPLACEMENTS = [
    ("<title>景区智搜 · 游客端原型</title>", "<title>景区智搜 · 游客端</title>"),
    ('<meta charset="UTF-8">',
     '<meta charset="UTF-8">\n<link rel="icon" href="data:,">'),
    ('onclick="openConnect()">把豆包变灵山导游</button>',
     'onclick="openConnect()">把 AI 接入知识库</button>'),
    ('''      <h1>灵山 AI 导游</h1>
      <p>答案全部来自景区官方资料库，每条可点开核对来源</p>''',
     '''      <h1 id="chatTitle">AI 导游</h1>
      <p id="chatSub">答案全部来自景区官方资料库，每条可点开核对来源</p>'''),
    ('''    <div class="model-bar">
      模型：<span class="chip on" data-model>内置（豆包 API）</span>
      <span class="chip" data-model>本地 Ollama</span>
      <span class="chip" data-model>填我自己的 Key</span>
    </div>''',
     '''    <div class="model-bar">回答方式：<span class="chip on" id="modelBadge">抽取式（未接大模型）</span></div>'''),
    ('<div class="msg bot">你好，我是灵山 AI 导游。关于灵山胜境与拈花湾的任何问题——景点、演出场次、游览路线——都可以问我。我的每个回答都来自景区资料库，并附来源。</div>',
     '<div class="msg bot" id="chatWelcome">你好，我是 AI 导游。关于景区景点、演出场次、票价与游览路线，都可以问我；每个回答都来自景区资料库，并附来源。</div>'),
    ('''  <div class="filters" id="filters">
    <button class="chip on" data-f="all">全部</button>
    <button class="chip" data-f="LS">胜境板块</button>
    <button class="chip" data-f="NH">拈花湾板块</button>
  </div>''',
     '  <div class="filters" id="filters"></div>'),
    ('<p>《灵山胜境 景点结构化数据集》<br><span id="dSrcId"></span> 全部 11 个结构化字段</p>',
     '<p><span id="dSrcName">后台景点结构化数据集</span><br><span id="dSrcId"></span> · 全部 11 个结构化字段</p>'),
    ('<button class="btn btn-ghost" onclick="openConnect()">在豆包中打开</button>',
     '<button class="btn btn-ghost" onclick="openConnect()">查看接入方式</button>'),
    ('<p style="margin-bottom:4px">本页数据同时是 AI 导游与豆包回答本景点问题的依据。</p>',
     '<p style="margin-bottom:4px">本页数据同时是 AI 导游回答本景点问题的依据。</p>'),
    ('<footer class="footer">景区智搜 · 游客端交互原型 —— 数据来自《灵山胜境 景点结构化数据集》真实资料 · 2026-10</footer>',
     '<footer class="footer">景区智搜 · 游客端 —— 数据来自后台 SQLite 知识库，检索与问答实时走 /api/public 接口</footer>'),
    (CONNECT_MODAL_OLD, CONNECT_MODAL_NEW),
]


def main() -> int:
    html = SOURCE.read_text(encoding="utf-8")
    # 丢掉原型里硬编码的演示脚本，换成对接 API 的外部脚本
    html = html.split("<script>")[0]
    for old, new in REPLACEMENTS:
        if old not in html:
            raise SystemExit(f"替换目标未找到，原型可能已改动：{old[:50]}")
        html = html.replace(old, new)

    html = html.replace('<div class="toast" id="toast"></div>',
                        SOURCE_MODAL + '\n<div class="toast" id="toast"></div>')
    html = html.replace(
        '</style>',
        '.src-body{font-size:14px;line-height:1.8;color:var(--text2);'
        'white-space:pre-wrap;background:var(--bg);border-radius:8px;'
        'padding:12px 14px;margin-top:10px;max-height:320px;overflow:auto}\n'
        '</style>', 1)
    # 原脚本被切掉后，</body></html> 也一并丢失
    html = html.rstrip() + (
        '\n\n<script src="/web/visitor_app.js"></script>\n</body>\n</html>\n')

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(html, encoding="utf-8")
    print(f"已生成：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
