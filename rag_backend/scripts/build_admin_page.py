# -*- coding: utf-8 -*-
"""由设计阶段的《管理端原型.html》生成对接真实 API 的管理页面。

只替换数据层与少量文案/控件，界面结构与样式保持原型不变。
运行：python scripts/build_admin_page.py
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # rag_backend/
SOURCE = ROOT / "design" / "管理端原型.html"            # 随本目录独立保存的设计原型
TARGET = ROOT / "web" / "admin.html"

REPLACEMENTS = [
    ("<title>景区智搜 · 管理端原型</title>", "<title>景区智搜 · 管理后台</title>"),
    ('<meta charset="UTF-8">',
     '<meta charset="UTF-8">\n<link rel="icon" href="data:,">'),
    ('<div class="login-hint">交互原型 · 任意账号密码均可进入</div>',
     '<div class="login-hint">默认账号 admin / 密码 admin · 见 config.yaml</div>'),
    ('<input id="loginPwd" type="password" value="123456" placeholder="密码">',
     '<input id="loginPwd" type="password" value="" placeholder="密码">'),
    ('<a href="游客端原型.html" target="_blank">↗ 打开游客端原型</a>',
     '<a href="/visitor" target="_blank">↗ 打开游客端</a>'),
    ('<a href="index.html" target="_blank">↗ 打开设计方案</a>',
     '<a href="/web/index.html" target="_blank">↗ 打开设计方案</a>\n'
     '      <a href="/docs" target="_blank">↗ 打开 API 文档</a>'),
    ('<span class="topbar-right"><span class="tag tg-green">管理员 · admin</span></span>',
     '<span class="topbar-right"><span class="tag tg-green" id="adminTag">管理员 · admin</span></span>'),
    ('<button class="chip on" data-st="all">全部 <span id="cAll"></span></button>',
     '<button class="chip on" data-st="all">全部 <span id="cAll"></span></button>'),
    ('<button class="chip" data-st="已入库">已入库 <span id="cIn"></span></button>',
     '<button class="chip" data-st="approved">已入库 <span id="cIn"></span></button>'),
    ('<button class="chip" data-st="待审核">待审核 <span id="cPend"></span></button>',
     '<button class="chip" data-st="pending">待审核 <span id="cPend"></span></button>'),
    ('<button class="chip" data-st="已下架">已下架 <span id="cOff"></span></button>',
     '<button class="chip" data-st="offline">已下架 <span id="cOff"></span></button>'),
    ('<option>长文档（自动切块）</option>',
     '<option value="long_doc">长文档（自动切块）</option>'),
    ('<option>结构化数据（按条目切块）</option>',
     '<option value="structured">结构化数据（按条目切块）</option>'),
    ('<option>明细表（直接入库，不切块）</option>',
     '<option value="detail">明细表（直接入库，不切块）</option>'),
    ('    <label>文档类型</label>',
     '    <label>选择文件（.docx / .xlsx / .txt / .md）</label>\n'
     '    <input id="upFile" type="file" accept=".docx,.xlsx,.txt,.md">\n'
     '    <label>文档类型</label>'),
    ('<div class="foot-note">景区智搜 · 管理端交互原型 —— 多景区管理：创建 / 删除景区、按景区管理文档、按景区查看检索热词与使用量。景区与热词均与游客端实时同步（localStorage 同源）；无日志时不虚构数据。文档库中 3 份为资料包真实文件，4 份为演示审核流程的示例文档。</div>',
     '<div class="foot-note">景区智搜 · 管理后台 —— FastAPI + SQLite 实现：景区增删、文档上传自动切块与向量化、知识块审核上下架、检索热词统计。统计数据来自 qa_log 真实日志，无日志时不虚构。</div>'),
    ('<span class="hd-sub">使用量来自游客端真实检索日志 · 创建后实时出现在游客端选择页</span>',
     '<span class="hd-sub">使用量来自 qa_log 真实检索日志 · 创建后实时出现在游客端选择页</span>'),
]

EDIT_MODAL = '''
<!-- 编辑知识块弹窗 -->
<div class="modal-mask" id="editMask" onclick="if(event.target===this)closeEdit()">
  <div class="modal">
    <h3>编辑知识块</h3>
    <label>来源位置（标题）</label>
    <input id="editTitle">
    <label>正文</label>
    <textarea id="editContent" rows="9" style="width:100%;border:1px solid var(--border2);border-radius:8px;padding:9px 12px;font-size:13.5px;line-height:1.7;outline:none;resize:vertical"></textarea>
    <div style="display:flex;gap:10px;margin-top:20px">
      <button class="btn btn-primary" style="flex:1" onclick="saveEdit()">保存并重新向量化</button>
      <button class="btn btn-ghost" onclick="closeEdit()">取消</button>
    </div>
  </div>
</div>
'''


def main() -> int:
    html = SOURCE.read_text(encoding="utf-8")
    # 丢掉原型的 localStorage 脚本，换成对接 API 的外部脚本
    html = html.split("<script>")[0]
    for old, new in REPLACEMENTS:
        if old not in html:
            raise SystemExit(f"替换目标未找到，原型可能已改动：{old[:40]}")
        html = html.replace(old, new)

    html = html.replace('<div class="toast" id="toast"></div>',
                        EDIT_MODAL + '\n<div class="toast" id="toast"></div>')
    # 原型的热词进度条是行内 span，宽度不生效；补上块级显示
    html = html.replace('</style>',
                        '.bar-row .track{display:block}\n'
                        '.bar-row .fill{display:block}\n'
                        '#chunkPanel .tbl-wrap{max-height:560px;overflow:auto}\n'
                        '</style>', 1)
    # 原脚本被切掉后，文档尾部的 </body></html> 也一并丢失，这里补回并挂载新脚本
    html = html.rstrip() + (
        '\n\n<script src="/web/admin_app.js"></script>\n</body>\n</html>\n')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(html, encoding="utf-8")
    print(f"已生成：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
