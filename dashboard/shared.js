/* ═══════════════════════════════════════════════════════════════════════════
   AI-SDN Dashboard — Shared JavaScript
   Navigation, Theme, SSE, Utilities, KPI Computations
   ═══════════════════════════════════════════════════════════════════════════ */

const API = 'http://127.0.0.1:5000';
let _dataCallback = null;
let _es = null;

/* ── Navigation ────────────────────────────────────────────────────────── */
const NAV_PAGES = [
  { id: 'overview',   href: 'index.html',      label: 'Overview',        icon: 'home' },
  { id: 'comparison', href: 'comparison.html',  label: 'DQN vs Baseline', icon: 'activity' },
  { id: 'network',    href: 'network.html',     label: 'Network',         icon: 'share-2' },
  { id: 'training',   href: 'training.html',    label: 'Training',        icon: 'trending-up' },
  { id: 'system',     href: 'system.html',      label: 'System',          icon: 'cpu' },
];

function injectNav(activePage) {
  const el = document.getElementById('main-nav');
  if (!el) return;
  const links = NAV_PAGES.map(p =>
    `<a href="${p.href}" class="nav-link${p.id === activePage ? ' active' : ''}">
      <i data-feather="${p.icon}"></i><span>${p.label}</span>
    </a>`
  ).join('');
  el.className = 'nav';
  el.innerHTML = `
    <div class="nav-logo">
      <div class="logo-dot" id="status-dot"></div>
      <span>AI-SDN Dashboard</span>
    </div>
    <div class="nav-links">${links}</div>
    <div class="nav-right">
      <span class="nav-info" id="nav-episode">Episode —</span>
      <span class="nav-info" id="nav-uptime">—</span>
      <button class="theme-btn" id="theme-toggle" title="Toggle dark/light mode">
        <svg id="ti-sun" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        <svg id="ti-moon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="display:none"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      </button>
    </div>`;
}

/* ── Icons ──────────────────────────────────────────────────────────────── */
function initIcons() {
  if (window.feather) feather.replace({ 'stroke-width': 1.75, width: 14, height: 14 });
}

/* ── Theme ──────────────────────────────────────────────────────────────── */
function initTheme() {
  const saved = localStorage.getItem('sdn-theme') || 'light';
  applyTheme(saved);
  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem('sdn-theme', next);
  });
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const sun = document.getElementById('ti-sun'), moon = document.getElementById('ti-moon');
  if (sun) sun.style.display  = theme === 'dark' ? 'none' : 'block';
  if (moon) moon.style.display = theme === 'dark' ? 'block' : 'none';
}

/* ── SSE ────────────────────────────────────────────────────────────────── */
function connectSSE() {
  if (_es) { try { _es.close(); } catch(e) {} }
  _es = new EventSource(`${API}/api/stream`);
  _es.onopen = () => { const d = document.getElementById('status-dot'); if (d) d.classList.add('live'); };
  _es.onerror = () => {
    const d = document.getElementById('status-dot'); if (d) d.classList.remove('live');
    _es.close(); setTimeout(connectSSE, 3000);
  };
  _es.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data);
      const ep = document.getElementById('nav-episode'); if (ep && d.episode_count) ep.textContent = `Episode ${d.episode_count}`;
      const ut = document.getElementById('nav-uptime');  if (ut && d.uptime_s != null) ut.textContent = `${Math.round(d.uptime_s)}s`;
      if (_dataCallback) _dataCallback(d);
    } catch(err) { console.warn('SSE parse error', err); }
  };
}

/* ── Init ───────────────────────────────────────────────────────────────── */
function initPage(pageName, callback) {
  injectNav(pageName);
  initTheme();
  initIcons();
  _dataCallback = callback || null;
  connectSSE();
}

/* ── Formatting ─────────────────────────────────────────────────────────── */
const fmt    = (n, d=2) => n == null ? '—' : Number(n).toFixed(d);
const fmtInt = n => n == null ? '—' : Math.round(n).toLocaleString();
const fmtPct = (n, d=1) => n == null ? '—' : (Number(n)*100).toFixed(d)+'%';
const setTxt = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };

/* ── Path helpers ───────────────────────────────────────────────────────── */
function pathBadge(p) {
  if (!p || p === '?') return '<span class="badge" style="opacity:.4">?</span>';
  const m = { PATH_A:['b-A','PATH A'], PATH_B:['b-B','PATH B'], PATH_C:['b-C','PATH C'], DROP:['b-D','DROP'] };
  const match = m[p] || m[Object.keys(m).find(k => p.includes(k.replace('PATH_','')))] ;
  if (match) return `<span class="badge ${match[0]}">${match[1]}</span>`;
  return `<span class="badge">${p}</span>`;
}
function utilColor(v) { return v>.8?'var(--red)':v>.5?'var(--yellow)':'var(--green)'; }

/* ── KPI Computations ───────────────────────────────────────────────────── */

/**
 * Jain's Fairness Index: (Σxi)² / (n × Σxi²)
 * Returns [0,1] — 1.0 = perfectly balanced, 1/n = worst case
 */
function jainFairnessIndex(utils) {
  const v = (utils||[]).filter(x => x!=null && x>=0);
  if (!v.length) return null;
  const sumX  = v.reduce((a,b)=>a+b, 0);
  const sumX2 = v.reduce((a,b)=>a+b*b, 0);
  return sumX2===0 ? 1 : (sumX*sumX)/(v.length*sumX2);
}

/**
 * Estimated avg latency (ms) from path distribution.
 * Path A via S3 = 7ms, Path B via S4 = 13ms, Path C crosslink ≈ 15ms.
 */
function estimatedLatency(pathCounts) {
  if (!pathCounts) return null;
  const a=pathCounts.PATH_A||0, b=pathCounts.PATH_B||0, c=pathCounts.PATH_C||0;
  const total = a+b+c;
  return total===0 ? null : (a*7 + b*13 + c*15)/total;
}

/**
 * Drop rate (0–1) from path counts.
 */
function dropRate(pathCounts) {
  if (!pathCounts) return null;
  const total = (pathCounts.PATH_A||0)+(pathCounts.PATH_B||0)+(pathCounts.PATH_C||0)+(pathCounts.DROP||0);
  return total===0 ? 0 : (pathCounts.DROP||0)/total;
}

/**
 * Throughput estimate in MB from state features[14,15].
 */
function throughputMB(state) {
  if (!state||state.length<16) return null;
  return ((state[14]+state[15])*1e7)/(1024*1024);
}

/**
 * Average utilization across first n links in state.
 */
function avgUtil(state, n=7) {
  if (!state||state.length<n) return 0;
  return state.slice(0,n).reduce((a,b)=>a+b,0)/n;
}

/**
 * Win rate — fraction of history snapshots where DQN reward > baseline.
 */
function winRate(history) {
  if (!history||!history.length) return null;
  return history.filter(h=>(h.reward_delta||0)>0).length/history.length;
}

/**
 * Agreement rate — fraction of flow_decisions where DQN === baseline.
 */
function agreementRate(decisions) {
  if (!decisions||!decisions.length) return null;
  return decisions.filter(d=>d.agreed===true).length/decisions.length;
}

/* ── D3 Helpers ─────────────────────────────────────────────────────────── */
function clearSvg(sel) { const s=d3.select(sel); s.selectAll('*').remove(); return s; }

function chartDimensions(svg, margins={}) {
  const W = svg.node()?.clientWidth||400;
  const H = parseFloat(svg.style('height'))||parseFloat(svg.attr('height'))||200;
  const M = {t:10,r:14,b:28,l:44,...margins};
  svg.attr('viewBox',`0 0 ${W} ${H}`);
  return {W,H,M};
}

function drawGridLines(svg,y,dims,ticks=4) {
  const {M,W}=dims;
  y.ticks(ticks).forEach(t=>{
    svg.append('line').attr('x1',M.l).attr('x2',W-M.r).attr('y1',y(t)).attr('y2',y(t)).attr('class','grid-line');
  });
}

function drawAxes(svg,x,y,dims,opts={}) {
  const {W,H,M}=dims;
  if (!opts.noX)
    svg.append('g').attr('class','axis').attr('transform',`translate(0,${H-M.b})`)
       .call(d3.axisBottom(x).ticks(opts.xTicks||5).tickFormat(opts.xFmt||''));
  svg.append('g').attr('class','axis').attr('transform',`translate(${M.l},0)`)
     .call(d3.axisLeft(y).ticks(opts.yTicks||4).tickFormat(opts.yFmt||d3.format('.2~f')));
}

/* ── Util Bars ──────────────────────────────────────────────────────────── */
const UTIL_LABELS = ['S1→S3 (A)','S1→S4 (B)','S2→S3 (A)','S2→S4 (B)','S3→S5 (A)','S4→S5 (B)','Crosslink (C)'];
const UTIL_COLORS = ['var(--pathA)','var(--pathB)','var(--pathA)','var(--pathB)','var(--pathA)','var(--pathB)','var(--pathC)'];

function renderUtilBars(containerId, state) {
  const el = document.getElementById(containerId);
  if (!el||!state||state.length<7) return;
  el.innerHTML = state.slice(0,7).map((v,i)=>{
    const pct=Math.round(v*100), col=v>.8?'var(--red)':v>.5?'var(--yellow)':UTIL_COLORS[i];
    return `<div class="util-row">
      <span class="util-label">${UTIL_LABELS[i]}</span>
      <div class="util-track"><div class="util-fill" style="width:${pct}%;background:${col}"></div></div>
      <span class="util-val" style="color:${col}">${pct}%</span>
    </div>`;
  }).join('');
}
