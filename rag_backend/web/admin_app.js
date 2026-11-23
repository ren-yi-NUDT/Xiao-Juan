/* ============================================================
   景区智搜 · 管理后台前端
   数据源：/api/admin/*（FastAPI + SQLite），不再使用 localStorage
   ============================================================ */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let TOKEN = sessionStorage.getItem('xj_admin_token') || '';
let AREAS = [];
let DOCS = [];
let CUR_CHUNKS = [];
let curDocId = null;
let editingChunkId = null;
let areaFilter = 'all';
let docFilter = 'all';
let hotScope = 'all';
let uploading = false;

const DOC_STATUS = {
  approved: ['已入库', 'tg-green'],
  pending: ['待审核', 'tg-orange'],
  offline: ['已下架', 'tg-red'],
  error: ['解析失败', 'tg-red'],
};
const DOC_TYPE_LABEL = { long_doc: '长文档', structured: '结构化数据', detail: '明细表' };

/* ---------------- 工具 ---------------- */
function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove('show'), 2400);
}
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}
async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (TOKEN) headers['Authorization'] = 'Bearer ' + TOKEN;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    showLogin();
    throw new Error('登录已过期，请重新登录');
  }
  if (!response.ok) {
    let message = '请求失败（' + response.status + '）';
    try {
      const data = await response.json();
      if (data.detail) {
        message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch (e) { /* 非 JSON 响应 */ }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

/* ---------------- 登录 ---------------- */
async function doLogin() {
  const username = $('#loginUser').value.trim();
  const password = $('#loginPwd').value;
  try {
    const response = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || '账号或密码错误');
    }
    const data = await response.json();
    TOKEN = data.token;
    sessionStorage.setItem('xj_admin_token', TOKEN);
    $('#adminTag').textContent = '管理员 · ' + data.user;
    enterShell();
  } catch (error) {
    toast(error.message);
  }
}
function enterShell() {
  $('#loginMask').classList.add('hide');
  $('#shell').classList.add('show');
  if (!location.hash) location.hash = '#/areas';
  router();
}
function showLogin() {
  $('#shell').classList.remove('show');
  $('#loginMask').classList.remove('hide');
}
function logout() {
  TOKEN = '';
  sessionStorage.removeItem('xj_admin_token');
  showLogin();
  toast('已退出登录');
}
async function boot() {
  bindStatusTabs();
  if (TOKEN) {
    try {
      const me = await api('/api/admin/me');
      $('#adminTag').textContent = '管理员 · ' + me.user;
      enterShell();
      return;
    } catch (error) { /* 令牌失效，回到登录页 */ }
  }
  showLogin();
}

/* ---------------- 景区（F5） ---------------- */
async function loadAreas() {
  try {
    AREAS = await api('/api/admin/areas');
    if (areaFilter !== 'all' && !AREAS.some((a) => a.id === areaFilter)) areaFilter = 'all';
    if (hotScope !== 'all' && !AREAS.some((a) => a.id === hotScope)) hotScope = 'all';
    renderAreas();
    renderAreaChips();
    renderHotAreaChips();
  } catch (error) { toast(error.message); }
}
function areaName(id) {
  const found = AREAS.find((a) => a.id === id);
  return found ? found.name : '（未知景区）';
}
function renderAreas() {
  const body = $('#areaBody');
  if (!AREAS.length) {
    body.innerHTML = '<tr><td colspan="8"><div class="empty">还没有景区，点击右上角“创建景区”</div></td></tr>';
    return;
  }
  body.innerHTML = AREAS.map((a) => `<tr>
      <td><strong>${esc(a.name)}</strong></td>
      <td>${esc(a.tag || '—')}</td>
      <td>${a.docs}</td><td>${a.chunks}</td><td>${a.hits}</td><td>${a.words}</td>
      <td>${esc((a.created_at || '').slice(0, 10))}</td>
      <td>
        <button class="btn btn-ghost" onclick="manageDocs('${a.id}')">管理文档</button>
        <button class="btn btn-ghost" onclick="manageHot('${a.id}')">热词</button>
        <button class="btn btn-danger" onclick="deleteArea('${a.id}')">删除</button>
      </td>
    </tr>`).join('');
}
function manageDocs(id) { areaFilter = id; location.hash = '#/docs'; }
function manageHot(id) { hotScope = id; location.hash = '#/hot'; }
function openAreaModal() {
  $('#areaName').value = '';
  $('#areaTag').value = '';
  $('#areaMask').classList.add('show');
  $('#areaName').focus();
}
function closeAreaModal() { $('#areaMask').classList.remove('show'); }
async function createArea() {
  const name = $('#areaName').value.trim();
  const tag = $('#areaTag').value.trim();
  if (!name) { toast('请填写景区名称'); return; }
  try {
    const area = await api('/api/admin/areas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, tag }),
    });
    closeAreaModal();
    await loadAreas();
    toast(`景区「${area.name}」已创建，游客端选择页同步可见`);
  } catch (error) { toast(error.message); }
}
async function deleteArea(id) {
  const area = AREAS.find((a) => a.id === id);
  if (!area) return;
  if (!confirm(`确认删除景区「${area.name}」？\n将同时移除其 ${area.docs} 份文档、${area.chunks} 个知识块，游客端选择页同步下线。`)) return;
  try {
    await api('/api/admin/areas/' + encodeURIComponent(id), { method: 'DELETE' });
    if (areaFilter === id) areaFilter = 'all';
    if (hotScope === id) hotScope = 'all';
    await loadAreas();
    if (currentPage() === 'docs') await loadDocs();
    toast(`景区「${area.name}」已删除`);
  } catch (error) { toast(error.message); }
}

/* ---------------- 文档（F5） ---------------- */
async function loadDocs() {
  try {
    const params = new URLSearchParams();
    if (areaFilter !== 'all') params.set('area_id', areaFilter);
    const query = params.toString();
    DOCS = await api('/api/admin/docs' + (query ? '?' + query : ''));
    renderDocs();
  } catch (error) { toast(error.message); }
}
function renderAreaChips() {
  $('#areaChips').innerHTML =
    `<span class="chip ${areaFilter === 'all' ? 'on' : ''}" onclick="setArea('all')">全部景区</span>` +
    AREAS.map((a) => `<span class="chip ${areaFilter === a.id ? 'on' : ''}" onclick="setArea('${a.id}')">${esc(a.name)}</span>`).join('');
}
function setArea(id) { areaFilter = id; renderAreaChips(); loadDocs(); }
function docCounts(list) {
  $('#cAll').textContent = `(${list.length})`;
  $('#cIn').textContent = `(${list.filter((d) => d.status === 'approved').length})`;
  $('#cPend').textContent = `(${list.filter((d) => d.status === 'pending').length})`;
  $('#cOff').textContent = `(${list.filter((d) => d.status === 'offline').length})`;
}
function renderDocs() {
  const keyword = ($('#docSearch').value || '').trim();
  const scoped = DOCS.filter((d) => !keyword || d.name.includes(keyword));
  docCounts(scoped);
  $('#docsSub').textContent =
    `${areaFilter === 'all' ? '全部景区' : areaName(areaFilter)} · 上传后自动切块、向量化 · 点击行管理知识块`;
  const rows = scoped.filter((d) => docFilter === 'all' || d.status === docFilter);
  const body = $('#docBody');
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7"><div class="empty">没有符合条件的文档</div></td></tr>';
    return;
  }
  body.innerHTML = rows.map((d) => {
    const [label, cls] = DOC_STATUS[d.status] || [d.status, 'tg-blue'];
    const chunkCell = d.doc_type === 'detail'
      ? '<span style="color:var(--text3)">直接入库</span>'
      : `${d.chunk_count} 块`;
    return `<tr class="rowdoc" onclick="showChunks(${d.id})">
        <td><strong>${esc(d.name)}</strong></td>
        <td><span class="tag tg-blue">${esc(d.area_name)}</span></td>
        <td>${DOC_TYPE_LABEL[d.doc_type] || esc(d.doc_type)}</td>
        <td>${chunkCell}</td>
        <td><span class="tag ${cls}">${label}</span></td>
        <td>${esc((d.uploaded_at || '').slice(0, 10))}</td>
        <td><button class="btn btn-ghost" onclick="event.stopPropagation();showChunks(${d.id})">查看</button></td>
      </tr>`;
  }).join('');
}
function bindStatusTabs() {
  $$('[data-st]').forEach((chip) => chip.addEventListener('click', () => {
    $$('[data-st]').forEach((x) => x.classList.remove('on'));
    chip.classList.add('on');
    docFilter = chip.dataset.st;
    renderDocs();
  }));
}

/* ---------------- 知识块审核（F6） ---------------- */
async function showChunks(docId) {
  const doc = DOCS.find((d) => d.id === docId);
  if (!doc) return;
  curDocId = docId;
  $('#chunkTitle').textContent = `${doc.name} · ${doc.area_name}`;
  const body = $('#chunkBody');
  try {
    const chunks = await api(`/api/admin/docs/${docId}/chunks`);
    CUR_CHUNKS = chunks;
    if (doc.doc_type === 'detail') {
      body.innerHTML = '<tr><td colspan="6"><div class="empty">该文档为明细表，按事实表直接入库，不参与知识切块</div></td></tr>';
    } else if (!chunks.length) {
      body.innerHTML = '<tr><td colspan="6"><div class="empty">暂无知识块</div></td></tr>';
    } else {
      body.innerHTML = chunks.map((c) => {
        const [label, cls] = DOC_STATUS[c.status] || [c.status, 'tg-blue'];
        const vector = c.embed_model
          ? '<span class="tag tg-blue">已向量化</span>'
          : '<span class="tag tg-orange">待向量化</span>';
        const content = c.content || '';
        return `<tr>
            <td><code>#${c.id}</code></td>
            <td>${esc(c.title || '—')}</td>
            <td style="max-width:300px">${esc(content.slice(0, 80))}${content.length > 80 ? '…' : ''}</td>
            <td>${vector}</td>
            <td><span class="tag ${cls}">${label}</span></td>
            <td>${chunkOps(c)}</td>
          </tr>`;
      }).join('');
    }
    $('#chunkPanel').style.display = 'block';
    $('#chunkPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) { toast(error.message); }
}
function chunkOps(chunk) {
  const edit = `<button class="btn btn-ghost" onclick="editChunk(${chunk.id})">编辑</button>`;
  if (chunk.status === 'pending') {
    return `<button class="btn btn-primary" onclick="setChunk(${chunk.id},'approved')">通过</button> `
      + `<button class="btn btn-danger" onclick="setChunk(${chunk.id},'offline')">下架</button> ${edit}`;
  }
  if (chunk.status === 'approved') {
    return `<button class="btn btn-danger" onclick="setChunk(${chunk.id},'offline')">下架</button> ${edit}`;
  }
  return `<button class="btn btn-ghost" onclick="setChunk(${chunk.id},'pending')">恢复待审</button> ${edit}`;
}
async function setChunk(id, status) {
  try {
    await api('/api/admin/chunks/' + id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    toast(`知识块 #${id} → ${(DOC_STATUS[status] || [status])[0]}`);
    await showChunks(curDocId);
    await loadDocs();
    await loadAreas();
  } catch (error) { toast(error.message); }
}
function closeChunks() { $('#chunkPanel').style.display = 'none'; }

function editChunk(id) {
  const chunk = CUR_CHUNKS.find((c) => c.id === id);
  if (!chunk) return;
  editingChunkId = id;
  $('#editTitle').value = chunk.title || '';
  $('#editContent').value = chunk.content || '';
  $('#editMask').classList.add('show');
}
function closeEdit() { $('#editMask').classList.remove('show'); }
async function saveEdit() {
  const title = $('#editTitle').value.trim();
  const content = $('#editContent').value.trim();
  if (!content) { toast('正文不能为空'); return; }
  try {
    await api('/api/admin/chunks/' + editingChunkId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content }),
    });
    closeEdit();
    toast('已保存并重新向量化');
    await showChunks(curDocId);
  } catch (error) { toast(error.message); }
}

/* ---------------- 上传新文档 ---------------- */
function openUpload() {
  if (!AREAS.length) { toast('请先创建景区'); return; }
  $('#upArea').innerHTML = AREAS.map((a) =>
    `<option value="${a.id}" ${a.id === areaFilter ? 'selected' : ''}>${esc(a.name)}</option>`).join('');
  $('#upName').value = '';
  $('#upFile').value = '';
  $('#upType').value = 'long_doc';
  $('#upProg').classList.remove('show');
  $('#upBar').style.width = '0';
  $('#upGo').disabled = false;
  $('#uploadMask').classList.add('show');
}
function closeUpload() { $('#uploadMask').classList.remove('show'); }
function startUpload() {
  if (uploading) return;
  const areaId = $('#upArea').value;
  const file = $('#upFile').files[0];
  const docType = $('#upType').value;
  if (!file) { toast('请选择要上传的文件'); return; }
  const suffix = (file.name.split('.').pop() || '').toLowerCase();
  if (docType === 'detail' && suffix !== 'xlsx') { toast('明细表请上传 .xlsx 文件'); return; }
  if (docType !== 'detail' && !['docx', 'txt', 'md'].includes(suffix)) {
    toast('该类型请上传 .docx / .txt / .md 文件'); return;
  }

  uploading = true;
  $('#upGo').disabled = true;
  $('#upProg').classList.add('show');
  const bar = $('#upBar');
  bar.style.width = '0';

  const form = new FormData();
  form.append('area_id', areaId);
  form.append('name', $('#upName').value.trim());
  form.append('doc_type', docType);
  form.append('file', file);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/admin/docs');
  xhr.setRequestHeader('Authorization', 'Bearer ' + TOKEN);
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) {
      bar.style.width = Math.round((event.loaded / event.total) * 70) + '%';
    }
  };
  xhr.onload = async () => {
    uploading = false;
    $('#upGo').disabled = false;
    if (xhr.status >= 200 && xhr.status < 300) {
      bar.style.width = '100%';
      let doc = null;
      try { doc = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
      closeUpload();
      const suffixText = doc
        ? (doc.doc_type === 'detail'
          ? '明细表直接入库'
          : `自动切成 ${doc.chunk_count} 个知识块，等待审核`)
        : '上传完成';
      toast(`已入库到「${areaName(areaId)}」：${suffixText}`);
      if (areaFilter !== 'all' && areaFilter !== areaId) areaFilter = areaId;
      await loadDocs();
      await loadAreas();
      if (doc) showChunks(doc.id);
    } else {
      let message = '上传失败';
      try {
        const data = JSON.parse(xhr.responseText);
        if (data.detail) message = data.detail;
      } catch (e) { /* ignore */ }
      toast(message);
      $('#upProg').classList.remove('show');
      bar.style.width = '0';
    }
  };
  xhr.onerror = () => {
    uploading = false;
    $('#upGo').disabled = false;
    $('#upProg').classList.remove('show');
    toast('网络错误，上传失败');
  };
  xhr.send(form);
}

/* ---------------- 检索热词（F7） ---------------- */
async function loadHot() {
  try {
    const params = new URLSearchParams();
    if (hotScope !== 'all') params.set('area_id', hotScope);
    const data = await api('/api/admin/stats/hot?' + params.toString());
    $('#stQ').textContent = data.total;
    $('#stW').textContent = data.distinct;
    $('#stToday').textContent = data.today;
    $('#hotSub').textContent =
      `${hotScope === 'all' ? '全部景区' : areaName(hotScope)} · 按问句聚合 · 真实日志，无日志时不虚构`;
    const el = $('#hotList');
    if (!data.rows.length) {
      el.innerHTML = '<div class="empty">该范围内暂无检索日志。<br>用游客端页面或 <code>POST /api/public/search</code> 提问几次，这里就会显示真实统计。</div>';
      return;
    }
    const max = Math.max(...data.rows.map((r) => r.count));
    el.innerHTML = data.rows.map((r) => `
      <div class="bar-row">
        <span class="bl" title="${esc(r.q)}">${esc(r.q)}</span>
        <span class="track"><span class="fill" style="width:${max ? Math.round((r.count / max) * 100) : 0}%"></span></span>
        <span class="bv">${r.count} 次</span>
      </div>`).join('');
  } catch (error) { toast(error.message); }
}
function renderHotAreaChips() {
  $('#hotAreaChips').innerHTML =
    `<span class="chip ${hotScope === 'all' ? 'on' : ''}" onclick="setHotScope('all')">全部景区</span>` +
    AREAS.map((a) => `<span class="chip ${hotScope === a.id ? 'on' : ''}" onclick="setHotScope('${a.id}')">${esc(a.name)}</span>`).join('');
}
function setHotScope(id) { hotScope = id; renderHotAreaChips(); loadHot(); }
async function clearLog() {
  const scope = hotScope === 'all' ? '全部景区' : areaName(hotScope);
  if (!confirm(`确认清空「${scope}」的检索日志？此操作不可恢复。`)) return;
  try {
    const params = new URLSearchParams();
    if (hotScope !== 'all') params.set('area_id', hotScope);
    await api('/api/admin/stats/hot?' + params.toString(), { method: 'DELETE' });
    await loadHot();
    await loadAreas();
    toast('日志已清空');
  } catch (error) { toast(error.message); }
}

/* ---------------- 路由 ---------------- */
function currentPage() {
  return (location.hash.match(/^#\/(\w+)/) || [])[1] || 'areas';
}
async function router() {
  const name = currentPage();
  const pages = { areas: 'page-areas', docs: 'page-docs', hot: 'page-hot' };
  $$('.page').forEach((p) => p.classList.remove('show'));
  const el = document.getElementById(pages[name] || pages.areas);
  if (el) el.classList.add('show');
  $('#crumbPage').textContent = { areas: '景区管理', docs: '资料管理', hot: '检索热词' }[name] || '景区管理';
  $$('[data-nav]').forEach((a) => a.classList.toggle('on', a.dataset.nav === name));

  if (name === 'docs') {
    await loadAreas();
    renderAreaChips();
    await loadDocs();
  } else if (name === 'hot') {
    await loadAreas();
    renderHotAreaChips();
    await loadHot();
  } else {
    await loadAreas();
  }
}
window.addEventListener('hashchange', router);

/* ---------------- 启动 ---------------- */
boot();
