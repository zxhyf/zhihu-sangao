/* =========================================================
   智护三高 · 前端逻辑（原生 JS，无任何第三方依赖）
   ========================================================= */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  boot: null,
  sending: false,
  view: 'chat',
  dashDays: 30,
  bigFont: localStorage.getItem('zhsg_big') === '1',
};

const RISK_COLOR = {
  normal: '#18854a', watch: '#c2760a', danger: '#c62828', emergency: '#7f1d1d',
};
const RISK_BG = {
  normal: '#e8f6ee', watch: '#fdf3e2', danger: '#fdeaea', emergency: '#ffe3e3',
};

/* ---------------------------------------------------------------- 工具 */
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function md(text) {
  const src = esc(text || '').replace(/\r/g, '');
  const blocks = src.split(/\n{2,}/);
  const out = [];
  for (let b of blocks) {
    const lines = b.split('\n').filter(l => l.trim() !== '');
    if (!lines.length) continue;
    if (lines.every(l => /^\s*[-*·]\s+/.test(l))) {
      out.push('<ul>' + lines.map(l => '<li>' + inline(l.replace(/^\s*[-*·]\s+/, '')) + '</li>').join('') + '</ul>');
    } else if (lines.every(l => /^\s*\d+[.、)]\s+/.test(l))) {
      out.push('<ol>' + lines.map(l => '<li>' + inline(l.replace(/^\s*\d+[.、)]\s+/, '')) + '</li>').join('') + '</ol>');
    } else {
      // 混排：逐行判断，列表行连着输出
      let buf = [];
      let mode = null;
      const flush = () => {
        if (!buf.length) return;
        if (mode === 'ul') out.push('<ul>' + buf.map(x => '<li>' + inline(x) + '</li>').join('') + '</ul>');
        else if (mode === 'ol') out.push('<ol>' + buf.map(x => '<li>' + inline(x) + '</li>').join('') + '</ol>');
        else out.push('<p>' + buf.map(inline).join('<br/>') + '</p>');
        buf = []; mode = null;
      };
      for (const l of lines) {
        if (/^\s*[-*·]\s+/.test(l)) {
          if (mode !== 'ul') flush();
          mode = 'ul'; buf.push(l.replace(/^\s*[-*·]\s+/, ''));
        } else if (/^\s*\d+[.、)]\s+/.test(l)) {
          if (mode !== 'ol') flush();
          mode = 'ol'; buf.push(l.replace(/^\s*\d+[.、)]\s+/, ''));
        } else {
          if (mode) flush();
          mode = 'p'; buf.push(l);
        }
      }
      flush();
    }
  }
  return out.join('');
}
function inline(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/（来源：([^）]+)）/g, '<span class="cite">（来源：$1）</span>')
    .replace(/【来源：([^】]+)】/g, '<span class="cite">【来源：$1】</span>');
}
function toast(msg, ms = 2200) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), ms);
}
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const ct = res.headers.get('content-type') || '';
  if (res.status === 401 && !path.startsWith('/api/session') && !path.startsWith('/api/login')) {
    showLogin('登录状态已过期，请重新输入密码');
    throw new Error('需要登录');
  }
  if (!ct.includes('json')) throw new Error('接口返回异常');
  return res.json();
}

/* ---------------- 登录（共享演示模式） ---------------- */
function showLogin(msg = '') {
  const mask = $('#loginMask');
  if (mask) mask.hidden = false;
  const hint = $('#loginHint');
  if (hint) hint.textContent = msg;
  const inp = $('#loginPassword');
  if (inp) setTimeout(() => inp.focus(), 80);
}

async function doLogin() {
  const pw = ($('#loginPassword') || {}).value || '';
  const hint = $('#loginHint');
  try {
    const res = await fetch('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok) {
      $('#loginMask').hidden = true;
      location.reload();
      return;
    }
    if (hint) hint.textContent = data.error || '密码不正确';
  } catch (e) {
    if (hint) hint.textContent = '登录失败：' + e.message;
  }
}
function fmtTime(s) {
  if (!s) return '';
  return s.length >= 16 ? s.slice(5, 16) : s;
}

/* ---------------------------------------------------------------- 初始化 */
async function init() {
  if (state.bigFont) document.documentElement.classList.add('big');
  if (new URLSearchParams(location.search).get('big') === '1') {
    state.bigFont = true;
    document.documentElement.classList.add('big');
    localStorage.setItem('zhsg_big', '1');
  }
  bindUI();

  // 体验链接：/…?k=密码 自动登录，评委点链接即可进入（登录后从地址栏抹掉密码）
  const key = new URLSearchParams(location.search).get('k');
  if (key) {
    const r = await api('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: key }),
    }).catch(() => null);
    if (r && r.ok) {
      const clean = location.pathname + location.hash;
      history.replaceState(null, '', clean);
    }
  }

  const sess = await api('/api/session').catch(() => null);
  if (!sess || !sess.authenticated) {
    showLogin(sess && sess.needs_password ? '' : '无法建立会话');
    return;
  }

  await refresh();
  const hist = await api('/api/history').catch(() => null);
  const thread = $('#messages');
  thread.innerHTML = '';
  if (hist && hist.messages && hist.messages.length) {
    const wrap = document.createElement('div');
    wrap.className = 'thread';
    thread.appendChild(wrap);
    hist.messages.slice(-20).forEach(m => {
      if (m.role === 'user') wrap.appendChild(userMsg(m.content));
      else wrap.appendChild(botMsg({ reply: m.content, blocks: m.blocks || [], sources: [], trace: [], mode: 'history' }, false));
    });
    scrollBottom();
  } else {
    renderWelcome();
  }
  // 演示直达：访问 /#q=今天血压150/95 会自动发送这句话（方便录演示视频）
  const hash = decodeURIComponent(location.hash || '');
  if (hash.startsWith('#q=')) {
    const q = hash.slice(3);
    if (q) setTimeout(() => sendMessage(q), 400);
  } else if (hash.startsWith('#view=')) {
    const v = hash.slice(6);
    const tab = document.querySelector('.tab[data-view="' + v + '"]');
    if (tab) setTimeout(() => tab.click(), 300);
  } else if (hash === '#lab') {
    setTimeout(async () => {
      openLabModal();
      const r = await api('/api/lab/sample').catch(() => null);
      if (r && r.text) {
        $('#labText').value = r.text;
        await parseLabText();
      }
    }, 350);
  }
}

async function refresh() {
  const data = await api('/api/bootstrap');
  state.boot = data;
  renderProfile(data);
  renderVitals(data);
  renderTasks(data);
  renderKb(data);
  renderMode(data);
  renderTools(data);
  renderSources(data);
  renderDemoStrip(data);
  fillProfileForm(data.profile);
}

function renderDemoStrip(d) {
  const strip = $('#demoStrip');
  if (!strip) return;
  const demo = d.demo || {};
  if (demo.has_demo) {
    $('#demoCount').textContent = demo.demo_count || 0;
    strip.hidden = false;
  } else {
    strip.hidden = true;
  }
}

/* ---------------------------------------------------------------- 侧栏 */
function renderProfile(d) {
  const p = d.profile || {};
  $('#profileAvatar').textContent = (p.name || '用')[0];
  $('#profileName').textContent = p.name || '未命名';
  const bits = [];
  if (p.age) bits.push(p.age + ' 岁');
  if (p.sex) bits.push(p.sex);
  if (p.height_cm) bits.push(p.height_cm + ' cm');
  $('#profileSub').textContent = bits.join(' · ') || '资料待完善';
  const chips = $('#profileChips');
  chips.innerHTML = '';
  (p.conditions || []).forEach(c => {
    const el = document.createElement('span');
    el.className = 'chip';
    el.textContent = c;
    chips.appendChild(el);
  });
  if (!p.can_cook) { const el = document.createElement('span'); el.className = 'chip alt'; el.textContent = '不做饭'; chips.appendChild(el); }
  if (p.taste === 'salty') { const el = document.createElement('span'); el.className = 'chip alt'; el.textContent = '口味偏咸'; chips.appendChild(el); }
  $('#bmiValue').textContent = p.bmi || '—';
  $('#weightValue').textContent = p.weight ? p.weight + ' kg' : '—';
}

function renderVitals(d) {
  const box = $('#vitals');
  box.innerHTML = '';
  const items = (d.snapshot && d.snapshot.items) || [];
  const wanted = ['血压', '空腹血糖', 'LDL-C', '体重'];
  const shown = [];
  wanted.forEach(w => {
    const it = items.find(x => x.label === w);
    if (it) shown.push(it);
  });
  if (!shown.length) {
    box.innerHTML = '<div class="vital-empty">还没有任何记录。说一句“今天血压 150/95”，系统会自动入库并画出趋势。</div>';
    return;
  }
  shown.slice(0, 4).forEach(it => {
    const lv = (it.risk && it.risk.level) || 'normal';
    const el = document.createElement('div');
    el.className = 'vital';
    el.style.setProperty('--v-color', RISK_COLOR[lv]);
    el.innerHTML = `<div class="vital-label">${esc(it.label)}</div>
      <div class="vital-value">${esc(it.value)}</div>
      <div class="vital-tag">${esc((it.risk && it.risk.label) || '')} · ${esc(fmtTime(it.at))}</div>`;
    el.onclick = () => sendMessage('我最近' + it.label + '怎么样');
    box.appendChild(el);
  });
  const last = shown[0];
  $('#snapTime').textContent = last ? fmtTime(last.at) : '—';
}

function renderTasks(d) {
  const box = $('#taskList');
  const items = (d.tasks || []).slice(0, 14);
  const st = d.task_stats || { total: 0, done: 0, rate: 0 };
  $('#taskRate').textContent = st.rate + '%';
  $('#taskBar').style.width = st.rate + '%';
  box.innerHTML = '';
  items.forEach(t => {
    const el = document.createElement('div');
    el.className = 'task-item' + (t.done ? ' done' : '');
    el.innerHTML = `<div class="tick">✓</div>
      <div><span class="task-time">${esc(t.time_text || '')}</span>
      <span class="task-text"> ${esc((t.content || '').slice(0, 42))}</span></div>`;
    el.querySelector('.tick').onclick = async () => {
      el.classList.toggle('done');            // 先给即时反馈
      const r = await api('/api/tasks/toggle', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: t.id }),
      });
      const b = await api('/api/bootstrap');
      state.boot = b;
      renderTasks(b);
      if (r && r.ok) toast(r.done ? '已勾选' : '已取消勾选');
    };
    box.appendChild(el);
  });
  if (!items.length) box.innerHTML = '<div class="vital-empty">今天还没有任务卡，发送“今天做什么”生成。</div>';
}

function renderKb(d) {
  const kb = d.kb || {};
  const cnt = $('#kbCount');
  if (cnt) cnt.textContent = (kb.doc_count || 0) + ' 篇指南';
  const ds = d.drug_stats || {};
  const stat = $('#drugStat');
  if (stat) stat.textContent = `${ds.drug_count || 0} 种常用药 · ${ds.rule_count || 0} 条联动规则`;
  const list = $('#kbDocList');
  if (!list) return;
  list.innerHTML = '';
  const docCount = $('#kbDocCount');
  if (docCount) docCount.textContent = `${kb.doc_count || 0} 篇`;
  (kb.docs || []).forEach(doc => {
    const el = document.createElement('div');
    el.className = 'kb-doc';
    el.innerHTML = `<div class="kb-doc-top">
        <div><b>${esc(doc.title)}</b>
          <div class="src-meta">${esc(doc.source || '')} · ${esc(doc.org || '')} · ${esc(doc.year || '')}</div>
        </div>
        <span class="badge-lv">${esc(doc.level || 'B')}级</span>
      </div>`;
    list.appendChild(el);
  });
}

function renderMode(d) {
  const j = d.judge || {};
  const badge = $('#modeBadge');
  if (!badge) return;
  const local = j.engine !== 'llm';
  badge.innerHTML = `<i></i><span>${esc(j.engine_label || (local ? '本地规则引擎' : '在线大模型'))}</span>`;
  badge.classList.toggle('local', local);
}

function renderTools(d) {
  // 面向用户后不再展示工具白名单；「安全说明」页为静态内容，这里不做渲染
  return;
}

function renderSources(d) {
  const data = d.sources || {};
  $('#sourcesDesc').textContent = (data.meta && data.meta.citation_rule) || '';
  const box = $('#sourcesList');
  box.innerHTML = '';
  (data.sources || []).forEach(s => {
    const el = document.createElement('div');
    el.className = 'source-card';
    el.innerHTML = `<div class="sc-top">
        <div><b>${esc(s.name)}</b>
          <div class="sc-meta">${esc(s.org)} · ${esc(String(s.year))} · ${esc(s.authority || '')}</div>
        </div>
        <span class="badge-lv">${esc((s.category || '').slice(0, 6))}</span>
      </div>
      <div class="sc-use">用途：${esc(s.used_for || '')}</div>
      <div class="sc-meta">时效性：${esc(s.timeliness || '')}${s.in_kb ? ' · 已入库' : ''} · 获取日期：${esc(s.collected || '')}</div>`;
    box.appendChild(el);
  });
}

/* ---------------------------------------------------------------- 欢迎页 */
function renderWelcome() {
  const thread = $('#messages');
  thread.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'welcome';
  const p = (state.boot && state.boot.profile) || {};
  const j = (state.boot && state.boot.judge) || {};
  const kbCount = (state.boot && state.boot.kb && state.boot.kb.doc_count) || 0;

  const steps = (j.steps || []).map(s => `
    <div class="step">
      <b>${esc(s.t)}</b>
      <div><div class="step-t">${esc(s.title)}</div><div class="step-d">${esc(s.desc)}</div></div>
    </div>`).join('');

  const questions = (j.questions || []).map(q => `
    <button class="q-chip" data-q="${esc(q.q)}">
      <span class="q-label">${esc(q.label)}</span>
      <span class="q-text">${esc(q.q)}</span>
    </button>`).join('');

  wrap.innerHTML = `
    <div class="welcome-card judge">
      <div class="w-kicker">开始体验 · 约 3 分钟</div>
      <h2>${esc(p.name || '你好')}，先看三件事</h2>
      <div class="steps">${steps}</div>
      <div class="w-sub">也可以直接点一个问题试试</div>
      <div class="q-grid">${questions}</div>
      <div class="w-foot">
        <span class="w-tag">${esc(j.engine_label || '本地规则引擎')}</span>
        <span class="w-note">${esc(j.notice || '演示数据为合成的模拟数据，不是真实病历')}</span>
      </div>
      <div class="w-note2">指南库已收录 ${kbCount} 篇权威要点，回答会标注出处；所有建议不构成诊疗意见，请遵医嘱。</div>
    </div>`;
  thread.appendChild(wrap);
  $$('.q-chip', wrap).forEach(b => {
    b.onclick = () => sendMessage(b.dataset.q);
  });
}

/* ---------------------------------------------------------------- 消息渲染 */
function scrollBottom() {
  const box = $('#messages');
  const jump = () => { box.style.scrollBehavior = 'auto'; box.scrollTop = box.scrollHeight; };
  jump();
  requestAnimationFrame(jump);
  setTimeout(() => { jump(); box.style.scrollBehavior = ''; }, 120);
}

function userMsg(text) {
  const el = document.createElement('div');
  el.className = 'msg user';
  el.innerHTML = `<div class="avatar">我</div><div class="msg-body"><div class="bubble">${md(text)}</div></div>`;
  return el;
}

function traceHtml(trace) {
  if (!trace || !trace.length) return '';
  const pills = trace.map((t, i) => {
    const cls = t.status === 'blocked' ? 'blocked' : (t.status === 'warn' ? 'warn' : '');
    return `<span class="trace-pill ${cls}" title="${esc(t.detail)}" style="animation-delay:${i * 70}ms">
      <i></i><b>${esc(t.label)}</b></span>`;
  }).join('');
  return `<div class="trace">${pills}</div>`;
}

function botMsg(payload, animate = true) {
  const el = document.createElement('div');
  el.className = 'msg bot';
  const modeLabel = payload.mode === 'llm' ? 'DeepSeek 生成'
    : payload.mode === 'safety' ? '安全网关拦截'
    : payload.mode === 'history' ? '历史记录' : '本地规则生成';
  const metaBits = [modeLabel];
  if (payload.intent) metaBits.push('意图：' + payload.intent);
  if (payload.elapsed_ms) metaBits.push(payload.elapsed_ms + ' ms');
  if (payload.ts) metaBits.push(payload.ts.slice(11, 16));

  const blocksEl = document.createElement('div');
  blocksEl.className = 'blocks';
  const ctx = { hasSafety: (payload.blocks || []).some(x => x && x.type === 'safety_note') };
  (payload.blocks || []).forEach(b => {
    const node = renderBlock(b, ctx);
    if (node) blocksEl.appendChild(node);
  });

  const sourcesHtml = (payload.sources && payload.sources.length) ? `
    <details class="sources"><summary>依据 · ${payload.sources.length} 条可溯源指南片段</summary>
      ${payload.sources.map(s => `<div class="source-item">
        <b>${esc(s.title)}</b> <span class="src-meta">${esc(s.source || '')}　${esc(s.org || '')}　${esc(String(s.year || ''))}</span>
        <div class="src-snippet">…${esc((s.snippet || '').slice(0, 110))}…</div>
      </div>`).join('')}
    </details>` : '';

  const followHtml = (payload.followups && payload.followups.length) ? `
    <div class="followups">${payload.followups.map(f => `<button class="followup">${esc(f)}</button>`).join('')}</div>` : '';

  el.innerHTML = `
    <div class="avatar">智</div>
    <div class="msg-body">
      <div class="trace-host"></div>
      <div class="bubble">${md(payload.reply || '')}</div>
      <div class="blocks-host"></div>
      ${sourcesHtml}
      ${followHtml}
      <div class="msg-meta">${metaBits.map(m => `<span>${esc(m)}</span>`).join('<span class="sep">·</span>')}
        <span class="sep">·</span><span>${esc(payload.disclaimer || '本建议不构成诊疗意见，请遵医嘱。')}</span></div>
    </div>`;

  el.querySelector('.trace-host').innerHTML = traceHtml(payload.trace);
  el.querySelector('.blocks-host').appendChild(blocksEl);
  $$('.followup', el).forEach(b => {
    b.onclick = () => {
      if (b.textContent.trim() === '打开检验单录入') { openLabModal(); return; }
      sendMessage(b.textContent);
    };
  });
  return el;
}

/* ---------------- 检验单录入弹窗 ---------------- */
function openLabModal() {
  $('#labMask').classList.add('show');
  setTimeout(() => $('#labText').focus(), 220);
}
function closeLabModal() { $('#labMask').classList.remove('show'); }

async function parseLabText() {
  const text = $('#labText').value;
  const hint = $('#labHint');
  const box = $('#labResult');
  const btn = $('#labCommitBtn');
  if (!text.trim()) { hint.textContent = '先把检验单内容粘贴进来'; return; }
  hint.textContent = '解析中…';
  box.innerHTML = '';
  btn.disabled = true;
  try {
    const r = await api('/api/lab/parse', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) {
      hint.textContent = r.error || '没有识别到可入库的指标';
      return;
    }
    hint.textContent = r.summary;
    r.items.forEach(it => box.appendChild(labRow(it)));
    btn.disabled = false;
    btn.textContent = `确认入库（${r.items.length} 项）`;
    btn.classList.remove('done');
    btn.dataset.measuredAt = r.measured_at || '';
  } catch (e) {
    hint.textContent = '解析失败：' + e.message;
  }
}

/* ---------------------------------------------------------------- 卡片渲染 */
function renderBlock(b, ctx) {
  ctx = ctx || {};
  switch (b.type) {
    case 'metric': return metricCard(b);
    case 'chart': return chartCard(b);
    case 'stats': return statsCard(b);
    case 'plan': return planCard(b);
    case 'report': return reportCard(b);
    case 'interactions': return interactionCard(b, ctx);
    case 'meds': return medsCard(b, ctx);
    case 'tasks': return tasksCard(b);
    case 'alert': return alertCard(b);
    case 'lab': return labCard(b);
    case 'cta': return ctaCard(b);
    case 'safety_note': return safetyNoteCard(b);
    case 'med_change': return medChangeCard(b);
    default: return null;
  }
}

function metricCard(b) {
  const lv = (b.risk && b.risk.level) || 'normal';
  const el = document.createElement('div');
  el.className = 'card metric';
  el.style.setProperty('--m-color', RISK_COLOR[lv]);
  const [v, ...rest] = String(b.value || '').split(' ');
  el.innerHTML = `
    <div class="card-title">${esc(b.label)} <span class="card-sub">${esc(fmtTime(b.time))}</span></div>
    <div class="metric-top">
      <span class="metric-value" style="color:${RISK_COLOR[lv]}">${esc(v)}</span>
      <span class="metric-unit">${esc(rest.join(' '))}</span>
      <span class="risk-badge" style="background:${RISK_BG[lv]};color:${RISK_COLOR[lv]}">${esc(b.risk.label)}</span>
    </div>
    <div class="metric-detail">${esc(b.risk.detail || '')}</div>
    <div class="metric-ref">参考依据：${esc(b.risk.ref || '')}</div>`;
  return el;
}

function chartCard(b) {
  const el = document.createElement('div');
  el.className = 'card chart';
  const isBp = b.kind === 'bp';
  el.innerHTML = `
    <div class="chart-head">
      <div class="card-title">${esc(b.title)} <span class="card-sub">近 ${esc(String(b.stats.days || ''))} 天</span></div>
      <div class="legend">
        <span><i style="background:#0f8f7e"></i>${isBp ? '收缩压' : (b.unit || '')}</span>
        ${isBp ? '<span><i style="background:#8fb8f0"></i>舒张压</span>' : ''}
      </div>
    </div>
    <div class="chart-host"></div>
    <div class="chart-stats">
      <span>均值 <b>${esc(b.stats.mean_text || '')}</b></span>
      <span>区间 <b>${esc(String(b.stats.min))}–${esc(String(b.stats.max))}</b> ${esc(b.unit || '')}</span>
      <span>方向 <b>${esc(b.stats.direction || '')}</b></span>
      <span>超参考 <b style="color:${b.counts.danger || b.counts.emergency ? '#c62828' : '#c2760a'}">${esc(String(b.stats.count != null ? (b.counts.watch + b.counts.danger + b.counts.emergency) : 0))}</b> / ${esc(String(b.stats.count))} 条</span>
    </div>`;
  el.querySelector('.chart-host').innerHTML = lineChart(b.series, { kind: b.kind, sub: b.sub, unit: b.unit });
  return el;
}

function statsCard(b) {
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = `<div class="card-title">${esc(b.title)} · 统计</div>
    <div class="stats-grid" style="margin-top:9px">
      ${(b.items || []).map(i => `<div class="stat-cell"><div class="k">${esc(i.k)}</div><div class="v">${esc(i.v)}</div></div>`).join('')}
    </div>`;
  return el;
}

function planCard(b) {
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = `<div class="card-title">${esc(b.title)} <span class="card-sub">点日期切换 · 每项都带时间和克数</span></div>
    <div class="plan-days"></div><div class="plan-body"></div>
    <div class="med-inline-note">方案里的服药时间只是提醒，<b>吃什么药、吃多少，一律以医生处方为准</b>；本方案不调整任何药物，请遵医嘱。</div>
    <details class="plan-extra"><summary>本周备菜清单 / 执行要点</summary>
      <div class="shop-grid">${(b.shopping || []).map(s => `<div><span>${esc(s.item)}</span> · ${esc(s.qty)}</div>`).join('')}</div>
      <ul style="font-size:12px;color:#3d4c5e;margin-top:8px;padding-left:18px">${(b.tips || []).map(t => `<li>${esc(t)}</li>`).join('')}</ul>
      <div class="src-snippet" style="margin-top:6px">依据：${(b.basis || []).map(esc).join('；')}</div>
    </details>`;
  const days = b.days || [];
  const tabs = el.querySelector('.plan-days');
  const body = el.querySelector('.plan-body');
  const draw = (i) => {
    $$('.plan-day-btn', tabs).forEach((x, j) => x.classList.toggle('active', i === j));
    const d = days[i];
    if (!d) { body.innerHTML = ''; return; }
    body.innerHTML = `<div class="timeline">${d.items.map(it => `
      <div class="tl-item">
        <div class="tl-time">${esc(it.time)}</div>
        <div class="tl-body">
          <div class="tl-title">${esc(it.title)}<span class="tl-cat cat-${esc(it.category)}">${catLabel(it.category)}</span></div>
          <div class="tl-content">${esc(it.content)}</div>
          ${it.note ? `<div class="tl-note">${esc(it.note)}</div>` : ''}
        </div>
      </div>`).join('')}</div>`;
  };
  days.forEach((d, i) => {
    const btn = document.createElement('button');
    btn.className = 'plan-day-btn';
    btn.textContent = (d.weekday || '') + ' ' + (d.date || '').slice(5);
    btn.onclick = () => draw(i);
    tabs.appendChild(btn);
  });
  draw(0);
  return el;
}

function catLabel(c) {
  return { meal: '饮食', exercise: '运动', measure: '测量', med: '用药', sleep: '作息' }[c] || c;
}

function reportCard(b) {
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = `<div class="card-title">${esc(b.title)} <span class="card-sub">${esc(b.range || '')}</span></div>
    ${(b.sections || []).map(s => `
      <div class="report-sec"><h4>${esc(s.title)}</h4>
        <ul>${(s.lines || []).map(l => `<li>${esc(l)}</li>`).join('')}</ul>
        ${s.chart ? `<div class="chart-host" data-chart='1'></div>` : ''}
      </div>`).join('')}
    <div class="src-snippet" style="margin-top:8px">导出的报告文件保存在项目 reports/ 目录，可在“对话”里发送“帮我生成周报”再次生成。</div>`;
  const hosts = $$('.chart-host', el);
  (b.sections || []).forEach((s, i) => {
    if (s.chart && hosts[i]) hosts[i].innerHTML = lineChart(s.chart.series, { kind: s.chart.kind, unit: s.chart.unit });
  });
  return el;
}

function interactionCard(b, ctx) {
  const el = document.createElement('div');
  el.className = 'card';
  const lvText = { high: '高风险', caution: '需关注', info: '提示' };
  const foot = (ctx && ctx.hasSafety) ? '' :
    '<div class="med-inline-note">以上为规则提示，<b>不构成用药建议</b>；能否同服与是否调整，请由医生或药师判断。</div>';
  el.innerHTML = `
    <div class="card-title">${esc(b.title)} <span class="card-sub">${esc(b.summary || '')}</span></div>
    <div class="drug-chips">${(b.drugs || []).map(d => `<span class="drug-chip">${esc(d.name)}<small>${esc((d.class || '').slice(0, 10))}</small></span>`).join('')}</div>
    ${(b.interactions || []).length ? (b.interactions || []).map(r => `
      <div class="rule ${esc(r.level)}">
        <div class="rule-title"><span class="lv-${esc(r.level)}">${lvText[r.level] || ''}</span>${esc(r.title)}</div>
        <div class="rule-detail">${esc(r.detail)}</div>
        <div class="rule-action">→ ${esc(r.action || '')}</div>
        <div class="rule-src">依据：${esc(r.source || '')}</div>
      </div>`).join('') : '<div class="metric-detail">在已收录规则中没有命中明确冲突。这不等于“可以随便一起吃”，新增药物仍需医生或药师审核。</div>'}
    ${foot}`;
  return el;
}

function medsCard(b, ctx) {
  const el = document.createElement('div');
  el.className = 'card';
  const foot = (ctx && ctx.hasSafety) ? '' :
    '<div class="med-inline-note">⚠️ 以上是你自己登记的用药信息，系统<b>不判断剂量、不建议调整</b>；实际服药<b>以医生处方为准，请遵医嘱</b>。</div>';
  el.innerHTML = `<div class="card-title">${esc(b.title)}</div>
    ${(b.items || []).map(m => `
      <div class="med-row">
        <div><div class="med-name">${esc(m.name)} <span class="med-meta">${esc(m.dose || '')}</span></div>
          <div class="med-meta">${esc(m.frequency || '')} ${esc((m.times || []).join(' / '))} ${m.purpose ? '· ' + esc(m.purpose) : ''}</div></div>
        <button class="checkin" data-name="${esc(m.name)}">打卡</button>
      </div>`).join('') || '<div class="metric-detail">还没有登记用药。说一句“我在吃氨氯地平 5 mg”，我帮你记下来。</div>'}
    ${foot}`;
  $$('.checkin', el).forEach(btn => {
    btn.onclick = async () => {
      const r = await api('/api/meds/log', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: btn.dataset.name }),
      });
      if (!r || !r.ok) { toast(r && r.error ? r.error : '打卡失败', 3600); return; }
      btn.classList.add('done');
      btn.textContent = `${r.slot} 已打卡 ✓`;
      const b = await api('/api/bootstrap');
      state.boot = b;
      renderTasks(b);
      toast(`已记录 ${r.slot} 服药打卡，请继续遵医嘱服药`);
    };
  });
  return el;
}

function safetyNoteCard(b) {
  const el = document.createElement('div');
  el.className = 'safety-note';
  el.innerHTML = `
    <div class="sn-head"><span class="sn-icon">⚠️</span>${esc(b.title || '用药安全提醒')}</div>
    <ul>${(b.lines || []).map(l => `<li>${mdInline(l)}</li>`).join('')}</ul>
    <div class="sn-foot">${esc(b.foot || '以上内容不构成用药建议，请严格遵医嘱服药。')}</div>`;
  return el;
}

function mdInline(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function tasksCard(b) {
  const el = document.createElement('div');
  el.className = 'card';
  const st = b.stats || { done: 0, total: 0, rate: 0 };
  el.innerHTML = `<div class="card-title">${esc(b.title)} <span class="card-sub">已完成 ${st.done}/${st.total}（${st.rate}%）</span></div>
    <div class="timeline" style="margin-top:6px">
      ${(b.items || []).slice(0, 16).map(t => `
        <div class="tl-item" style="grid-template-columns:52px 1fr 26px">
          <div class="tl-time">${esc(t.time_text || '')}</div>
          <div class="tl-body"><div class="tl-content">${esc(t.content || '')}</div></div>
          <div class="tick" data-id="${t.id}" style="width:18px;height:18px;border-radius:5px;border:1.5px solid ${t.done ? '#0f8f7e' : '#d5deea'};background:${t.done ? '#0f8f7e' : '#fff'};color:${t.done ? '#fff' : 'transparent'};display:grid;place-items:center;font-size:11px;cursor:pointer">✓</div>
        </div>`).join('')}
    </div>`;
  $$('.tick', el).forEach(t => {
    t.onclick = async () => {
      const r = await api('/api/tasks/toggle', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: Number(t.dataset.id) }),
      });
      if (!r || !r.ok) { toast('更新失败'); return; }
      // 就地更新勾选图案（之前只刷新了侧栏，这张卡片本身没变）
      t.style.background = r.done ? '#0f8f7e' : '#fff';
      t.style.borderColor = r.done ? '#0f8f7e' : '#d5deea';
      t.style.color = r.done ? '#fff' : 'transparent';
      const b2 = await api('/api/bootstrap');
      state.boot = b2;
      renderTasks(b2);
      toast(r.done ? '已勾选' : '已取消勾选');
    };
  });
  return el;
}

function alertCard(b) {
  const el = document.createElement('div');
  el.className = 'card alert ' + (b.level || 'info');
  el.innerHTML = `<div class="alert-title">${b.level === 'emergency' ? '🚨 ' : (b.level === 'prescription' ? '⛔ ' : '⚠️ ')}${esc(b.title)}</div>
    <div class="alert-body">${esc(b.body || '')}</div>
    ${(b.actions || []).length ? `<ul class="alert-actions">${b.actions.map(a => `<li>${esc(a)}</li>`).join('')}</ul>` : ''}`;
  return el;
}

/* ---------------- 检验单 ---------------- */
function labRow(it) {
  const lv = (it.risk && it.risk.level) || 'normal';
  const row = document.createElement('div');
  row.className = 'lab-row';
  row.dataset.kind = it.kind || '';
  row.dataset.sub = it.sub || '';
  row.dataset.value = it.value;
  row.dataset.unit = it.unit || '';
  row.dataset.label = it.label || '';
  row.innerHTML = `
    <input type="checkbox" checked />
    <div><div class="lab-name">${esc(it.label)}</div>
      <div class="lab-line">${esc(it.line || '')}</div></div>
    <div class="lab-val">${esc(String(it.value))}<span class="metric-unit"> ${esc(it.unit || '')}</span></div>
    <div class="lab-line">参考 ${esc(it.ref || '—')}</div>
    <div class="lab-risk" style="background:${RISK_BG[lv]};color:${RISK_COLOR[lv]}">${esc((it.risk && it.risk.label) || '')}</div>`;
  const cb = row.querySelector('input');
  cb.onchange = () => row.classList.toggle('off', !cb.checked);
  return row;
}

function collectLabItems(container) {
  const items = [];
  $$('.lab-row', container).forEach(row => {
    const cb = row.querySelector('input[type="checkbox"]');
    const val = Number(row.dataset.value);
    if (!cb.checked || !isFinite(val)) return;
    items.push({
      kind: row.dataset.kind, sub: row.dataset.sub || null, value: val,
      unit: row.dataset.unit, label: row.dataset.label, checked: true,
      line: (row.querySelector('.lab-line') || {}).textContent || '',
    });
  });
  return items;
}

async function commitLabItems(container, measuredAt, button) {
  const items = collectLabItems(container);
  if (!items.length) { toast('至少勾选一项'); return; }
  if (button) { button.disabled = true; button.textContent = '正在入库…'; }
  try {
    const r = await api('/api/lab/commit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items, measured_at: measuredAt || '' }),
    });
    toast(r.message || '已入库');
    if (button) { button.textContent = `已入库 ${r.count} 项 ✓`; button.classList.add('done'); }
    const b = await api('/api/bootstrap');
    state.boot = b;
    renderVitals(b); renderTasks(b); renderProfile(b);
  } catch (e) {
    toast('入库失败：' + e.message);
    if (button) { button.disabled = false; button.textContent = '确认入库'; }
  }
}

function labCard(b) {
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = `<div class="card-title">${esc(b.title)} <span class="card-sub">${esc(b.date_text || '')} · 核对后才会入库</span></div>
    <div class="lab-result"></div>`;
  const box = el.querySelector('.lab-result');
  (b.items || []).forEach(it => box.appendChild(labRow(it)));
  const btn = document.createElement('button');
  btn.className = 'cta-btn';
  btn.textContent = `确认入库（${(b.items || []).length} 项）`;
  btn.onclick = () => commitLabItems(box, b.measured_at, btn);
  el.appendChild(btn);
  return el;
}

function ctaCard(b) {
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = `<div class="card-title">${esc(b.title)}</div>
    <div class="cta-body">${esc(b.body || '')}</div>`;
  const btn = document.createElement('button');
  btn.className = 'cta-btn';
  btn.textContent = b.button || '打开';
  btn.onclick = () => openLabModal();
  el.appendChild(btn);
  return el;
}

/* ---------------------------------------------------------------- SVG 折线图 */
function lineChart(series, opt = {}) {
  const data = (series || []).filter(d => d && d.v != null);
  if (!data.length) return '<div class="vital-empty">没有可绘制的数据</div>';
  const W = 720, H = 240, PL = 46, PR = 14, PT = 16, PB = 30;
  const vals = [];
  data.forEach(d => { vals.push(Number(d.v)); if (opt.kind === 'bp' && d.v2 != null) vals.push(Number(d.v2)); });
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const span = Math.max(1e-6, hi - lo);
  lo -= span * 0.18; hi += span * 0.18;
  if (lo < 0 && Math.min(...vals) >= 0) lo = 0;
  const x = i => PL + (data.length === 1 ? (W - PL - PR) / 2 : (i / (data.length - 1)) * (W - PL - PR));
  const y = v => PT + (1 - (v - lo) / (hi - lo)) * (H - PT - PB);

  const ticks = 4;
  const nice = (hi - lo) > 20 ? 0 : 1;
  let grid = '';
  for (let i = 0; i <= ticks; i++) {
    const v = lo + (hi - lo) * (i / ticks);
    const yy = y(v);
    grid += `<line x1="${PL}" y1="${yy.toFixed(1)}" x2="${W - PR}" y2="${yy.toFixed(1)}" stroke="#eef2f7" stroke-width="1"/>
      <text x="${PL - 8}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end" font-size="10" fill="#8b98a8">${v.toFixed(nice)}</text>`;
  }

  const path = (key) => {
    let d = '';
    data.forEach((p, i) => { d += (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(Number(p[key])).toFixed(1) + ' '; });
    return d;
  };
  const area = path('v') + `L${x(data.length - 1).toFixed(1)} ${(H - PB)} L${x(0).toFixed(1)} ${(H - PB)} Z`;

  const dots = data.map((p, i) => {
    const c = RISK_COLOR[p.risk] || '#0f8f7e';
    return `<circle cx="${x(i).toFixed(1)}" cy="${y(Number(p.v)).toFixed(1)}" r="3.2" fill="${c}" stroke="#fff" stroke-width="1.2">
      <title>${esc(p.t || '')}  ${esc(p.text || p.v)}</title></circle>`;
  }).join('');

  const diaDots = (opt.kind === 'bp')
    ? data.map((p, i) => p.v2 == null ? '' :
      `<circle cx="${x(i).toFixed(1)}" cy="${y(Number(p.v2)).toFixed(1)}" r="2.4" fill="#8fb8f0"><title>${esc(p.t || '')} 舒张压 ${p.v2}</title></circle>`).join('')
    : '';

  const step = Math.max(1, Math.ceil(data.length / 5));
  let xlab = '';
  data.forEach((p, i) => {
    if (i % step !== 0 && i !== data.length - 1) return;
    xlab += `<text x="${x(i).toFixed(1)}" y="${H - 10}" text-anchor="middle" font-size="10" fill="#8b98a8">${esc((p.label || '').slice(0, 5))}</text>`;
  });

  const band = opt.kind === 'bp' ? null : refBand(opt.kind, opt.sub);
  let bandSvg = '';
  if (band) {
    const y1 = y(band[1]), y2 = y(band[0]);
    if (y1 > PT - 4 && y2 < H - PB + 4) {
      bandSvg = `<rect x="${PL}" y="${Math.max(PT, y1).toFixed(1)}" width="${W - PL - PR}"
        height="${Math.max(1, Math.min(H - PB, y2) - Math.max(PT, y1)).toFixed(1)}"
        fill="#0f8f7e" opacity="0.07"/>`;
    }
  }

  const uid = 'g' + Math.random().toString(36).slice(2, 8);
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">
    <defs><linearGradient id="${uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#0f8f7e" stop-opacity=".22"/>
      <stop offset="100%" stop-color="#0f8f7e" stop-opacity="0"/>
    </linearGradient></defs>
    ${grid}${bandSvg}
    <path d="${area}" fill="url(#${uid})"/>
    <path d="${path('v')}" fill="none" stroke="#0f8f7e" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    ${opt.kind === 'bp' ? `<path d="${path('v2')}" fill="none" stroke="#8fb8f0" stroke-width="1.6" stroke-dasharray="4 3"/>` : ''}
    ${diaDots}${dots}${xlab}
  </svg>`;
}
function fmtNum(v) { return (Math.round(v * 10) / 10).toString(); }
function refBand(kind, sub) {
  if (kind === 'bp') return [90, 139];
  if (kind === 'glucose' && sub === 'fasting') return [3.9, 6.1];
  if (kind === 'glucose') return [3.9, 7.8];
  if (kind === 'lipid' && sub === 'ldl') return [0.8, 3.4];
  if (kind === 'lipid' && sub === 'tg') return [0.4, 1.7];
  if (kind === 'hba1c') return [4.0, 6.5];
  return null;
}

/* ---------------------------------------------------------------- 对话交互 */
async function sendMessage(text) {
  text = (text || '').trim();
  if (!text || state.sending) return;
  state.sending = true;
  $('#sendBtn').disabled = true;
  $('#input').value = '';
  autoGrow($('#input'));

  const thread = $('#messages');
  const wrap = thread.querySelector('.thread') || (() => {
    thread.innerHTML = '';
    const w = document.createElement('div');
    w.className = 'thread';
    thread.appendChild(w);
    return w;
  })();

  wrap.appendChild(userMsg(text));
  const pending = document.createElement('div');
  pending.className = 'msg bot';
  pending.innerHTML = `<div class="avatar">智</div><div class="msg-body">
      <div class="bubble"><div class="thinking"><i></i><i></i><i></i><span class="thinking-text">安全审查 · 意图识别 · 检索知识库…</span></div></div>
    </div>`;
  wrap.appendChild(pending);
  scrollBottom();

  try {
    const res = await api('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    if (!res.ok) throw new Error(res.error || '处理失败');
    pending.remove();
    wrap.appendChild(botMsg(res));
    scrollBottom();
    if (res.intent === 'record' || res.intent === 'plan' || res.intent === 'task') {
      const b = await api('/api/bootstrap');
      state.boot = b;
      renderVitals(b); renderTasks(b); renderProfile(b);
    }
  } catch (e) {
    pending.remove();
    const err = document.createElement('div');
    err.className = 'msg bot';
    err.innerHTML = `<div class="avatar">智</div><div class="msg-body"><div class="bubble">
      出了点问题：${esc(e.message)}。<br/>请确认服务仍在运行（终端窗口不要关闭），或稍后重试。</div></div>`;
    wrap.appendChild(err);
  } finally {
    state.sending = false;
    $('#sendBtn').disabled = false;
    $('#input').focus();
  }
}

function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(140, el.scrollHeight) + 'px';
}

function medChangeCard(b) {
  const el = document.createElement('div');
  el.className = 'card med-change';
  const isStop = b.action === 'stop';
  const tagText = { add: '新增', update: '变更', append: '追加', remove: '移除', same: '无变化' };
  const btnText = isStop ? '确认移除'
    : (b.mode === 'add' ? '确认添加'
      : b.mode === 'append' ? '确认追加'
        : (b.mode === 'update' ? '确认变更' : '确认保存'));
  const rows = (b.items || []).map(i => {
    const tag = tagText[i.change] || '';
    const prev = (i.prev_times || []).join(' / ');
    const now = (i.final_times || i.times || []).join(' / ') || '08:00';
    const added = (i.added_times || []).join(' / ');
    let timeText = now;
    if (isStop) timeText = '从打卡清单移除';
    else if (i.change === 'append') timeText = `+${added}（现有 ${prev} → ${now}）`;
    else if (i.change === 'update' && prev && prev !== now) timeText = `${prev} → <b>${now}</b>`;
    return `<div class="ml-row">
      <b>${esc(i.name)}</b>
      ${tag ? `<span class="ml-tag ml-${esc(i.change || 'add')}">${tag}</span>` : ''}
      ${i.dose ? `<span class="ml-dose">${esc(i.dose)}</span>` : ''}
      <span class="ml-time">${timeText}</span>
    </div>`;
  }).join('');
  el.innerHTML = `
    <div class="card-title">${esc(b.title)} <span class="card-sub">${isStop ? '移除' : '写入'}前确认</span></div>
    <div class="ml-list">${rows}</div>
    ${b.desc ? `<div class="ml-desc">安排：${esc(b.desc)}</div>` : ''}
    ${b.caution ? `<div class="med-inline-note">⚠️ ${esc(b.caution)}</div>` : ''}
    <div class="ml-actions">
      <button class="cta-btn" data-ok>${btnText}</button>
      <button class="pill-btn" data-cancel>取消</button>
    </div>`;
  const actions = el.querySelector('.ml-actions');
  el.querySelector('[data-cancel]').onclick = () => {
    actions.innerHTML = '<div class="ml-done">已取消，没有修改任何数据。</div>';
  };
  el.querySelector('[data-ok]').onclick = async () => {
    actions.innerHTML = '<div class="ml-done">正在写入…</div>';
    const r = await api('/api/meds/apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: b.action, items: b.items, op: b.op || 'merge' }),
    });
    if (!r || !r.ok) {
      actions.innerHTML = `<div class="ml-done err">${esc((r && r.error) || '写入失败')}</div>`;
      return;
    }
    actions.innerHTML = `<div class="ml-done ok">✅ ${esc(r.reply)}</div>`;
    toast(r.reply, 3200);
    const boot = await api('/api/bootstrap');
    state.boot = boot;
    renderTasks(boot);
    if (document.querySelector('#view-meds').classList.contains('active')) await renderMeds();
  };
  return el;
}

/* ---------------------------------------------------------------- 用药打卡页 */
async function renderMeds() {
  const data = await api('/api/meds');
  const meds = data.meds || [];
  const schedule = data.schedule || [];
  const adh = data.adherence || {};

  const doneN = schedule.filter(s => s.done).length;
  $('#medsKpi').innerHTML = `
    <div class="kpi"><b>${doneN}/${schedule.length}</b><span>今日已服</span></div>
    <div class="kpi"><b>${adh.rate || 0}%</b><span>7 天依从率</span></div>
    <div class="kpi"><b>${meds.length}</b><span>在服药物</span></div>`;
  $('#medsTodayHint').textContent = schedule.length
    ? `${doneN}/${schedule.length} 已完成 · 共 ${schedule.length} 个时段 / ${meds.length} 种药`
    : '还没有登记用药';
  const listHint = $('#medListHint');
  if (listHint) {
    const totalSlots = meds.reduce((n, m) => n + ((m.times || []).length || 1), 0);
    listHint.textContent = `${meds.length} 种药 · 共 ${totalSlots} 个时段（单药最多 8）`;
  }

  // 今日服药时间表
  const sch = $('#medsSchedule');
  sch.innerHTML = '';
  if (!schedule.length) {
    sch.innerHTML = `<div class="vital-empty">还没有登记用药。可以在右侧添加，或直接对我说“我在吃氨氯地平 5 mg，每天早上一片”。</div>`;
  }
  schedule.forEach(item => {
    const row = document.createElement('div');
    row.className = 'slot';
    row.innerHTML = `
      <div class="slot-time">${esc(item.time)}</div>
      <div><div class="slot-name">${esc(item.med_name)} <span class="slot-dose">${esc(item.content.replace(item.med_name, '').trim() || '')}</span></div>
        <div class="slot-dose">${item.done ? '已打卡' : '待打卡'}</div></div>
      <button class="slot-btn${item.done ? ' done' : ''}">${item.done ? '已服 ✓' : '打卡'}</button>`;
    const btn = row.querySelector('.slot-btn');
    if (!item.done) {
      btn.onclick = async () => {
        const r = await api('/api/meds/log', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: item.med_name, slot: item.slot }),
        });
        if (!r || !r.ok) { toast(r && r.error ? r.error : '打卡失败', 3600); return; }
        toast(`${item.med_name} ${item.slot} 已打卡，请继续遵医嘱服药`);
        const b = await api('/api/bootstrap');
        state.boot = b;
        renderTasks(b);
        await renderMeds();
      };
    }
    sch.appendChild(row);
  });

  // 用药清单
  const list = $('#medsList');
  list.innerHTML = '';
  if (!meds.length) {
    list.innerHTML = '<div class="vital-empty">清单为空。添加后，每个时段都能在这里打卡。</div>';
  }
  meds.forEach(m => {
    const row = document.createElement('div');
    row.className = 'med-row';
    row.innerHTML = `
      <div><div class="med-name">${esc(m.name)} <span class="med-meta">${esc(m.dose || '')}</span></div>
        <div class="med-meta">${esc(m.frequency || '')} · ${esc((m.times || []).join(' / '))}</div></div>
      <div class="med-actions">
        <button class="ghost tiny" data-edit="${esc(m.name)}">改时段</button>
        <button class="ghost tiny" data-stop="${esc(m.name)}">停用</button>
      </div>`;
    row.querySelector('[data-edit]').onclick = async () => {
      const cur = (m.times || []).join(',');
      const input = prompt(
        `「${m.name}」每天几点吃？用逗号分隔，最多 8 个\n注意：这里会「整体替换」（不是追加）\n例如：08:00,12:00,18:00,睡前`,
        cur);
      if (input === null) return;
      const periodHour = { 早上: '08:00', 早晨: '08:00', 上午: '08:00', 中午: '12:00',
                           下午: '15:00', 傍晚: '19:00', 晚上: '19:00', 睡前: '22:00' };
      const times = input.split(/[,，、\s]+/).filter(Boolean).map(t => {
        const hm = t.match(/^(\d{1,2})[:：](\d{2})$/);
        if (hm) return hm[1].padStart(2, '0') + ':' + hm[2];
        const pt = t.match(/^(早上|早晨|上午|中午|下午|傍晚|晚上|睡前)(\d{1,2})?[点时]?$/);
        if (pt) {
          if (pt[2]) {
            let h = Number(pt[2]);
            if (['下午', '傍晚', '晚上'].includes(pt[1]) && h < 12) h += 12;
            return String(h).padStart(2, '0') + ':00';
          }
          return periodHour[pt[1]] || '';
        }
        return t;
      }).filter(Boolean);
      if (!times.length) { toast('至少填一个时段'); return; }
      if (times.length > 8) { toast('单药最多 8 个时段'); return; }
      const bad = times.find(t => !/^([01]\d|2[0-3]):[0-5]\d$/.test(t));
      if (bad) { toast(`时段格式应为 HH:MM（${bad} 不符合）`, 3000); return; }
      const r = await api('/api/meds/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: m.name, dose: m.dose || '', times, op: 'replace' }),
      });
      if (!r || !r.ok) { toast(r && r.error ? r.error : '修改失败'); return; }
      toast(r.message || `已更新「${m.name}」`, 3600);
      await renderMeds();
      const b = await api('/api/bootstrap');
      state.boot = b;
      renderTasks(b);
    };
    row.querySelector('[data-stop]').onclick = async () => {
      if (!confirm(`停药要由医生决定。这里只是把它从打卡清单里移出，确定要移除「${m.name}」吗？`)) return;
      await api('/api/meds/stop', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: m.name }),
      });
      toast('已从打卡清单移除（不代表可以停药）');
      await renderMeds();
    };
    list.appendChild(row);
  });

  // 依从率
  const adhBox = $('#adhList');
  $('#adhHint').textContent = `${adh.days || 7} 天 · 应服 ${adh.expected || 0} 次 · 实服 ${adh.taken || 0} 次`;
  adhBox.innerHTML = '';
  const byMed = adh.by_med || {};
  const names = Object.keys(byMed);
  if (!names.length) {
    adhBox.innerHTML = '<div class="vital-empty">还没有用药计划，无法统计依从率。</div>';
  }
  names.forEach(name => {
    const v = byMed[name];
    const row = document.createElement('div');
    row.className = 'adh-row';
    row.innerHTML = `<div>${esc(name)}</div>
      <div class="adh-bar"><i style="width:${Math.min(100, v.rate)}%"></i></div>
      <div class="adh-num">${v.taken}/${v.expected} · ${v.rate}%</div>`;
    adhBox.appendChild(row);
  });
}

/* ---------------------------------------------------------------- 看板 */
async function renderDash(days) {
  state.dashDays = days;
  const grid = $('#dashGrid');
  grid.innerHTML = '<div class="vital-empty">正在计算…</div>';
  const data = await api('/api/overview?days=' + days);
  grid.innerHTML = '';
  const order = [
    ['bp', '血压'], ['glucose_fasting', '空腹血糖'], ['glucose_post', '餐后血糖'],
    ['ldl', 'LDL-C'], ['tg', '甘油三酯'], ['weight', '体重'],
  ];
  order.forEach(([key, title]) => {
    const t = data[key];
    const card = document.createElement('div');
    card.className = 'card';
    if (t && t.ok) {
      card.innerHTML = `<div class="chart-head">
          <div class="card-title">${esc(title)} <span class="card-sub">${t.count} 条记录</span></div>
          <div class="card-sub">${esc(t.stats.direction)}</div>
        </div>
        <div class="chart-host"></div>
        <div class="chart-stats">
          <span>均值 <b>${esc(t.stats.mean_text)}</b></span>
          <span>区间 <b>${t.stats.min}–${t.stats.max}</b> ${esc(t.unit)}</span>
          <span>超参考 <b>${t.abnormal}</b> 条</span>
        </div>`;
      card.querySelector('.chart-host').innerHTML = lineChart(t.series, { kind: t.kind, sub: t.sub, unit: t.unit });
    } else {
      card.innerHTML = `<div class="card-title">${esc(title)}</div>
        <div class="vital-empty" style="margin-top:10px">${esc((t && t.message) || '暂无记录')}</div>`;
    }
    grid.appendChild(card);
  });
}

/* ---------------------------------------------------------------- 档案 */
function fillProfileForm(p) {
  if (!p) return;
  $('#f_name').value = p.name || '';
  $('#f_birth').value = p.birth_year || '';
  $('#f_sex').value = p.sex || '男';
  $('#f_height').value = p.height_cm || '';
  $('#f_conditions').value = (p.conditions || []).join('，');
  $('#f_wake').value = p.wake_time || '06:30';
  $('#f_sleep').value = p.sleep_time || '22:30';
  $('#f_cook').value = String(p.can_cook == null ? 1 : p.can_cook);
  $('#f_budget').value = p.budget || 'normal';
  $('#f_taste').value = p.taste || 'normal';
}

/* ---------------------------------------------------------------- 事件绑定 */
function bindUI() {
  // 发送
  const input = $('#input');
  input.addEventListener('input', () => autoGrow(input));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input.value);
    }
  });
  $('#sendBtn').onclick = () => sendMessage(input.value);

  // tab 切换
  $$('.tab').forEach(t => {
    t.onclick = async () => {
      $$('.tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      $$('.view').forEach(v => v.classList.remove('active'));
      $('#view-' + t.dataset.view).classList.add('active');
      state.view = t.dataset.view;
      if (t.dataset.view === 'dash') await renderDash(state.dashDays);
      if (t.dataset.view === 'meds') await renderMeds();
    };
  });

  // 侧栏「用药打卡」直达
  const openMeds = $('#openMedsBtn');
  if (openMeds) {
    openMeds.onclick = () => {
      const tab = document.querySelector('.tab[data-view="meds"]');
      if (tab) tab.click();
    };
  }

  // 快捷入口
  const goChat = () => {
    const tab = document.querySelector('.tab[data-view="chat"]');
    if (tab) tab.click();
  };
  const qaMeds = $('#qaMeds');
  if (qaMeds) qaMeds.onclick = () => {
    const tab = document.querySelector('.tab[data-view="meds"]');
    if (tab) tab.click();
  };
  const qaPlan = $('#qaPlan');
  if (qaPlan) qaPlan.onclick = () => { goChat(); sendMessage('给我一份 7 天方案'); };
  const qaReport = $('#qaReport');
  if (qaReport) qaReport.onclick = () => { goChat(); sendMessage('帮我生成这周的报告'); };
  const qaLab = $('#qaLab');
  if (qaLab) qaLab.onclick = () => openLabModal();

  // 添加用药
  const medForm = $('#medForm');
  if (medForm) {
    medForm.onsubmit = async (e) => {
      e.preventDefault();
      const name = $('#medName').value.trim();
      if (!name) { toast('请先填药名'); return; }
      const raw = ($('#medTimes').value || '08:00').split(/[,，、\s]+/).filter(Boolean);
      // 允许写 8:00 / 早上8点 / 睡前 这类口语，统一成 HH:MM
      const periodHour = { 早上: '08:00', 早晨: '08:00', 上午: '08:00', 中午: '12:00',
                           下午: '15:00', 傍晚: '19:00', 晚上: '19:00', 睡前: '22:00' };
      const times = raw.map(t => {
        const hm = t.match(/^(\d{1,2})[:：](\d{2})$/);
        if (hm) return hm[1].padStart(2, '0') + ':' + hm[2];
        const pt = t.match(/^(早上|早晨|上午|中午|下午|傍晚|晚上|睡前)(\d{1,2})?[点时]?$/);
        if (pt) {
          if (pt[2]) {
            let h = Number(pt[2]);
            if (['下午', '傍晚', '晚上'].includes(pt[1]) && h < 12) h += 12;
            return String(h).padStart(2, '0') + ':00';
          }
          return periodHour[pt[1]] || '';
        }
        return t;
      }).filter(Boolean);
      if (times.length > 8) { toast('最多 8 个时段', 3000); return; }
      const bad = times.find(t => !/^([01]\d|2[0-3]):[0-5]\d$/.test(t));
      if (bad) { toast(`时段格式应为 HH:MM，例如 08:00（${bad} 不符合）`, 3200); return; }
      const r = await api('/api/meds/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, dose: $('#medDose').value.trim(), times, op: 'merge' }),
      });
      if (!r || !r.ok) { toast(r && r.error ? r.error : '添加失败'); return; }
      $('#medName').value = ''; $('#medDose').value = ''; $('#medTimes').value = '';
      toast(r.message || `已添加「${name}」`, 3600);
      const b = await api('/api/bootstrap');
      state.boot = b;
      renderTasks(b);
      await renderMeds();
    };
  }

  // 快捷问题
  const chips = [
    ['记录一次血糖', '早餐后血糖 9.6'],
    ['今日任务', '今天我要做什么'],
    ['这周报告', '帮我生成这周的报告'],
    ['用药冲突', '我在吃氢氯噻嗪和格列美脲，要注意什么'],
    ['盐能吃多少', '三高人群每天能吃多少盐'],
    ['检验单录入', '帮我录入这张化验单'],
  ];
  const chipBox = $('#quickChips');
  chips.forEach(([label, q]) => {
    const b = document.createElement('button');
    b.className = 'quick-chip';
    b.textContent = label;
    b.onclick = () => sendMessage(q);
    chipBox.appendChild(b);
  });

  // 大字
  const big = $('#bigFontBtn');
  big.classList.toggle('primary', state.bigFont);
  big.onclick = () => {
    state.bigFont = !state.bigFont;
    document.documentElement.classList.toggle('big', state.bigFont);
    localStorage.setItem('zhsg_big', state.bigFont ? '1' : '0');
    big.classList.toggle('primary', state.bigFont);
    toast(state.bigFont ? '已切换为大字模式' : '已恢复标准字号');
  };

  // 演示数据提示条：恢复我这边的演示数据（普通用户唯一可用的数据操作）
  const demoReset = $('#demoResetBtn');
  if (demoReset) {
    demoReset.onclick = async () => {
      if (!confirm('恢复演示数据？会重置你这边的指标、用药和对话记录（不影响其他访客）。')) return;
      const r = await api('/api/demo/reset', { method: 'POST' });
      const b = await api('/api/bootstrap');
      state.boot = b;
      renderProfile(b); renderVitals(b); renderTasks(b); renderDemoStrip(b);
      $('#messages').innerHTML = '';
      renderWelcome();
      toast(r.message || '已恢复演示数据');
    };
  }

  // 登录
  const loginBtn = $('#loginBtn');
  if (loginBtn) loginBtn.onclick = doLogin;
  const loginInput = $('#loginPassword');
  if (loginInput) loginInput.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

  // 档案
  $('#editProfileBtn').onclick = () => { fillProfileForm((state.boot || {}).profile); $('#profileMask').classList.add('show'); };
  $('#closeProfileBtn').onclick = () => $('#profileMask').classList.remove('show');
  $('#profileMask').onclick = (e) => { if (e.target.id === 'profileMask') e.target.classList.remove('show'); };
  $('#saveProfileBtn').onclick = async () => {
    const body = {
      name: $('#f_name').value.trim() || '演示用户',
      birth_year: Number($('#f_birth').value) || null,
      sex: $('#f_sex').value,
      height_cm: Number($('#f_height').value) || null,
      conditions: $('#f_conditions').value.split(/[，,、\s]+/).filter(Boolean),
      wake_time: $('#f_wake').value || '06:30',
      sleep_time: $('#f_sleep').value || '22:30',
      can_cook: Number($('#f_cook').value),
      budget: $('#f_budget').value,
      taste: $('#f_taste').value,
    };
    await api('/api/profile', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    $('#profileMask').classList.remove('show');
    const b = await api('/api/bootstrap');
    state.boot = b;
    renderProfile(b);
    toast('档案已保存，方案会按新条件重新生成');
  };

  // 指南库抽屉（只读）
  const openKb = () => { $('#kbDrawer').classList.add('show'); $('#kbMask').classList.add('show'); };
  const closeKb = () => { $('#kbDrawer').classList.remove('show'); $('#kbMask').classList.remove('show'); };
  $('#openKbBtn').onclick = openKb;
  $('#closeKbBtn').onclick = closeKb;
  $('#kbMask').onclick = closeKb;

  // 数据来源
  $('#openSourcesBtn').onclick = () => $('#sourcesMask').classList.add('show');
  $('#closeSourcesBtn').onclick = () => $('#sourcesMask').classList.remove('show');
  $('#sourcesMask').onclick = (e) => { if (e.target.id === 'sourcesMask') e.target.classList.remove('show'); };

  // 检验单录入
  $('#openLabBtn').onclick = openLabModal;
  $('#closeLabBtn').onclick = closeLabModal;
  $('#labMask').onclick = (e) => { if (e.target.id === 'labMask') closeLabModal(); };
  $('#labParseBtn').onclick = parseLabText;
  $('#labSampleBtn').onclick = async () => {
    const r = await api('/api/lab/sample');
    $('#labText').value = r.text || '';
    $('#labHint').textContent = '已填入示例，点「解析」看看识别效果';
  };
  $('#labCommitBtn').onclick = (e) => {
    const btn = e.currentTarget;
    commitLabItems($('#labResult'), btn.dataset.measuredAt || '', btn);
  };

  // 看板区间
  $$('#rangeSwitch button').forEach(b => {
    b.onclick = () => {
      $$('#rangeSwitch button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderDash(Number(b.dataset.days));
    };
  });
}

init().catch(err => {
  document.body.innerHTML = `<div style="padding:40px;font-family:sans-serif">
    <h2>页面初始化失败</h2><p>${esc(err.message)}</p>
    <p>请确认已在项目目录运行 <code>python app.py</code>，并访问终端显示的地址。</p></div>`;
});
