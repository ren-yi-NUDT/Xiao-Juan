/* ============================================================
   景区智搜 · 游客端
   数据源：/api/public/*（FastAPI + SQLite），不再使用硬编码语料
   ============================================================ */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const API = '/api/public';

let AREAS = [];
let AREA = null;
let ATTRACTIONS = [];
let searchStarted = false;

const routes = {
  home: 'page-home', chat: 'page-chat', search: 'page-search',
  scenic: 'page-scenic', detail: 'page-detail', attraction: 'page-detail',
};

/* ---------------- 工具 ---------------- */
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}
function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove('show'), 2400);
}
async function api(path, options = {}) {
  const response = await fetch(API + path, options);
  if (!response.ok) {
    let message = '请求失败（' + response.status + '）';
    try {
      const data = await response.json();
      if (data.detail) {
        message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch (e) { /* 非 JSON */ }
    throw new Error(message);
  }
  return response.json();
}
function postJson(body) {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}
function go(hash) {
  if (location.hash === hash) router();
  else location.hash = hash;
}

/* ---------------- 景区 ---------------- */
async function loadAreas() {
  AREAS = await api('/areas');
  const savedId = sessionStorage.getItem('xj_visitor_area');
  if (savedId) AREA = AREAS.find((a) => a.id === savedId) || null;
  updateAreaChip();
}
function updateAreaChip() {
  const chip = $('#areaChip');
  if (!chip) return;
  if (AREA) {
    chip.textContent = '◈ ' + AREA.name;
    chip.style.display = 'inline-flex';
  } else {
    chip.style.display = 'none';
  }
}
async function renderHome() {
  const grid = $('#areaGrid');
  try {
    await loadAreas();
  } catch (error) {
    grid.innerHTML = '<div class="result"><div class="rt">暂时连不上知识库</div>'
      + '<div class="rs">请确认后台服务已启动（运行 backend 下的启动脚本），然后刷新本页。</div></div>';
    return;
  }
  if (!AREAS.length) {
    grid.innerHTML = '<div class="result"><div class="rt">还没有可游览的景区</div>'
      + '<div class="rs">请先在管理端创建景区并上传资料。</div></div>';
    return;
  }
  grid.innerHTML = AREAS.map((area, index) => `
      <div class="area-card">
        <div class="thumb th${index % 6}"><b>${esc(area.name)}</b></div>
        <div class="abody">
          <div style="font-size:12px;color:var(--primary);font-weight:600">${esc(area.tag || '景区知识库')}</div>
          <div class="ameta" style="color:var(--text2);margin-top:7px;line-height:1.6">
            ${esc(area.intro || '')}<br>${area.attractions} 个景点 · ${area.chunks} 个知识块
          </div>
          <button class="abtn" onclick="enterArea('${area.id}')">进入景区</button>
        </div>
      </div>`).join('') + `
      <div class="area-card ghost">
        <div class="plus">＋</div><b>扩展位</b>
        <p style="font-size:12.5px;margin-top:8px;padding:0 20px;line-height:1.6">
          新景区由管理端创建、资料入库后自动出现在这里
        </p>
      </div>`;
}
function enterArea(id) {
  const area = AREAS.find((a) => a.id === id);
  if (!area) return;
  AREA = area;
  sessionStorage.setItem('xj_visitor_area', area.id);
  updateAreaChip();
  renderChatHead();
  resetChat();
  resetSearch();
  const target = '#/chat';
  if (location.hash === target) router();
  else location.hash = target;
}

/* ---------------- 路由 ---------------- */
async function router() {
  const hash = location.hash || '#/home';
  const match = hash.match(/^#\/(\w+)(?:\/([\w-]+))?/);
  const name = match ? match[1] : 'home';
  if (!routes[name]) { location.hash = '#/home'; return; }
  if (name !== 'home' && !AREA) {
    toast('请先选择景区');
    location.hash = '#/home';
    return;
  }
  $$('.page').forEach((page) => page.classList.remove('show'));
  const page = document.getElementById(routes[name]);
  if (page) page.classList.add('show');
  const chip = $('#areaChip');
  if (chip) chip.style.display = name === 'home' ? 'none' : 'inline-flex';
  $$('[data-nav]').forEach((link) => {
    link.classList.toggle('on',
      link.dataset.nav === name
      || ((name === 'detail' || name === 'attraction') && link.dataset.nav === 'scenic'));
  });
  window.scrollTo(0, 0);

  try {
    if (name === 'home') await renderHome();
    if (name === 'chat') { renderChatHead(); if (!$('#chatBox').dataset.ready) resetChat(); }
    if (name === 'search' && !searchStarted) { searchStarted = true; showSearchEmpty(); }
    if (name === 'scenic') await renderCards();
    if ((name === 'detail' || name === 'attraction') && match && match[2]) {
      await renderDetail(match[2]);
    }
  } catch (error) {
    toast(error.message);
  }
}
window.addEventListener('hashchange', router);

/* ---------------- AI 问答 ---------------- */
function renderChatHead() {
  if (!AREA) return;
  $('#chatTitle').textContent = `${AREA.name} AI 导游`;
  $('#chatSub').textContent = '答案来自景区官方资料库，每条可点开核对原文';
  renderSuggestions();
}
function renderSuggestions() {
  const box = document.querySelector('.sugs');
  if (!box || !AREA) return;
  const questions = AREA.id === 'lingshan'
    ? ['带老人半天怎么逛灵山？', '九龙灌浴今天几点开演？', '梵宫《吉祥颂》今天几场？', '门票多少钱？']
    : [`${AREA.name}怎么玩？`, '开放时间是什么时候？', '有什么好玩的？', '门票多少钱？'];
  box.innerHTML = '';
  questions.forEach((question) => {
    const button = document.createElement('button');
    button.className = 'sug';
    button.textContent = question;
    button.onclick = () => ask(question);
    box.appendChild(button);
  });
}
function resetChat() {
  if (!AREA) return;
  $('#chatBox').innerHTML = `<div class="msg bot" id="chatWelcome">你好，我是 ${esc(AREA.name)} AI 导游。关于景点、演出场次、票价与游览路线，都可以问我；每个回答都来自景区资料库，并附来源。</div>`;
  $('#chatBox').dataset.ready = '1';
  $('#modelBadge').textContent = '抽取式（未接大模型）';
}
function bubble(cls, html) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  div.innerHTML = html;
  $('#chatBox').appendChild(div);
  return div;
}
function scrollChat() {
  const box = $('#chatBox');
  box.parentElement.scrollIntoView({ block: 'end' });
}
function ask(question) {
  const target = '#/chat';
  const run = () => { $('#chatInput').value = question; send(); };
  if (location.hash === target) { router(); setTimeout(run, 80); }
  else { location.hash = target; setTimeout(run, 180); }
}
async function send() {
  const input = $('#chatInput');
  const question = input.value.trim();
  if (!question) return;
  if (!AREA) { toast('请先选择景区'); go('#/home'); return; }
  input.value = '';
  bubble('me', esc(question));
  const typing = document.createElement('div');
  typing.className = 'typing';
  typing.id = 'typing';
  typing.innerHTML = '正在检索知识库<i>·</i><i>·</i><i>·</i>';
  $('#chatBox').appendChild(typing);
  scrollChat();
  try {
    // 同一标签页内按景区保持会话，实现多轮追问；后台按 session_id 取最近几轮历史
    const sessionKey = 'xj_session_' + AREA.id;
    const payload = { area_id: AREA.id, q: question };
    const savedSession = sessionStorage.getItem(sessionKey);
    if (savedSession) payload.session_id = savedSession;
    const data = await api('/ask', postJson(payload));
    if (data.session_id) sessionStorage.setItem(sessionKey, data.session_id);
    typing.remove();
    renderAnswer(data);
  } catch (error) {
    typing.remove();
    bubble('bot', '抱歉，后台服务暂时不可用（' + esc(error.message)
      + '）。请确认已运行启动脚本，然后刷新页面。');
    scrollChat();
  }
}
function renderAnswer(data) {
  const answer = esc(data.answer || '').replace(/\n/g, '<br>');
  const citations = (data.citations || []).map((cite, index) =>
    `<button class="cite" onclick="openSource(${cite.chunk_id})">[${index + 1}] ${esc(cite.title)} ↗</button>`).join('');
  const quote = citations
    ? `<div class="quote"><div class="qt">引用来源（点开核对原文）</div>${citations}</div>`
    : '<div class="quote"><div class="qt">本次未命中知识块</div></div>';
  const message = bubble('bot', answer + quote);
  const actions = document.createElement('div');
  actions.className = 'msg-acts';
  actions.innerHTML = `<button onclick="sendFeedback(${data.qa_id})">有误，纠错</button>`
    + `<button onclick="markHelpful(${data.qa_id})">有帮助</button>`;
  message.insertAdjacentElement('afterend', actions);
  $('#modelBadge').textContent = data.model === 'extractive'
    ? '抽取式（未接大模型）' : '大模型：' + data.model;
  scrollChat();
}
async function sendFeedback(qaId) {
  try {
    await api('/feedback', postJson({
      qa_id: qaId,
      content: '用户对这条回答点击了「有误，纠错」',
    }));
    toast('已提交纠错，管理员复核后会修正知识库');
  } catch (error) { toast(error.message); }
}
async function markHelpful(qaId) {
  try {
    await api('/qa/' + qaId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ satisfied: true }),
    });
    toast('感谢反馈');
  } catch (error) { toast(error.message); }
}

/* ---------------- 知识块原文 ---------------- */
async function openSource(chunkId) {
  try {
    const chunk = await api('/chunks/' + chunkId);
    $('#srcTitle').textContent = chunk.title || '知识块原文';
    $('#srcMeta').textContent = `来源：${chunk.doc_name} · 知识块 #${chunk.id}`;
    $('#srcBody').textContent = chunk.content;
    $('#sourceMask').classList.add('show');
  } catch (error) { toast(error.message); }
}
function closeSource() { $('#sourceMask').classList.remove('show'); }

/* ---------------- 语义检索 ---------------- */
function showSearchEmpty() {
  $('#searchMeta').textContent = '输入问题后点击“语义检索”，结果来自后台知识块。';
  $('#resultList').innerHTML = `
    <div class="result">
      <div class="rt">示例问题</div>
      <div class="rs">
        点击任意一条试试：<br>
        <button class="cite" onclick="doSearch('带老人半天怎么逛')">带老人半天怎么逛</button>
        <button class="cite" onclick="doSearch('九龙灌浴几点开演')">九龙灌浴几点开演</button>
        <button class="cite" onclick="doSearch('门票多少钱')">门票多少钱</button>
      </div>
    </div>`;
}
function resetSearch() {
  searchStarted = false;
  $('#resultList').innerHTML = '';
  $('#searchMeta').textContent = '';
  $('#searchInput').value = '';
}
async function doSearch(preset) {
  if (!AREA) { toast('请先选择景区'); go('#/home'); return; }
  const input = $('#searchInput');
  const question = (typeof preset === 'string' ? preset : input.value).trim();
  if (!question) return;
  input.value = question;
  $('#searchMeta').textContent = '检索中…';
  try {
    const data = await api('/search', postJson({
      area_id: AREA.id, q: question, top_k: 6,
    }));
    const terms = question.split(/[\s，,？?]+/).filter((term) => term.length > 0);
    $('#searchMeta').textContent =
      `语义匹配到 ${data.hits.length} 个知识块（${data.took_ms} 毫秒）· 检索词：“${question}”`;
    const list = $('#resultList');
    if (!data.hits.length) {
      list.innerHTML = '<div class="result"><div class="rt">没有找到相关知识块</div>'
        + '<div class="rs">换个问法试试，例如“门票多少钱”。</div></div>';
      return;
    }
    list.innerHTML = data.hits.map((hit) => {
      const relation = Math.max(0.01, Math.min(1, hit.score));
      const text = highlight((hit.content || '').slice(0, 120), terms);
      const jump = hit.attraction_id
        ? ` onclick="go('#/attraction/${hit.attraction_id}')" style="cursor:pointer"` : '';
      const sourceClass = (hit.doc_name || '').includes('指南') ? 'src-orange' : 'src-green';
      return `<div class="result"${jump}>
          <div class="rt">${esc(hit.title)}</div>
          <div class="rs">${text}…</div>
          <div class="rmeta">
            <span class="src-tag ${sourceClass}">${esc(hit.doc_name || '知识库')}</span>
            <button class="cite" onclick="event.stopPropagation();openSource(${hit.chunk_id})">查看原文 ↗</button>
            <span class="rel"><span class="bar"><i style="width:${Math.round(relation * 100)}%"></i></span>相关度 ${relation.toFixed(2)}</span>
          </div>
        </div>`;
    }).join('');
  } catch (error) {
    $('#searchMeta').textContent = '检索失败：' + error.message;
  }
}
function highlight(text, terms) {
  let html = esc(text);
  terms.filter((term) => term.length > 1).forEach((term) => {
    const safe = esc(term);
    html = html.split(safe).join('<mark>' + safe + '</mark>');
  });
  return html;
}

/* ---------------- 景点导览 ---------------- */
async function renderCards() {
  if (!AREA) return;
  await loadAreas();
  $('#filters').innerHTML = AREAS.map((area) =>
    `<button class="chip ${area.id === AREA.id ? 'on' : ''}" onclick="switchArea('${area.id}')">${esc(area.name)}</button>`).join('');
  ATTRACTIONS = await api(`/areas/${encodeURIComponent(AREA.id)}/attractions`);
  $('#cardCount').textContent = `共 ${ATTRACTIONS.length} 个景点 · 数据来自后台结构化数据集`;
  const grid = $('#cardGrid');
  if (!ATTRACTIONS.length) {
    grid.innerHTML = '<div class="result"><div class="rt">该景区暂无景点数据</div>'
      + '<div class="rs">请先在管理端上传景点资料。</div></div>';
    return;
  }
  grid.innerHTML = ATTRACTIONS.map((attraction, index) => `
      <div class="card" onclick="go('#/attraction/${attraction.id}')">
        <div class="thumb th${index % 6}">${esc(attraction.name.slice(0, 6))}</div>
        <div class="cbody">
          <div class="cname">${esc(attraction.name)}<span class="cid">${esc(attraction.id)}</span></div>
          <div class="cdesc">${esc(attraction.highlights || attraction.core_function || attraction.location || '')}</div>
          <div class="copen">◷ ${esc((attraction.performance_info || '全天开放').slice(0, 42))}</div>
        </div>
      </div>`).join('');
}
async function switchArea(id) {
  const area = AREAS.find((a) => a.id === id);
  if (!area) return;
  AREA = area;
  sessionStorage.setItem('xj_visitor_area', area.id);
  updateAreaChip();
  renderChatHead();
  resetChat();
  resetSearch();
  await renderCards();
}

/* ---------------- 景点详情 ---------------- */
async function renderDetail(id) {
  const attraction = await api('/attractions/' + encodeURIComponent(id));
  const area = AREAS.find((a) => a.id === attraction.area_id);
  $('#dCrumb').textContent = attraction.name;
  $('#dName').textContent = attraction.name.slice(0, 6);
  $('#dName2').textContent = attraction.name;
  $('#dId').textContent = attraction.id;
  $('#dSub').textContent = `${area ? area.name : ''} · 景点编号 ${attraction.id}`;
  const index = parseInt((attraction.id.match(/\d+$/) || ['0'])[0], 10) % 6;
  $('#dHero').className = 'd-hero th' + index;
  $('#dSrcName').textContent = '后台景点结构化数据集';
  $('#dSrcId').textContent = attraction.id;

  const fields = [
    ['位置', attraction.location],
    ['建筑 · 景观参数', attraction.params],
    ['核心功能', attraction.core_function],
    ['文化内涵', attraction.culture],
    ['游玩亮点', attraction.highlights],
    ['开放 · 演艺信息', attraction.performance_info],
    ['详细介绍', attraction.detail],
    ['备注', attraction.remark],
  ];
  let html = fields.filter((field) => field[1]).map((field) =>
    `<div class="field"><span class="k">${esc(field[0])}</span><span class="v">${esc(field[1])}</span></div>`).join('');
  if (attraction.performances && attraction.performances.length) {
    const shows = attraction.performances.map((perf) =>
      esc(perf.show_time) + (perf.duration_min ? `（约${perf.duration_min}分钟）` : '')).join('、');
    html += `<div class="field"><span class="k">演出 / 讲解场次</span><span class="v">${shows}</span></div>`;
  }
  $('#dFields').innerHTML = html;
  $('#dAskBtn').onclick = () => ask(`${attraction.name}有什么好玩？`);
}

/* ---------------- 接入说明 ---------------- */
function openConnect() {
  $('#apiBase').textContent = location.origin + '/api/public';
  $('#connectMask').classList.add('show');
}
function closeConnect() { $('#connectMask').classList.remove('show'); }
function copyUrl() {
  const url = location.origin + '/api/public';
  if (navigator.clipboard) {
    navigator.clipboard.writeText(url)
      .then(() => toast('接口地址已复制'), () => toast(url));
  } else {
    toast(url);
  }
}

/* ---------------- 启动 ---------------- */
async function boot() {
  try { await loadAreas(); }
  catch (error) { toast('后台服务未启动：' + error.message); }
  if (!location.hash) location.hash = '#/home';
  router();
}
boot();
