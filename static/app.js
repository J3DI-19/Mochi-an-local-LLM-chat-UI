/* Local AI Chat v2 — Mochi. Plain JS, no dependencies. */
(() => {
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const HDR = {'Content-Type': 'application/json', 'X-Local-Chat': '1'};
const ENGINE_ID = 'qwen3.8-27b-hauhaucs-iq3xs';
const params = new URLSearchParams(location.search);
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
/* ---------------- Mochi avatar ---------------- */
function mochiSVG() {
  return `<svg class="mochi" viewBox="0 0 120 124" data-state="idle" aria-hidden="true">
  <ellipse class="m-shadow" cx="60" cy="116" rx="30" ry="5" fill="#000" opacity=".3"/>
  <g class="m-all">
    <g class="m-antenna"><path d="M60 26 C58 18 61 11 67 9" fill="none" stroke="#9a7cff" stroke-width="3.5" stroke-linecap="round"/>
      <circle class="m-orbglow" cx="68" cy="8" r="9" fill="url(#mochiOrb)"/><circle class="m-orb" cx="68" cy="8" r="4.8" fill="#ffd36e"/></g>
    <g class="m-bodyfill"><path d="M60 24C88 24 104 42 104 67 104 93 85 108 60 108 35 108 16 93 16 67 16 42 32 24 60 24Z" fill="url(#mochiBody)"/>
      <path d="M60 24C88 24 104 42 104 67 104 93 85 108 60 108 35 108 16 93 16 67 16 42 32 24 60 24Z" fill="url(#mochiShade)"/></g>
    <ellipse cx="42" cy="42" rx="11" ry="6" fill="#fff" opacity=".35" transform="rotate(-28 42 42)"/>
    <g class="m-face">
      <ellipse class="m-eye" cx="45" cy="65" rx="6.5" ry="8.5" fill="#1b1530"/>
      <ellipse class="m-eye" cx="75" cy="65" rx="6.5" ry="8.5" fill="#1b1530"/>
      <circle class="m-glint" cx="47.4" cy="61.4" r="2.4" fill="#fff"/><circle class="m-glint" cx="77.4" cy="61.4" r="2.4" fill="#fff"/>
      <path class="m-happy" d="M38.5 67 Q45 58 51.5 67 M68.5 67 Q75 58 81.5 67" fill="none" stroke="#1b1530" stroke-width="3.6" stroke-linecap="round"/>
      <ellipse cx="34" cy="78" rx="6" ry="3.6" fill="#ff5e9a" opacity=".45"/><ellipse cx="86" cy="78" rx="6" ry="3.6" fill="#ff5e9a" opacity=".45"/>
      <path class="m-smile" d="M53 79 Q60 86 67 79" fill="none" stroke="#1b1530" stroke-width="3.4" stroke-linecap="round"/>
      <ellipse class="m-mouth" cx="60" cy="82" rx="5.2" ry="5" fill="#1b1530"/>
    </g>
    <path class="m-sweat" d="M95 46 q4 6 0 9 q-4 -3 0 -9z" fill="#7cc7ff"/>
  </g>
  <g class="m-dots" fill="#b9a8ff"><circle cx="92" cy="22" r="3.2"/><circle cx="101" cy="15" r="3.8"/><circle cx="111" cy="7" r="4.4"/></g>
  <path class="m-spark" d="M14 26 l2 6 6 2 -6 2 -2 6 -2 -6 -6 -2 6 -2z" fill="#ffd36e"/>
  <path class="m-spark" d="M104 34 l1.6 4.4 4.4 1.6 -4.4 1.6 -1.6 4.4 -1.6 -4.4 -4.4 -1.6 4.4 -1.6z" fill="#ff7eb6"/>
  <path class="m-spark" d="M24 96 l1.4 4 4 1.4 -4 1.4 -1.4 4 -1.4 -4 -4 -1.4 4 -1.4z" fill="#8b7bff"/>
</svg>`;
}
function mountAvatar(slot) { slot.innerHTML = mochiSVG(); return slot.firstElementChild; }
const reacts = new WeakMap();
function setMood(svg, state, ms) {
  if (!svg) return;
  clearTimeout(reacts.get(svg));
  svg.setAttribute('data-state', state);
  if (ms) reacts.set(svg, setTimeout(() => svg.setAttribute('data-state', 'idle'), ms));
}
// eyes follow the pointer a little on the big avatars
function lookAt(svg, e) {
  if (!svg || svg.getAttribute('data-state') !== 'idle') return;
  const r = svg.getBoundingClientRect(); const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
  const d = Math.hypot(dx, dy) || 1, k = Math.min(1, d / 400);
  $('.m-face', svg).style.transform = `translate(${(dx / d * 4 * k).toFixed(2)}px,${(dy / d * 3 * k).toFixed(2)}px)`;
}

/* ---------------- markdown (small, safe: everything is escaped first) ---------------- */
const KW = new Set(('if else elif for while return def class import from as with try except finally raise yield lambda pass break continue in is not and or ' +
  'function const let var new this typeof instanceof async await export default switch case throw catch do void delete of static extends super ' +
  'public private protected int float double char bool long short unsigned struct enum fn mut impl pub use match loop where trait type interface ' +
  'package func go defer select chan map range nil None True False true false null undefined self echo then fi done esac local SELECT FROM WHERE INSERT UPDATE DELETE JOIN ON GROUP BY ORDER').split(' '));
const BUILTIN = new Set('print len range str int list dict set tuple open console Math JSON Object Array String Number Promise document window require'.split(' '));
function highlight(code, lang) {
  const hashC = /^(py|python|sh|bash|shell|ps1|powershell|ruby|rb|yaml|yml|toml|r|perl|dockerfile|make|ini|conf)$/i.test(lang || '');
  const re = hashC
    ? /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\b\d[\d_]*\.?\d*(?:e[+-]?\d+)?\b|\b0x[\da-f]+\b)|([A-Za-z_$][\w$]*)/gi
    : /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->)|(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\b\d[\d_]*\.?\d*(?:e[+-]?\d+)?\b|\b0x[\da-f]+\b)|([A-Za-z_$][\w$]*)/gi;
  let out = '', last = 0, m;
  while ((m = re.exec(code))) {
    out += esc(code.slice(last, m.index)); last = re.lastIndex;
    const t = esc(m[0]);
    if (m[1]) out += `<span class="tk-c">${t}</span>`;
    else if (m[2]) out += `<span class="tk-s">${t}</span>`;
    else if (m[3]) out += `<span class="tk-n">${t}</span>`;
    else if (KW.has(m[4])) out += `<span class="tk-k">${t}</span>`;
    else if (BUILTIN.has(m[4])) out += `<span class="tk-b">${t}</span>`;
    else if (code[re.lastIndex] === '(') out += `<span class="tk-f">${t}</span>`;
    else out += t;
  }
  return out + esc(code.slice(last));
}
const COPY_ICON = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`\n]+)`/g, (_, c) => (codes.push(c), `\u0001${codes.length - 1}\u0001`));
  s = esc(s);
  s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`);
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^\w*])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>').replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');
  s = s.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  return s.replace(/\u0001(\d+)\u0001/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
}
function md(src) {
  const blocks = [];
  src = src.replace(/\r\n/g, '\n');
  // fenced code (an unclosed fence while streaming runs to the end)
  src = src.replace(/(^|\n)```([\w+#.-]*)[^\n]*\n([\s\S]*?)(\n```[ \t]*(?=\n|$)|$)/g, (_, pre, lang, code) => {
    blocks.push(`<div class="code"><div class="code-head"><span>${esc(lang || 'code')}</span><button class="copy" data-copy>${COPY_ICON}<span>Copy</span></button></div><pre><code>${highlight(code, lang)}</code></pre></div>`);
    return `${pre}\u0000${blocks.length - 1}\u0000\n`;
  });
  const lines = src.split('\n'); let html = '', i = 0;
  const isTableSep = l => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
  while (i < lines.length) {
    let l = lines[i];
    const ph = l.match(/^\u0000(\d+)\u0000$/);
    if (ph) { html += blocks[+ph[1]]; i++; continue; }
    if (!l.trim()) { i++; continue; }
    let m;
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { const n = Math.min(m[1].length + 1, 4); html += `<h${n}>${inline(m[2])}</h${n}>`; i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { html += '<hr>'; i++; continue; }
    if (/^\s*>/.test(l)) { const q = []; while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, '')); html += `<blockquote>${md(q.join('\n'))}</blockquote>`; continue; }
    if (l.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const row = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
      const head = row(l); i += 2; let t = '<table><thead><tr>' + head.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>';
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) t += '<tr>' + row(lines[i++]).map(c => `<td>${c}</td>`).join('') + '</tr>';
      html += t + '</tbody></table>'; continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
      const ordered = /^\s*\d+[.)]/.test(l), tag = ordered ? 'ol' : 'ul';
      const start = ordered ? parseInt(l, 10) : 1; let items = [], cur = null;
      while (i < lines.length) {
        const s = lines[i];
        if (/^\s*([-*+]|\d+[.)])\s+/.test(s) && (/^\s*\d+[.)]/.test(s) === ordered || /^\s{2,}/.test(s))) {
          if (/^\s{2,}/.test(s) && cur) cur.push(s.trim().replace(/^([-*+]|\d+[.)])\s+/, '• ')); else items.push(cur = [s.replace(/^\s*([-*+]|\d+[.)])\s+/, '')]);
          i++;
        } else if (s.trim() && /^\s{2,}/.test(s) && cur) { cur.push(s.trim()); i++; }
        else if (!s.trim() && i + 1 < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i + 1])) { i++; }
        else break;
      }
      html += `<${tag}${ordered && start !== 1 ? ` start="${start}"` : ''}>` + items.map(it => `<li>${it.map(inline).join('<br>')}</li>`).join('') + `</${tag}>`;
      continue;
    }
    const p = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*>|\u0000\d+\u0000$)/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i]) &&
           !(lines[i].includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1]))) p.push(lines[i++]);
    if (!p.length) { html += `<p>${inline(lines[i++])}</p>`; continue; }
    html += `<p>${p.map(inline).join('<br>')}</p>`;
  }
  return html;
}
function withCaret(html) {
  const c = '<span class="caret"></span>';
  const m = html.match(/(<\/(p|li|h\d|td)>)((<\/(ul|ol|tr|tbody|table|blockquote)>)*)$/);
  return m ? html.slice(0, m.index) + c + html.slice(m.index) : html + c;
}
function splitThink(content, reasoning) {
  let r = reasoning || '', c = content || '';
  const o = c.indexOf('<think>');
  if (o !== -1) {
    const e = c.indexOf('</think>', o);
    if (e === -1) { r += c.slice(o + 7); c = c.slice(0, o); }
    else { r += c.slice(o + 7, e); c = c.slice(0, o) + c.slice(e + 8); }
  } else if (c.includes('</think>')) { const e = c.indexOf('</think>'); r += c.slice(0, e); c = c.slice(e + 8); }
  return { reasoning: r.trim(), content: c.replace(/^\s+/, '') };
}


/* ================= state ================= */
const PRESETS0 = [
  { id: 'mochi', name: 'Mochi (default)', text: "You are Mochi, a friendly and sharp AI assistant running privately on Atharva's PC (ATHEREAL). Be accurate and concise, use Markdown when it helps, and say so when you are unsure." },
  { id: 'coder', name: 'Coding buddy', text: 'You are an expert software engineer. Give correct, idiomatic code with short explanations. Prefer complete runnable snippets, point out edge cases, and never invent APIs.' },
  { id: 'brief', name: 'Short & direct', text: 'Answer in as few words as possible. Bullet points over paragraphs. No preamble.' },
  { id: 'tutor', name: 'Patient tutor', text: 'You are a patient tutor. Explain step by step with simple examples, check understanding, and avoid jargon unless you define it.' },
  { id: 'none', name: 'No system prompt', text: '' }
];
const ACCENTS = {
  mochi: ['#8b7bff', '#ff7eb6', '#ffb37a'], ocean: ['#4f8bff', '#2fd6c9', '#7ce3ff'], mint: ['#22c58b', '#7be0a6', '#d9f99d'],
  sunset: ['#ff6b4a', '#ff9f43', '#ffd36e'], rose: ['#e2508f', '#ff8fab', '#ffc2d1'], mono: ['#9aa0b4', '#c7cbd8', '#e5e7ee']
};
const DEFAULTS = {
  theme: 'dark', accent: 'mochi', customAccent: '#8b7bff', fontSize: 15, density: 'comfy', width: 'normal', aurora: true,
  mochi: true, mochiMotion: 'full', sendOnEnter: true, defaultModel: null, model: null, effort: 'medium',
  tempMode: 'auto', temperature: 0.7, maxTokens: 0, showStats: true, presets: PRESETS0, presetId: 'mochi', v: 2,
  toolsEnabled: true, toolsAutoExec: true, maxToolRounds: 5, disabledTools: []
};
const LS_SET = 'lac.settings.v2', LS_CUR = 'lac.current.v2';
const safeJSON = s => { try { return s ? JSON.parse(s) : null; } catch { return null; } };
let S = Object.assign({}, DEFAULTS, safeJSON(localStorage.getItem(LS_SET)) || {});
let auth = { authed: false, has_password: false, local: false, lan: false, internet: false, tunnel: false, localhost_no_login: true, user: null, perms: {}, limits: null };
let chatList = [];             // metas from the server
let chats = {};                // id -> full chat (loaded on demand)
let currentId = null;
let models = null;             // /api/models
let vram = null;               // /api/vram
let lanInfo = null, fwInfo = null;
let gen = null, attachments = [], stick = true;
let searchQ = '', searchRes = null, listLoading = true;

const el = {
  app: $('#app'), list: $('#chatList'), thread: $('#thread'), msgs: $('#messages'), empty: $('#empty'), input: $('#input'),
  send: $('#sendBtn'), toolsBtn: $('#toolsBtn'), attachRow: $('#attachRow'), file: $('#fileInput'), hint: $('#hint'), drop: $('#drop'), toBottom: $('#toBottom'),
  modelPicker: $('#modelPicker'), modelBtn: $('#modelBtn'), modelMenu: $('#modelMenu'), modelName: $('#modelName'), modelSub: $('#modelSub'), modelDot: $('#modelDot'),
  modal: $('#modal'), toasts: $('#toasts'), menu: $('#menuPop'), search: $('#search')
};
const heroAv = mountAvatar($('#heroAvatar')), brandAv = mountAvatar($('#brandAvatar')), modalAv = mountAvatar($('#modalAvatar')), authAv = mountAvatar($('#authAvatar'));

/* ================= server API ================= */
class ApiError extends Error { constructor(msg, status, data) { super(msg); this.status = status; this.data = data || {}; } }
async function api(path, method = 'GET', body) {
  const opt = { method, headers: HDR, credentials: 'same-origin' };
  if (body !== undefined) opt.body = JSON.stringify(body);
  let r;
  try { r = await fetch(path, opt); } catch { throw new ApiError('Lost connection to the chat server', 0); }
  let d = null; try { d = await r.json(); } catch { }
  if (r.status === 401 && !path.startsWith('/api/auth/')) { showAuth(); throw new ApiError('Signed out', 401, d); }
  if (!r.ok) throw new ApiError((d && d.error) || `HTTP ${r.status}`, r.status, d);
  return d;
}

/* ================= settings / theme ================= */
let saveSetT;
function saveSettings() {
  localStorage.setItem(LS_SET, JSON.stringify(S));
  clearTimeout(saveSetT);
  saveSetT = setTimeout(() => { if (auth.authed) api('/api/settings', 'PUT', S).catch(() => {}); }, 500);
}
const mixHex = (a, b, t) => { const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); const x = p(a), y = p(b); return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join(''); };
function accentColors() {
  if (S.accent === 'custom' && /^#[0-9a-f]{6}$/i.test(S.customAccent)) { const c = S.customAccent; return [c, mixHex(c, '#ff7eb6', .45), mixHex(c, '#ffd36e', .55)]; }
  return ACCENTS[S.accent] || ACCENTS.mochi;
}
function applyLook() {
  const root = document.documentElement, sysLight = matchMedia('(prefers-color-scheme: light)').matches;
  const theme = S.theme === 'system' ? (sysLight ? 'light' : 'dark') : S.theme;
  root.dataset.theme = theme;
  const [a1, a2, a3] = accentColors();
  root.style.setProperty('--a1', a1); root.style.setProperty('--a2', a2); root.style.setProperty('--a3', a3);
  root.style.setProperty('--fs', (S.fontSize || 15) + 'px');
  root.style.setProperty('--gap', { compact: '12px', comfy: '22px', spacious: '32px' }[S.density] || '22px');
  root.style.setProperty('--maxw', { narrow: '700px', normal: '820px', wide: '1040px' }[S.width] || '820px');
  const b = document.body;
  b.classList.toggle('dense-compact', S.density === 'compact'); b.classList.toggle('dense-spacious', S.density === 'spacious');
  b.classList.toggle('mochi-off', !S.mochi); b.classList.toggle('mochi-subtle', S.mochiMotion === 'subtle'); b.classList.toggle('mochi-static', S.mochiMotion === 'static');
  b.classList.toggle('calm', !S.aurora);
  const meta = $('meta[name=theme-color]'); if (meta) meta.content = theme === 'light' ? '#f6f4ff' : '#09090f';
}
matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if (S.theme === 'system') applyLook(); });
applyLook();
$('#themeBtn').onclick = () => { S.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; applyLook(); saveSettings(); };
const sysPrompt = () => { const p = (S.presets || []).find(p => p.id === S.presetId); return p ? p.text : PRESETS0[0].text; };

/* ================= toasts & modal ================= */
function toast(text, kind, action) {
  const t = document.createElement('div'); t.className = 'toast ' + (kind || '');
  t.innerHTML = `<i></i><span>${esc(text)}</span>${action ? `<button class="btn-sm">${esc(action.label)}</button>` : ''}`;
  if (action) $('button', t).onclick = () => { action.fn(); kill(); };
  el.toasts.appendChild(t);
  const kill = () => { t.classList.add('out'); setTimeout(() => t.remove(), 320); };
  setTimeout(kill, action ? 7000 : 3600);
  while (el.toasts.children.length > 4) el.toasts.firstChild.remove();
}
function confirmModal(title, text, yes, mood, check, extraHtml) {
  $('#modalTitle').textContent = title;
  $('#modalText').textContent = text || '';
  $('#modalText').hidden = !text;
  const ex = $('#modalExtra');
  if (ex) { ex.innerHTML = extraHtml || ''; ex.hidden = !extraHtml; }
  $('#modalYes').textContent = yes || 'OK';
  $('#modalCheckWrap').hidden = !check;
  if (check) { $('#modalCheckText').textContent = check.text; $('#modalCheck').checked = !!check.value; }
  el.modal.classList.add('open'); el.modal.setAttribute('aria-hidden', 'false'); setMood(modalAv, mood || 'idle');
  setTimeout(() => $('#modalYes').focus(), 60);
  return new Promise(res => {
    const close = v => { el.modal.classList.remove('open'); el.modal.setAttribute('aria-hidden', 'true'); if (ex) { ex.innerHTML = ''; ex.hidden = true; } $('#modalText').hidden = false; modalClose = null; res(v && check ? { ok: true, checked: $('#modalCheck').checked } : v); };
    modalClose = () => close(false);
    $('#modalYes').onclick = () => close(true); $('#modalNo').onclick = () => close(false);
    el.modal.onclick = e => { if (e.target === el.modal) close(false); };
  });
}
let modalClose = null;
function promptModal(title, value) {
  return new Promise(res => {
    $('#modalTitle').textContent = title; $('#modalCheckWrap').hidden = true;
    const ex = $('#modalExtra'); if (ex) { ex.innerHTML = ''; ex.hidden = true; }
    $('#modalText').hidden = false;
    $('#modalText').innerHTML = `<input class="modal-input" id="modalInput" maxlength="120">`;
    const inp = $('#modalInput'); inp.value = value || '';
    $('#modalYes').textContent = 'Save'; el.modal.classList.add('open'); setMood(modalAv, 'idle');
    setTimeout(() => { inp.focus(); inp.select(); }, 60);
    const close = v => { el.modal.classList.remove('open'); modalClose = null; res(v); };
    modalClose = () => close(null);
    inp.onkeydown = e => { if (e.key === 'Enter') close(inp.value.trim()); };
    $('#modalYes').onclick = () => close(inp.value.trim()); $('#modalNo').onclick = () => close(null);
    el.modal.onclick = e => { if (e.target === el.modal) close(null); };
  });
}

/* ================= auth ================= */
let authMode = 'login';
function showAuth(state) {
  if (state) auth = Object.assign(auth, state);
  auth.authed = false; stopPolls();
  el.app.hidden = true; $('#auth').hidden = false;
  const setup = !auth.has_password;
  authMode = setup ? (auth.local ? 'setup' : 'nosetup') : 'login';
  $('#authTitle').textContent = setup ? (auth.local ? 'Create a password' : 'Not set up yet') : 'Welcome back';
  $('#authText').textContent = setup ? (auth.local ? 'Protect your chats. You need this for phone / LAN access.' : 'Create a password on the PC first (open http://127.0.0.1:8765 there).') : 'Sign in to chat with Mochi.';
  $('#authPw2Wrap').hidden = authMode !== 'setup';
  $('#authUserWrap').hidden = authMode === 'setup';
  $('#authUser').placeholder = auth.local ? 'Username (blank = PC owner)' : 'Username';
  $('#authUser').required = !auth.local;
  $('#authPw').autocomplete = setup ? 'new-password' : 'current-password';
  $('#authPw').disabled = authMode === 'nosetup';
  $('#authBtn').textContent = setup ? 'Create password' : 'Sign in';
  $('#authBtn').disabled = authMode === 'nosetup';
  $('#authNote').textContent = setup ? 'At least 8 characters. Stored only as a salted PBKDF2 hash on this PC.' : (auth.tunnel ? '🔒 Secure internet link · every account needs its password.' : (auth.lan && !auth.local ? 'Connected over your local network.' : ''));
  $('#authErr').textContent = ''; $('#authPw').value = ''; $('#authPw2').value = '';
  setMood(authAv, 'idle');
  setTimeout(() => (authMode === 'login' && !$('#authUser').value && !auth.local ? $('#authUser') : $('#authPw')).focus(), 80);
}
$$('[data-eye]').forEach(b => b.onclick = () => { const i = $('#' + b.dataset.eye); i.type = i.type === 'password' ? 'text' : 'password'; });
$('#authForm').onsubmit = async e => {
  e.preventDefault();
  const pw = $('#authPw').value, btn = $('#authBtn'), err = $('#authErr');
  err.textContent = '';
  if (authMode === 'setup') {
    if (pw.length < 8) { err.textContent = 'Use at least 8 characters.'; return shake(); }
    if (pw !== $('#authPw2').value) { err.textContent = "Passwords don't match."; return shake(); }
  }
  btn.disabled = true; setMood(authAv, 'thinking');
  try {
    await api(authMode === 'setup' ? '/api/auth/setup' : '/api/auth/login', 'POST', authMode === 'setup' ? { password: pw } : { username: $('#authUser').value.trim(), password: pw });
    $('#authPw').value = ''; $('#authPw2').value = '';
    setMood(authAv, 'done'); await sleep(reduced() ? 0 : 420);
    await boot();
    if (authMode === 'setup') toast('Password created — you can now use LAN mode', 'ok');
  } catch (ex) {
    err.textContent = ex.message; setMood(authAv, 'error', 1800); shake();
  } finally { btn.disabled = false; }
};
function shake() { const c = $('#authForm'); c.classList.remove('shake'); void c.offsetWidth; c.classList.add('shake'); }
async function logout(all) {
  if (all && !await confirmModal('Sign out everywhere?', 'Every browser and phone signed in to Local AI Chat will need the password again.', 'Sign out all', 'error')) return;
  try { await api('/api/auth/logout', 'POST', { all: !!all }); } catch { }
  chats = {}; chatList = []; currentId = null; localStorage.removeItem(LS_CUR);
  const st = await api('/api/auth/state').catch(() => null);
  if (st && st.authed) { auth = Object.assign(auth, st); if (!all) { await boot(); } toast(all ? 'Your other sessions were signed out' : 'This PC skips login for the owner (see Settings › Account)', 'ok'); return; }
  showAuth(st || {});
}
$('#logoutBtn').onclick = () => logout(false);
async function shutdownMochi() {
  if (!isMaster() || !auth.local) return;
  let info = null;
  try { info = await api('/api/shutdown'); } catch (ex) { toast(ex.message, 'bad'); return; }
  const items = ['Stop the Mochi chat server'];
  if (info.searxng && info.searxng.running) items.push('Stop SearXNG private web search');
  if (info.internet && info.internet.active) items.push(`Turn off the internet link (${esc(info.internet.provider || 'tunnel')})`);
  const loadedNames = [];
  if (info.engine) loadedNames.push(`RDNA4 engine (${info.engine.short})`);
  if (info.lmstudio_loaded && info.lmstudio_loaded.length) loadedNames.push(...info.lmstudio_loaded.map(m => m.name));
  const hasModels = loadedNames.length > 0;
  const lanChanged = !!(info.lan && info.lan.enabled && !info.lan.was_enabled_at_start);
  const extra = `<div class="shutdown-box">
    <div>Will stop right now:</div>
    <ul>${items.map(x => `<li>${x}</li>`).join('')}</ul>
    <label class="chk"><input type="checkbox" id="sdUnload" checked><span>Unload all loaded models${hasModels ? ` (${esc(loadedNames.join(', '))})` : ' (none loaded right now)'}</span></label>
    ${lanChanged ? '<label class="chk"><input type="checkbox" id="sdLan" checked><span>Turn LAN mode back off (was off when you opened Mochi)</span></label>' : ''}
  </div>`;
  const p = confirmModal('Shut down Mochi?', 'This cleanly stops Mochi and returns things to how they were.', 'Shut down', 'idle', null, extra);
  let unload = true, restoreLan = true;
  const yesBtn = $('#modalYes');
  const origClick = yesBtn.onclick;
  yesBtn.onclick = () => {
    const u = $('#sdUnload'), l = $('#sdLan');
    unload = u ? u.checked : true;
    restoreLan = l ? l.checked : true;
    origClick();
  };
  if (!await p) return;
  closeSheets();
  if (gen) stopGen();
  try {
    await api('/api/shutdown', 'POST', { unload_models: unload, restore_lan: restoreLan });
  } catch (ex) { toast(ex.message, 'bad'); return; }
  stopPolls();
  auth.authed = false;
  el.app.hidden = true;
  $('#auth').hidden = false;
  $('#authTitle').textContent = 'Mochi is shut down';
  $('#authText').textContent = 'The chat server, search, internet link' + (unload ? ' and loaded models' : '') + ' were stopped cleanly.';
  $('#authUserWrap').hidden = true;
  $('#authPw').closest('.pw').hidden = true;
  $('#authPw2Wrap').hidden = true;
  $('#authBtn').hidden = true;
  $('#authErr').textContent = '';
  $('#authNote').innerHTML = 'You can close this tab, or run <code>Start-ChatUI.ps1</code> on this PC to start Mochi again.';
  setMood(authAv, 'idle');
}
if ($('#shutdownBtn')) $('#shutdownBtn').onclick = shutdownMochi;

/* ================= sidebar & chats ================= */
const narrow = () => matchMedia('(max-width: 860px)').matches;
if (narrow()) el.app.classList.add('side-closed');
$('#sideToggle').onclick = () => el.app.classList.toggle('side-closed');
$('#scrim').onclick = $('#sideClose').onclick = () => el.app.classList.add('side-closed');
const ICON = {
  dots: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>',
  pin: '<svg viewBox="0 0 24 24"><path d="M9 3h6l-1 6 4 4H6l4-4zM12 13v8"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/></svg>',
  del: '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
  dl: '<svg viewBox="0 0 24 24"><path d="M12 4v12M7 11l5 5 5-5M4 20h16"/></svg>',
  copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  regen: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5"/></svg>'
};
function ago(t) {
  const s = (Date.now() - t) / 1000;
  if (s < 60) return 'just now'; if (s < 3600) return Math.floor(s / 60) + 'm ago'; if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  if (s < 7 * 86400) return Math.floor(s / 86400) + 'd ago'; return new Date(t).toLocaleDateString();
}
function bucket(t) {
  const d = new Date(), today = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  if (t >= today) return 'Today'; if (t >= today - 86400e3) return 'Yesterday'; if (t >= today - 7 * 86400e3) return 'Previous 7 days'; return 'Older';
}
function hl(text, q) {
  if (!q) return esc(text);
  const i = text.toLowerCase().indexOf(q.toLowerCase()); if (i < 0) return esc(text);
  return esc(text.slice(0, i)) + '<mark>' + esc(text.slice(i, i + q.length)) + '</mark>' + esc(text.slice(i + q.length));
}
function renderList() {
  const L = el.list;
  if (listLoading) { L.innerHTML = '<div class="skel"></div><div class="skel" style="width:80%"></div><div class="skel" style="width:90%"></div>'; return; }
  const items = searchRes || chatList;
  if (!items.length) {
    L.innerHTML = searchRes ? `<div class="list-empty"><b>🔍</b>No chats match “${esc(searchQ)}”</div>` : '<div class="list-empty"><b>💬</b>No chats yet.<br>Say hi to Mochi!</div>';
    return;
  }
  let html = '', sec = null;
  for (const c of items) {
    const s = searchRes ? 'Results' : (c.pinned ? 'Pinned' : bucket(c.updated));
    if (s !== sec) { html += `<div class="list-sec">${s === 'Pinned' ? ICON.pin : ''}${s}</div>`; sec = s; }
    html += `<div class="chat-item${c.id === currentId ? ' active' : ''}" data-id="${esc(c.id)}" tabindex="0">
      ${c.pinned && !searchRes ? `<span class="pin">${ICON.pin}</span>` : ''}
      <span class="t">${hl(c.title || 'New chat', searchQ)}${searchRes && c.snippet && c.snippet !== c.title ? `<span class="sub">${hl(c.snippet, searchQ)}</span>` : `<span class="sub">${ago(c.updated)}</span>`}</span>
      <span class="acts"><button data-menu title="More">${ICON.dots}</button></span></div>`;
  }
  L.innerHTML = html;
}
el.list.addEventListener('click', e => {
  const it = e.target.closest('.chat-item'); if (!it) return;
  if (e.target.closest('[data-menu]')) { e.stopPropagation(); return chatMenu(it.dataset.id, e.target.closest('[data-menu]')); }
  openChat(it.dataset.id);
});
el.list.addEventListener('keydown', e => { const it = e.target.closest('.chat-item'); if (it && e.key === 'Enter') openChat(it.dataset.id); });
el.list.addEventListener('contextmenu', e => { const it = e.target.closest('.chat-item'); if (it) { e.preventDefault(); chatMenu(it.dataset.id, null, e); } });
function chatMenu(id, anchor, ev) {
  const meta = chatList.find(c => c.id === id) || {};
  el.menu.innerHTML = `<button data-a="pin">${ICON.pin}${meta.pinned ? 'Unpin' : 'Pin to top'}</button>
    <button data-a="rename">${ICON.edit}Rename</button><hr>
    <button data-a="md">${ICON.dl}Export Markdown</button><button data-a="json">${ICON.dl}Export JSON</button><hr>
    <button data-a="del" class="danger">${ICON.del}Delete</button>`;
  el.menu.hidden = false;
  const r = anchor ? anchor.getBoundingClientRect() : { left: ev.clientX, bottom: ev.clientY, right: ev.clientX };
  const w = el.menu.offsetWidth, h = el.menu.offsetHeight;
  el.menu.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - 20)) + 'px';
  el.menu.style.top = Math.max(8, Math.min(innerHeight - h - 8, r.bottom + 4)) + 'px';
  el.menu.onclick = async e => {
    const a = e.target.closest('[data-a]'); if (!a) return; closeMenu();
    const act = a.dataset.a;
    try {
      if (act === 'pin') { await api(`/api/chats/${id}`, 'PATCH', { pinned: !meta.pinned }); toast(meta.pinned ? 'Unpinned' : 'Pinned 📌', 'ok'); }
      if (act === 'rename') {
        const t = await promptModal('Rename chat', meta.title); if (!t) return;
        const r = await api(`/api/chats/${id}`, 'PATCH', { title: t });
        if (chats[id]) { chats[id].title = t; chats[id].rev = r.rev; }
        toast('Renamed', 'ok');
      }
      if (act === 'md' || act === 'json') { location.href = `/api/chats/${id}/export?format=${act}`; toast('Exporting…'); }
      if (act === 'del') {
        if (!await confirmModal('Delete this chat?', `“${meta.title || 'New chat'}” will be removed from every device.`, 'Delete', 'error')) return;
        await api(`/api/chats/${id}`, 'DELETE'); delete chats[id];
        if (currentId === id) { currentId = null; localStorage.removeItem(LS_CUR); renderChat(); }
        toast('Chat deleted', 'ok');
      }
      await refreshList();
    } catch (ex) { toast(ex.message, 'bad'); }
  };
}
const closeMenu = () => { el.menu.hidden = true; };
document.addEventListener('pointerdown', e => { if (!el.menu.hidden && !el.menu.contains(e.target)) closeMenu(); });

async function refreshList() {
  try {
    const d = await api('/api/chats'); chatList = d.chats || []; listLoading = false;
    if (searchQ) await runSearch(); else renderList();
    // another device changed the open chat → pull it
    const m = chatList.find(c => c.id === currentId), c = chats[currentId];
    if (m && c && m.rev > (c.rev || 0) && !gen && !c._dirty) {
      const fresh = await api(`/api/chats/${currentId}`); chats[currentId] = fresh;
      if (currentId === fresh.id) renderChat(false, true);
    }
    if (currentId && !m && c && c.rev) { currentId = null; renderChat(); toast('This chat was deleted on another device'); }
  } catch { }
}
let searchT;
el.search.addEventListener('input', () => { clearTimeout(searchT); searchT = setTimeout(runSearch, 220); $('#searchClear').hidden = !el.search.value; });
el.search.addEventListener('keydown', e => { if (e.key === 'Escape') { el.search.value = ''; runSearch(); el.search.blur(); } });
$('#searchClear').onclick = () => { el.search.value = ''; runSearch(); };
async function runSearch() {
  searchQ = el.search.value.trim(); $('#searchClear').hidden = !searchQ;
  if (!searchQ) { searchRes = null; return renderList(); }
  try { const d = await api('/api/search?q=' + encodeURIComponent(searchQ)); if (searchQ === el.search.value.trim()) { searchRes = d.results; renderList(); } } catch { }
}
function newChat() {
  if (gen) stopGen();
  currentId = null; localStorage.removeItem(LS_CUR); renderList(); renderChat();
  el.input.focus(); if (narrow()) el.app.classList.add('side-closed');
  setMood(heroAv, 'done', 900);
}
$('#newChat').onclick = newChat;
async function openChat(id) {
  if (gen) stopGen();
  currentId = id; localStorage.setItem(LS_CUR, id); renderList();
  if (narrow()) el.app.classList.add('side-closed');
  if (!chats[id]) {
    el.empty.classList.add('gone'); el.msgs.innerHTML = '<div class="skel" style="height:60px;width:50%;margin-left:auto"></div><div class="skel" style="height:120px"></div>';
    try { chats[id] = await api(`/api/chats/${id}`); }
    catch (ex) { toast(ex.message, 'bad'); currentId = null; renderChat(); return; }
    if (currentId !== id) return;
  }
  renderChat(true);
}
const cur = () => currentId ? chats[currentId] : null;
async function saveChat(c) {
  c._dirty = true;
  const body = { id: c.id, title: c.title, created: c.created, updated: c.updated, pinned: c.pinned, messages: c.messages.map(m => { const x = Object.assign({}, m); delete x.streaming; return x; }) };
  try {
    const r = await api(`/api/chats/${c.id}`, 'PUT', body); c.rev = r.rev; c._dirty = false;
    const i = chatList.findIndex(x => x.id === c.id); if (i >= 0) chatList[i] = r.meta; else chatList.unshift(r.meta);
    chatList.sort((a, b) => (b.pinned - a.pinned) || (b.updated - a.updated));
    if (!searchQ) renderList();
  } catch (ex) {
    if (ex.status === 413) toast('Chat too large to save — remove some images', 'bad'); else if (ex.status !== 401) toast('Could not save chat: ' + ex.message, 'bad');
  }
}
async function migrateLocal() {
  if (localStorage.getItem('lac.migrated.v2')) return;
  const old = safeJSON(localStorage.getItem('lac.chats.v1')) || [];
  const good = old.filter(c => c && /^[A-Za-z0-9_-]{4,64}$/.test(c.id) && Array.isArray(c.messages) && c.messages.length);
  if (good.length) {
    try { const r = await api('/api/chats/import', 'POST', { chats: good }); if (r.imported) toast(`Moved ${r.imported} chat${r.imported > 1 ? 's' : ''} from this browser to the server`, 'ok'); }
    catch { return; }
  }
  const s1 = safeJSON(localStorage.getItem('lac.settings.v1'));
  if (s1 && !localStorage.getItem(LS_SET)) { if (s1.theme) S.theme = s1.theme; if (s1.model) S.model = s1.model; }
  localStorage.setItem('lac.migrated.v2', '1');
}

/* ================= models, jobs, VRAM ================= */
const GB = b => (b / 1e9).toFixed(1) + ' GB';
const fmtMB = mb => mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : Math.round(mb) + ' MB';
function modelOptions() {
  const out = [];
  if (!models) return out;
  const engs = models.engines || [{ key: '27b', id: ENGINE_ID, name: 'Qwen3.8 27B', short: '27B', quant: 'IQ3_XS', online: !!models.engine.online, vision: true }];
  for (const e of engs) out.push({ backend: 'engine', id: e.id, key: e.key, short: e.short, quant: e.quant, label: e.name.split(' · ')[0], sub: e.quant + ' · RDNA4 engine', online: !!e.online, vision: !!e.vision, think: 'full' });
  for (const m of models.lmstudio.models || []) {
    if (m.type === 'embedding' || m.type === 'embeddings') continue;
    const r = m.reasoning || [];
    out.push({ backend: 'lmstudio', id: m.key, label: m.name, sub: [m.params, m.quant].filter(Boolean).join(' · ') + ' · LM Studio', online: m.loaded && models.lmstudio.online,
               vision: m.vision, think: r.includes('off') && r.includes('on') ? 'binary' : (r.length ? 'on' : 'none'), size: m.size });
  }
  return out;
}
const sameModel = (a, b) => a && b && a.backend === b.backend && a.id === b.id;
function selModel() {
  const o = modelOptions(), s = o.find(x => sameModel(x, S.model));
  if (s && s.online) return s;
  const pick = o.find(x => x.online && sameModel(x, S.defaultModel)) || o.find(x => x.online && x.backend === 'engine') || o.find(x => x.online);
  return pick || s || null;
}
function useModel(o, quiet) {
  S.model = { backend: o.backend, id: o.id }; saveSettings(); renderPicker(); renderEffort();
  if (!quiet) toast(`Chatting with ${o.label}`, 'ok');
}
function renderPicker() {
  const s = selModel();
  el.modelName.textContent = s ? s.label : (models ? (isMaster() ? 'No model online' : 'No model available') : 'Checking models…');
  el.modelSub.textContent = s ? (s.backend === 'engine' ? (s.short || '27B') + ' · RDNA4' : 'LM Studio') : '';
  el.modelDot.className = 'dot ' + (s && s.online ? 'on' : (job.state === 'running' ? 'busy' : 'off'));
  const o = modelOptions(); const on = o.filter(x => x.online), off = o.filter(x => !x.online);
  const item = x => `<button class="mm-item${sameModel(x, s) ? ' sel' : ''}${x.online ? '' : ' off'}" data-b="${x.backend}" data-id="${esc(x.id)}">
      <div class="nm"><b>${esc(x.label)}</b><small>${x.online ? esc(x.sub) : 'not loaded · click to load'}</small></div>
      ${x.backend === 'engine' ? '<span class="tag f">fast</span>' : ''}${x.vision ? '<span class="tag v">vision</span>' : ''}
      <svg class="check" viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg></button>`;
  el.modelMenu.innerHTML = (on.length ? '<div class="mm-group"><span class="dot on"></span>Ready</div>' + on.map(item).join('') : '<div class="mm-group"><span class="dot off"></span>No model is running</div>') +
    (off.length ? '<div class="mm-group"><span class="dot off"></span>Not loaded</div>' + off.map(item).join('') : '') +
    (isMaster() ? `<button class="mm-manage" data-manage>Manage models &amp; VRAM <kbd>Ctrl+M</kbd></button>` : `<div class="mm-group">${auth.limits ? 'Models your account may use' : 'Only running models are listed'}</div>`);
  updateHint();
}
el.modelBtn.onclick = e => { e.stopPropagation(); el.modelPicker.classList.toggle('open'); };
document.addEventListener('click', e => { if (!el.modelPicker.contains(e.target)) el.modelPicker.classList.remove('open'); });
el.modelMenu.onclick = e => {
  if (e.target.closest('[data-manage]')) { el.modelPicker.classList.remove('open'); return openSheet('models'); }
  const b = e.target.closest('.mm-item'); if (!b) return;
  el.modelPicker.classList.remove('open');
  const o = modelOptions().find(x => x.backend === b.dataset.b && x.id === b.dataset.id); if (!o) return;
  if (o.online) return useModel(o);
  if (!isMaster()) return toast('That model isn’t running — ask the owner to start it', 'bad');
  S.model = { backend: o.backend, id: o.id }; saveSettings();
  if (o.backend === 'engine') toggleEngine(true, o.id); else toggleLM(o.id, true);
};

/* ---- jobs ---- */
let job = { state: 'idle', id: 0 }, seenJob = 0;
async function startJob(body) {
  try {
    const r = await api('/api/jobs', 'POST', body); job = r.job; seenJob = job.id; renderJob(); renderModels(); schedulePoll(400); return true;
  } catch (ex) {
    if (ex.data && ex.data.code === 'engine_running') {
      const cur = engineOn(); const nm = cur ? cur.short : 'engine model';
      const ok = await confirmModal(`Stop the ${nm} first?`, `The ${nm} (RDNA4 engine) is using most of the GPU memory. Stop it before loading LM Studio models?`, `Stop ${nm}`, 'thinking');
      if (ok) return startJob({ action: 'engine_stop' });
    } else toast(ex.message, 'bad');
    return false;
  }
}
function engineList() { return (models && models.engines) || []; }
function engineOn() { return engineList().find(e => e.online) || null; }
async function toggleEngine(on, id) {
  const em = engineList().find(e => e.id === id || e.key === id) || engineList()[0]; if (!em) return;
  if (on) {
    const cur = engineOn();
    const lmLoaded = (models && models.lmstudio.models || []).filter(m => m.loaded).map(m => m.name);
    const lmTxt = lmLoaded.length ? `All LM Studio models get unloaded (${lmLoaded.join(', ')}). ` : '';
    const ok = cur && cur.id !== em.id
      ? await confirmModal(`Switch to ${em.name.split(' · ')[0]}?`, `Only one engine model runs at a time: this stops the ${cur.short} and starts the ${em.short} (~${em.vram_gb} GB of VRAM). ${lmTxt}`, `Switch to ${em.short}`, 'thinking')
      : await confirmModal(`Start ${em.name.split(' · ')[0]}?`, `It needs ~${em.vram_gb} GB of VRAM. ${lmTxt || 'LM Studio models get unloaded first. '}Turning it off later won't reload them — switch them back on here when you need them.`, `Start ${em.short}`, 'thinking');
    if (ok) startJob({ action: 'engine_start', key: em.key });
  } else {
    if (await confirmModal(`Stop the ${em.short}?`, `Frees ~${em.vram_gb} GB of VRAM. LM Studio models stay unloaded until you switch them on.`, 'Stop', 'idle')) startJob({ action: 'engine_stop' });
  }
  renderModels();
}
async function toggleLM(key, on) {
  const m = (models.lmstudio.models || []).find(x => x.key === key); if (!m) return;
  if (on) {
    if (models.engine.online) return startJob({ action: 'lm_load', key });
    if (vram && vram.total_mb && vram.used_mb != null && m.size && vram.used_mb + m.size / 1048576 > vram.total_mb * 0.97) {
      if (!await confirmModal('This may not fit in VRAM', `${m.name} needs ~${GB(m.size)} and ${fmtMB(vram.total_mb - vram.used_mb)} is free. It will spill into shared memory and run much slower.`, 'Load anyway', 'thinking')) return;
    }
    startJob({ action: 'lm_load', key });
  } else {
    startJob({ action: 'lm_unload', key });
  }
}
function renderJob() {
  const chip = $('#jobChip'), run = job.state === 'running';
  chip.hidden = !run;
  if (run) { $('#jobChipText').textContent = job.label; $('#jobChipBar').style.width = Math.min(95, 100 * job.elapsed / (job.expect || 30)) + '%'; }
  if (job.id && job.id !== seenJob && job.state === 'running') seenJob = job.id;
  if (job.id === seenJob && job.state !== 'running' && job._toasted !== job.id && job.state !== 'idle') {
    job._toasted = job.id; seenJob = -1;
    if (job.state === 'done') {
      toast(job.label.replace(/^(Starting|Stopping|Loading|Unloading|Switching)/, m => ({ Starting: 'Started', Stopping: 'Stopped', Loading: 'Loaded', Unloading: 'Unloaded', Switching: 'Switched' })[m]).replace(/ \((unloads LM Studio models|stops the [^)]*)\)/, ''), 'ok');
      setMood(brandAv, 'done', 1400);
      if (job.kind === 'engine_start') { const o = modelOptions().find(x => x.backend === 'engine' && (x.id === job.target || !job.target) && x.online) || modelOptions().find(x => x.backend === 'engine' && x.id === job.target); if (o) useModel(o, true); }
      if (job.kind === 'lm_load' && S.model && S.model.backend === 'lmstudio') renderPicker();
    } else if (job.state === 'failed') { toast('Failed: ' + (job.error || job.label), 'bad'); setMood(brandAv, 'error', 2000); }
  }
}
let pollT = null, vramT = null, listT = null;
function schedulePoll(ms) { clearTimeout(pollT); pollT = setTimeout(pollModels, ms); }
async function pollModels() {
  try {
    models = await api('/api/models'); const prev = job.state; job = Object.assign(job, models.job);
    renderJob(); renderPicker(); renderEffort(); if (sheetOpen === 'models') renderModels();
    if (prev === 'running' && job.state !== 'running') setTimeout(refreshVram, 1500);
  } catch { }
  schedulePoll(job.state === 'running' ? 1200 : sheetOpen === 'models' ? 3000 : 9000);
}
async function refreshVram() {
  clearTimeout(vramT);
  if (!isMaster()) return;
  if (document.visibilityState === 'visible') { try { vram = await api('/api/vram'); renderVram(); } catch { } }
  vramT = setTimeout(refreshVram, sheetOpen === 'models' ? 2500 : 6000);
}
function stopPolls() { clearTimeout(pollT); clearTimeout(vramT); clearInterval(listT); }
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && auth.authed) { refreshVram(); refreshList(); schedulePoll(100); } });
function renderVram() {
  const v = vram || {}, mini = $('#vramMini');
  if (!v.available) { $('#vmText').textContent = 'VRAM: n/a'; return; }
  if (v.pending || v.used_mb == null) { $('#vmText').textContent = 'VRAM: reading…'; }
  else {
    const t = v.total_mb || 16304, p = Math.min(100, 100 * v.used_mb / t);
    $('#vmFill').style.width = p + '%';
    $('#vmShared').style.left = p + '%'; $('#vmShared').style.width = (v.shared_mb > 400 && p > 92 ? Math.min(100 - p + 4, 6) : 0) + '%';
    $('#vmText').textContent = `VRAM ${(v.used_mb / 1024).toFixed(1)} / ${(t / 1024).toFixed(1)} GB`;
    mini.classList.toggle('hot', p > 92);
    mini.title = `${v.gpu || 'GPU'} — dedicated ${fmtMB(v.used_mb)} of ${fmtMB(t)}, shared ${fmtMB(v.shared_mb)}. Click for details.`;
  }
  if (sheetOpen === 'models') renderModels();
}
$('#vramMini').onclick = () => openSheet('models');
const PCOL = ['var(--a1)', 'var(--a2)', 'var(--a3)', '#3ddc97', '#4f8bff', '#c084fc', '#f472b6', '#94a3b8'];
function pname(n) { const map = { 'ie-serve': 'RDNA4 engine (ie-serve)', 'llama-server': 'LM Studio models', 'LM Studio': 'LM Studio app', 'llmworker': 'LM Studio model', 'dwm': 'Windows desktop (dwm)', 'msedge': 'Edge', 'chrome': 'Chrome' }; return map[n] || n; }
function vramCard() {
  const v = vram || {};
  if (!v.available) return `<div class="card vram-big"><div class="vb-top"><b>GPU memory</b></div><p class="note">VRAM readings need Windows performance counters (not available).</p></div>`;
  if (v.pending || v.used_mb == null) return `<div class="card vram-big"><div class="vb-top"><b>GPU memory</b><small>${esc(v.gpu || '')}</small></div><div class="skel" style="height:14px;margin:12px 0"></div><div class="skel" style="height:60px"></div></div>`;
  const t = v.total_mb || 16304; const procs = (v.procs || []).filter(p => p.dedicated_mb > 40);
  let rest = v.used_mb - procs.reduce((a, p) => a + p.dedicated_mb, 0); if (rest < 0) rest = 0;
  const bar = procs.map((p, i) => `<i style="width:${100 * p.dedicated_mb / t}%;background:${PCOL[i % 8]}" title="${esc(pname(p.name))}"></i>`).join('') + (rest > 30 ? `<i style="width:${100 * rest / t}%;background:var(--text3)"></i>` : '');
  const rows = procs.map((p, i) => `<span><i class="sw" style="background:${PCOL[i % 8]}"></i>${esc(pname(p.name))}</span><span>${fmtMB(p.dedicated_mb)}</span><span>${p.shared_mb > 50 ? fmtMB(p.shared_mb) : '—'}</span>`).join('');
  const free = t - v.used_mb;
  return `<div class="card vram-big"><div class="vb-top"><b>${(v.used_mb / 1024).toFixed(1)} <small>/ ${(t / 1024).toFixed(1)} GB used</small></b><small>${esc(v.gpu || '')}</small></div>
    <div class="vb-bar">${bar}</div>
    <div class="vb-legend"><span class="hd">Process</span><span class="hd">VRAM</span><span class="hd">Shared</span>${rows}
      ${rest > 30 ? `<span><i class="sw" style="background:var(--text3)"></i>Other / system</span><span>${fmtMB(rest)}</span><span></span>` : ''}
      <span><i class="sw" style="background:var(--line2)"></i>Free</span><span>${fmtMB(free)}</span><span></span></div>
    ${v.shared_mb > 1500 && free < 600 ? '<p class="note warn" style="margin-top:8px">⚠ VRAM is full and spilling into shared system memory — generation will be slow.</p>' : ''}</div>`;
}
function jobBanner() {
  if (job.state === 'running') return `<div class="job-banner"><div class="jb-top"><span class="spin"></span>${esc(job.label)}<span style="margin-left:auto;font-weight:400;color:var(--text3)">${Math.round(job.elapsed)}s</span></div>
    <div class="pbar"><i style="width:${Math.min(95, 100 * job.elapsed / (job.expect || 30))}%"></i></div>${job.last ? `<small>${esc(job.last)}</small>` : ''}</div>`;
  if (job.state === 'failed' && job.ended && Date.now() / 1000 - job.ended < 120) return `<div class="job-banner failed"><div class="jb-top">⚠ ${esc(job.label)} failed</div><small>${esc(job.error)}</small></div>`;
  return '';
}
function renderModels() {
  const body = $('#modelsBody'); if (!body) return;
  if (!models) { body.innerHTML = vramCard() + '<div class="skel" style="height:90px"></div><div class="skel" style="height:90px"></div>'; return; }
  const run = job.state === 'running', e = models.engine, s = selModel();
  const busy = k => run && ((k.startsWith('engine:') && /^engine_/.test(job.kind) && (!job.target || job.target === k.slice(7) || (job.kind === 'engine_start' && (engineOn() || {}).id === k.slice(7)))) || (job.kind && job.kind.startsWith('lm_') && job.label.includes(k)));
  const tg = (on, attrs, b) => `<button class="tg${on ? ' on' : ''}${b ? ' busy' : ''}" role="switch" aria-checked="${on}" ${attrs}${run ? ' disabled' : ''}></button>`;
  let h = vramCard() + jobBanner();
  const engs = engineList(), anyOn = engineOn();
  h += `<div class="sec-title">RDNA4 engine <small style="font-weight:400;opacity:.7">· one model at a time</small></div>`;
  for (const em of engs) {
    const inUse = s && s.backend === 'engine' && s.id === em.id;
    h += `<div class="card${inUse ? ' hl' : ''}"><div class="card-row"><div class="nm"><b>${esc(em.name)}</b><small>${em.online ? '● Online · ' + esc(em.speed) : '○ Off'} · ctx 8K · MTP · vision</small></div>
    ${tg(em.online, `data-eng="${esc(em.key)}"`, busy('engine:' + em.id))}</div>
    <div class="tags"><span class="tag">Uncensored</span><span class="tag">Thinking: Off/Low/Med/High</span><span class="tag">~${em.vram_gb} GB VRAM</span></div>
    ${!em.online ? `<div class="warn">${anyOn ? `Turning it on stops the ${esc(anyOn.short)} first (one engine model at a time). ` : ''}LM Studio models get unloaded to free VRAM and aren’t reloaded automatically when it’s turned off.</div>` : ''}
    <div class="acts">${em.online && !inUse ? `<button class="btn-sm primary" data-use="engine:${esc(em.id)}">Use for chat</button>` : ''}${em.online && inUse ? '<span class="status">✓ In use for chat</span>' : ''}</div></div>`;
  }
  h += `<div class="sec-title">LM Studio ${models.lmstudio.online ? '' : '<span style="color:#ff8095">· offline</span>'}</div>`;
  if (!models.lmstudio.online) h += '<div class="card"><p class="note">LM Studio’s server isn’t reachable on port 1234. Open LM Studio and start the server (Developer › Status: Running).</p></div>';
  for (const m of models.lmstudio.models || []) {
    const emb = /embed/.test(m.type || '') || /embed/.test(m.key), active = s && s.backend === 'lmstudio' && s.id === m.key;
    const r = m.reasoning || [];
    h += `<div class="card${active ? ' hl' : ''}"><div class="card-row"><div class="nm"><b>${esc(m.name)}</b><small>${m.loaded ? '● Loaded' : '○ Not loaded'} · ${esc([m.params, m.quant].filter(Boolean).join(' · '))}${m.size ? ' · ' + GB(m.size) : ''}${m.loaded && m.context ? ' · ctx ' + Math.round(m.context / 1024) + 'K' : ''}</small></div>
      ${tg(m.loaded, `data-lm="${esc(m.key)}"`, busy(m.name))}</div>
      <div class="tags">${emb ? '<span class="tag">Embeddings</span>' : ''}${m.vision ? '<span class="tag">Vision</span>' : ''}${r.includes('off') ? '<span class="tag">Thinking: on/off</span>' : (!emb ? '<span class="tag">No thinking</span>' : '')}</div>
      ${!emb && m.loaded ? `<div class="acts">${active ? '<span class="status">✓ In use for chat</span>' : `<button class="btn-sm primary" data-use="${esc(m.key)}">Use for chat</button>`}</div>` : ''}</div>`;
  }
  h += `<p class="note">Only one model task runs at a time. Loading several chat models at once can overflow the 16 GB and get slow.</p>`;
  if (body._h !== h) { body._h = h; body.innerHTML = h; }
}
$('#modelsBody').addEventListener('click', e => {
  const t = e.target.closest('button'); if (!t || t.disabled) return;
  if (t.hasAttribute('data-eng')) return toggleEngine(!t.classList.contains('on'), t.dataset.eng);
  if (t.dataset.lm) return toggleLM(t.dataset.lm, !t.classList.contains('on'));
  if (t.dataset.use) { const u = t.dataset.use, o = modelOptions().find(x => u.startsWith('engine:') ? x.backend === 'engine' && x.id === u.slice(7) : x.backend === 'lmstudio' && x.id === u); if (o) { useModel(o); renderModels(); if (narrow()) closeSheets(); } return; }
});

/* ================= effort ================= */
const EFF = ['off', 'low', 'medium', 'high'];
const EFF_LABEL = { off: 'Off', low: 'Low', medium: 'Medium', high: 'High' };
const ENGINE_EFF = { off: { tok: 2048 }, low: { re: 'low', budget: 768, tok: 3072 }, medium: { re: 'medium', budget: 2048, tok: 4096 }, high: { re: 'xhigh', tok: 6144 } };
function effortFor(s) {
  const caps = s ? s.think : 'none';
  let e = S.effort;
  if (caps === 'none') return { e: null, caps };
  if (caps === 'on' && e === 'off') e = 'medium';
  return { e, caps };
}
const EFF_SHORT = { off: 'Off', low: 'Low', medium: 'Med', high: 'High' };
const slider = $('#effortSlider');
function effortMin(caps) { return caps === 'on' ? 1 : 0; }
function placeThumb(pos, dragging) { // pos: 0..3 (fractional while dragging)
  const pct = (pos / 3) * 100;
  slider.classList.toggle('dragging', !!dragging);
  $('#esThumb').style.left = pct + '%'; $('#esFill').style.width = pct + '%';
  const near = Math.round(pos);
  $$('.es-stop', slider).forEach((d, i) => d.classList.toggle('on', i <= near));
  $$('.es-labels button', slider).forEach((b, i) => b.classList.toggle('on', i === near));
  $('#esBubble').textContent = EFF_SHORT[EFF[near]];
}
function renderEffort() {
  const s = selModel(), { e, caps } = effortFor(s), wrap = $('#effort'), off = caps === 'none';
  wrap.classList.toggle('disabled', off);
  slider.setAttribute('aria-disabled', off); slider.tabIndex = off ? -1 : 0;
  if (off && document.activeElement === slider) slider.blur();
  const min = effortMin(caps);
  $$('.es-labels button', slider).forEach((b, i) => { b.disabled = off || i < min; });
  const i = off ? 0 : EFF.indexOf(e);
  if (!slider.classList.contains('dragging')) placeThumb(i);
  slider.dataset.level = off ? 'none' : e;
  slider.setAttribute('aria-valuenow', i); slider.setAttribute('aria-valuemin', min);
  slider.setAttribute('aria-valuetext', off ? 'Not available for this model' : EFF_LABEL[e]);
  const note = $('#effortNote');
  if (!s) note.textContent = '';
  else if (off) note.textContent = `${s.label} is an instruct model — no step-by-step thinking`;
  else if (caps === 'full') note.textContent = { off: 'Answers straight away', low: 'Quick think · ≤768 tokens', medium: 'Thinks · ≤2K tokens', high: 'Thinks as long as it needs' }[e];
  else if (caps === 'binary') note.textContent = e === 'off' ? 'Thinking off' : 'LM Studio: thinking is on/off only — level sets the reply budget';
  else note.textContent = 'This model always thinks';
}
function setEffort(level, quiet) {
  const s = selModel(), { caps } = effortFor(s);
  if (caps === 'none') return false;
  const i = Math.max(effortMin(caps), Math.min(3, typeof level === 'number' ? level : EFF.indexOf(level)));
  const changed = S.effort !== EFF[i];
  S.effort = EFF[i]; saveSettings(); renderEffort();
  if (changed && !quiet) { slider.classList.remove('pulse'); void slider.offsetWidth; slider.classList.add('pulse'); }
  return true;
}
(() => { // pointer drag with snapping
  let drag = null;
  const posFrom = x => { const r = $('.es-rail', slider).getBoundingClientRect(); return Math.max(0, Math.min(3, ((x - r.left) / r.width) * 3)); };
  slider.addEventListener('pointerdown', ev => {
    if (slider.getAttribute('aria-disabled') === 'true' || ev.button > 0) return;
    const lb = ev.target.closest('.es-labels button'); if (lb) { if (!lb.disabled) setEffort(lb.dataset.e); return; }
    ev.preventDefault(); slider.focus({ preventScroll: true });
    drag = { id: ev.pointerId }; slider.setPointerCapture(ev.pointerId);
    placeThumb(posFrom(ev.clientX), true);
  });
  slider.addEventListener('pointermove', ev => { if (drag && ev.pointerId === drag.id) placeThumb(posFrom(ev.clientX), true); });
  const end = ev => {
    if (!drag || ev.pointerId !== drag.id) return;
    const p = posFrom(ev.clientX); drag = null; slider.classList.remove('dragging');
    if (!setEffort(Math.round(p))) renderEffort();
  };
  slider.addEventListener('pointerup', end); slider.addEventListener('pointercancel', end);
  slider.addEventListener('keydown', ev => {
    const i = EFF.indexOf(S.effort), k = ev.key;
    const to = { ArrowLeft: i - 1, ArrowDown: i - 1, ArrowRight: i + 1, ArrowUp: i + 1, Home: 0, End: 3, PageDown: i - 1, PageUp: i + 1 }[k];
    if (to === undefined) return; ev.preventDefault(); setEffort(Math.max(0, Math.min(3, to)));
  });
})();
addEventListener('resize', () => requestAnimationFrame(renderEffort));

/* ================= tools ================= */
let availTools = [];
let availMemories = [];
async function loadTools() {
  try { const r = await api('/api/tools'); availTools = r.tools || []; }
  catch { availTools = []; }
}
async function loadMemories() {
  if (auth.user && auth.user.tier === 'limited') { availMemories = []; return; }
  try { const r = await api('/api/memory'); availMemories = r.memories || []; }
  catch { availMemories = []; }
}
function toolMeta(name) { return availTools.find(t => t.name === name) || null; }

function activeTools() {
  if (!S.toolsEnabled) return [];
  const tier = (auth.user && auth.user.tier) || 'master';
  if (tier === 'limited') return [];
  const dis = new Set(S.disabledTools || []);
  return availTools.filter(t => !t.unavailable && !dis.has(t.name)).map(t => t.schema);
}

function fitEngineBudget(messages, tools) {
  const toolLen = tools.length ? JSON.stringify(tools).length : 0;
  const estOf = arr => Math.ceil((JSON.stringify(arr).replace(/data:image[^"]+/g, 'x'.repeat(1200)).length + toolLen) / 3.2);
  let out = messages.slice();
  if (estOf(out) <= 6400) return { messages: out, est: estOf(out) };
  const head = out.length && out[0].role === 'system' ? [out[0]] : [];
  let tail = out.slice(head.length);
  while (tail.length > 1 && estOf([...head, ...tail]) > 6400) {
    // drop the oldest message (and any orphaned tool replies immediately following an assistant tool_call)
    const dropped = tail.shift();
    if (dropped && dropped.role === 'assistant' && dropped.tool_calls) {
      while (tail.length > 1 && tail[0].role === 'tool') tail.shift();
    }
  }
  out = [...head, ...tail];
  return { messages: out, est: estOf(out) };
}

function buildRequest(model, messages, opts) {
  const { e, caps } = effortFor(model);
  const tools = opts && opts.noTools ? [] : activeTools();
  let msgs = messages, est = 0;
  if (model.backend === 'engine') {
    const fitted = fitEngineBudget(messages, tools);
    msgs = fitted.messages; est = fitted.est;
  }
  const body = { model: model.id, messages: msgs, stream: true, stream_options: { include_usage: true } };
  if (tools.length) body.tools = tools;
  let tok = 4096, thinking = !!e && e !== 'off';
  if (model.backend === 'engine') {
    const x = ENGINE_EFF[e || 'medium']; tok = x.tok;
    if (e === 'off') body.chat_template_kwargs = { enable_thinking: false };
    else { body.reasoning_effort = x.re; if (x.budget) body.reasoning_budget = x.budget; }
  } else {
    if (caps === 'binary' && e === 'off') body.reasoning_effort = 'none';
    tok = { off: 2048, low: 2048, medium: 4096, high: 6144 }[e || 'medium'];
    if (caps === 'none') { tok = 2048; thinking = false; }
  }
  if (S.maxTokens > 0) tok = S.maxTokens;
  if (model.backend === 'engine') { // keep prompt + reply inside the engine's 8K context
    tok = Math.max(512, Math.min(tok, 8192 - est - 64));
  }
  body.max_tokens = auth.limits ? Math.min(tok, auth.limits.max_tokens) : tok;
  if (S.tempMode === 'manual') body.temperature = +S.temperature;
  else if (model.backend !== 'engine') body.temperature = thinking ? 0.6 : 0.7; // engine picks Qwen's own presets when omitted
  return { body, effort: e };
}

/* ================= rendering chat ================= */
const CHEV = '<svg class="chev" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>';
function renderChat(smooth, keepScroll) {
  const c = cur(), top = el.thread.scrollTop;
  el.msgs.innerHTML = '';
  el.empty.classList.toggle('gone', !!(c && c.messages.length));
  if (!c) { setMood(heroAv, 'idle'); updateHint(); return; }
  c.messages.forEach((m, i) => el.msgs.appendChild(m.role === 'user' ? userEl(m) : (m.role === 'tool' ? toolEl(m) : botEl(m, i === c.messages.length - 1))));
  requestAnimationFrame(() => {
    if (keepScroll && !stick) { el.thread.scrollTop = top; return; }
    el.thread.scrollTo({ top: el.thread.scrollHeight, behavior: smooth && !reduced() ? 'smooth' : 'auto' }); stick = true;
  });
}
function userEl(m) {
  const d = document.createElement('div'); d.className = 'msg user';
  const imgs = (m.images || []).map(u => `<img src="${esc(u)}" alt="attached image">`).join('');
  d.innerHTML = `<div class="col">${imgs ? `<div class="imgs">${imgs}</div>` : ''}${m.imagesDropped ? '<div class="stat">image removed from history</div>' : ''}${m.content ? `<div class="bubble">${esc(m.content)}</div>` : ''}</div>`;
  return d;
}
function toolEl(m) {
  const d = document.createElement('div'); d.className = 'msg tool-msg';
  const isErr = !!m.error;
  const meta = toolMeta(m.name);
  const label = meta ? meta.label : (m.name || 'tool');
  let preview = (m.content || '').replace(/\s+/g, ' ').slice(0, 60);
  const imgs = (m.images || []).map(u => `<img src="${esc(u)}" alt="tool output">`).join('');
  d.innerHTML = `<div class="body">
    <details class="tool-box"${isErr || imgs ? ' open' : ''}>
      <summary>
        <span class="tool-badge ${isErr ? 'error' : 'result'}">${isErr ? 'Error' : 'Result'}</span>
        <span class="tool-name">${esc(label)}</span>
        <span class="tool-preview">${esc(preview)}</span>
        ${CHEV}
      </summary>
      <div class="tool-body">${esc(m.content || '(empty result)')}</div>
      ${imgs ? `<div class="tool-imgs">${imgs}</div>` : ''}
    </details></div>`;
  return d;
}
function botEl(m, isLast) {
  const d = document.createElement('div'); d.className = 'msg bot' + (m.streaming ? '' : ' done');
  d.innerHTML = `<div class="side"><div class="avatar-slot sm"></div></div><div class="body">
    <div class="who"><b>Mochi</b><span class="mdl">${esc(m.modelLabel || '')}</span></div>
    <details class="think" hidden><summary><span class="lbl">Thinking</span><span class="tsec"></span>${CHEV}</summary><div class="tbody"></div></details>
    <div class="tool-calls-box"></div>
    <div class="content"></div><div class="errbox"></div>
    <div class="meta"></div></div>`;
  d._av = mountAvatar($('.avatar-slot', d));
  fillBot(d, m, isLast);
  return d;
}
function fillBot(d, m, isLast) {
  const { reasoning, content } = splitThink(m.content, m.reasoning);
  const th = $('.think', d);
  if (reasoning) {
    th.hidden = false; $('.tbody', th).textContent = reasoning;
    const live = m.streaming && !content;
    th.classList.toggle('live', live);
    $('.lbl', th).textContent = live ? 'Thinking…' : 'Thought process';
    $('.tsec', th).textContent = m.thinkSecs ? ` · ${m.thinkSecs.toFixed(1)}s` : '';
    if (live && !th._userToggled) th.open = true;
    if (!live && th.open && !th._userToggled && m.streaming) th.open = false;
  }
  const tcb = $('.tool-calls-box', d);
  if (tcb) {
    if (m.tool_calls && m.tool_calls.length) {
      tcb.innerHTML = m.tool_calls.map(tc => {
        const fn = tc.function || {};
        let argPrev = (fn.arguments || '').replace(/\s+/g, ' ').slice(0, 60);
        return `<details class="tool-box">
          <summary>
            <span class="tool-badge call">Call</span>
            <span class="tool-name">${esc(fn.name || 'function')}</span>
            <span class="tool-preview">${esc(argPrev)}</span>
            ${CHEV}
          </summary>
          <div class="tool-body">${esc(fn.arguments || '{}')}</div>
        </details>`;
      }).join('');
    } else {
      tcb.innerHTML = '';
    }
  }
  const html = md(content);
  d.classList.toggle('streaming', !!m.streaming);
  $('.content', d).innerHTML = m.streaming ? (content ? withCaret(html) : (reasoning || (m.tool_calls && m.tool_calls.length) ? '' : '<div class="typing"><i></i><i></i><i></i></div>')) : html;
  $('.errbox', d).innerHTML = m.error ? `<div class="err">${esc(m.error)}</div>` : '';
  if (!m.streaming) {
    const s = m.stats || {}; let meta = '';
    if (S.showStats) {
      if (m.effort) meta += `<span class="stat">effort <b>${EFF_LABEL[m.effort] || m.effort}</b></span>`;
      if (s.ttft != null) meta += `<span class="stat">TTFT <b>${s.ttft.toFixed(2)}s</b></span>`;
      if (s.tps) meta += `<span class="stat"><b>${s.tps.toFixed(1)}</b> tok/s</span>`;
      if (s.tokens) meta += `<span class="stat"><b>${s.tokens}</b> tokens${s.estimated ? '~' : ''}</span>`;
    }
    meta += `<button class="act" data-act="copy" title="Copy reply">${ICON.copy}</button>`;
    if (isLast) meta += `<button class="act" data-act="regen" title="Regenerate (Ctrl+Shift+R)">${ICON.regen}</button>`;
    $('.meta', d).innerHTML = meta; d.classList.add('done');
  }
}
el.msgs.addEventListener('click', async e => {
  const cp = e.target.closest('[data-copy]');
  if (cp) { const code = cp.closest('.code').querySelector('code').textContent; await copyText(code); flash(cp, '<span>Copied!</span>'); return; }
  const a = e.target.closest('.act');
  if (a && a.dataset.act === 'copy') { const i = [...el.msgs.children].indexOf(a.closest('.msg')); const m = cur().messages[i]; await copyText(splitThink(m.content, m.reasoning).content); a.classList.add('ok'); setTimeout(() => a.classList.remove('ok'), 1200); toast('Reply copied', 'ok'); return; }
  if (a && a.dataset.act === 'regen') return regenerate();
  const img = e.target.closest('.imgs img, .tool-imgs img'); if (img) lightbox(img.src);
  const sum = e.target.closest('.think summary'); if (sum) sum.parentElement._userToggled = true;
});
function flash(btn, html) { const old = btn.innerHTML; btn.classList.add('done'); btn.innerHTML = COPY_ICON + html; setTimeout(() => { btn.innerHTML = old; btn.classList.remove('done'); }, 1400); }
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); }
  catch { const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
}
function lightbox(src) { const d = document.createElement('div'); d.className = 'lightbox'; const i = document.createElement('img'); i.src = src; d.appendChild(i); d.onclick = () => d.remove(); document.body.appendChild(d); }

/* ---- scrolling ---- */
el.thread.addEventListener('scroll', () => {
  const gap = el.thread.scrollHeight - el.thread.scrollTop - el.thread.clientHeight;
  stick = gap < 90; el.toBottom.classList.toggle('show', gap > 300);
}, { passive: true });
el.toBottom.onclick = () => { el.thread.scrollTo({ top: el.thread.scrollHeight, behavior: 'smooth' }); stick = true; };
const followBottom = () => { if (stick) el.thread.scrollTop = el.thread.scrollHeight; };

/* ---- composer & images ---- */
function autosize() { el.input.style.height = 'auto'; el.input.style.height = Math.min(el.input.scrollHeight, 240) + 'px'; updateSend(); }
el.input.addEventListener('input', autosize);
el.input.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing) return;
  const touch = matchMedia('(hover: none)').matches;
  const sendIt = S.sendOnEnter && !touch ? !e.shiftKey : (e.ctrlKey || e.metaKey);
  if (sendIt) { e.preventDefault(); if (!gen) send(); }
});
function updateSend() {
  el.send.classList.toggle('stop', !!gen);
  el.send.title = gen ? 'Stop generating (Esc)' : 'Send';
  el.send.disabled = !gen && !(el.input.value.trim() || attachments.length);
}
el.send.onclick = () => gen ? stopGen() : send();
function updateHint() {
  const s = selModel();
  el.hint.classList.remove('warn');
  if (attachments.length && s && !s.vision) { el.hint.textContent = `${s.label} can't see images — pick a vision model (an engine model or a “vision” LM Studio model)`; el.hint.classList.add('warn'); }
  else if (!s || !s.online) { el.hint.textContent = models ? 'No chat model is running — open Models to turn one on' : 'Connecting…'; el.hint.classList.add('warn'); }
  else el.hint.textContent = (S.sendOnEnter ? 'Enter to send · Shift+Enter for a new line' : 'Ctrl+Enter to send · Enter for a new line') + ' · paste or drop images';
}
$('#attachBtn').onclick = () => el.file.click();
function updateToolsBtn() {
  if (!el.toolsBtn) return;
  el.toolsBtn.classList.toggle('active', !!S.toolsEnabled);
  el.toolsBtn.title = S.toolsEnabled ? 'Tools enabled (click to toggle)' : 'Tools disabled (click to toggle)';
}
if (el.toolsBtn) {
  el.toolsBtn.onclick = () => {
    S.toolsEnabled = !S.toolsEnabled;
    saveSettings();
    updateToolsBtn();
    toast(S.toolsEnabled ? 'Tools enabled' : 'Tools disabled', 'ok');
  };
  updateToolsBtn();
}
el.file.onchange = () => { addFiles(el.file.files); el.file.value = ''; };
async function addFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue;
    if (attachments.length >= 6) { toast('Up to 6 images per message'); break; }
    try { attachments.push(await downscale(f)); } catch { toast('Could not read ' + f.name, 'bad'); }
  }
  renderAttach();
}
function downscale(file) {
  return new Promise((res, rej) => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      const max = 1600, k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      const png = c.toDataURL('image/png'); res(png.length < 1.5e6 ? png : c.toDataURL('image/jpeg', 0.9));
    };
    img.onerror = () => { URL.revokeObjectURL(url); rej(); }; img.src = url;
  });
}
function renderAttach() {
  el.attachRow.innerHTML = '';
  attachments.forEach((u, i) => {
    const t = document.createElement('div'); t.className = 'thumb';
    t.innerHTML = `<img src="${u}" alt=""><button title="Remove"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>`;
    $('button', t).onclick = () => { t.classList.add('out'); setTimeout(() => { attachments.splice(i, 1); renderAttach(); }, 230); };
    $('img', t).onclick = () => lightbox(u);
    el.attachRow.appendChild(t);
  });
  updateSend(); updateHint();
}
document.addEventListener('paste', e => {
  const files = [...(e.clipboardData && e.clipboardData.files || [])].filter(f => f.type.startsWith('image/'));
  if (files.length) { e.preventDefault(); addFiles(files); }
});
let dragN = 0;
addEventListener('dragenter', e => { if ([...e.dataTransfer.types].includes('Files')) { dragN++; el.drop.classList.add('show'); } });
addEventListener('dragleave', () => { if (--dragN <= 0) { dragN = 0; el.drop.classList.remove('show'); } });
addEventListener('dragover', e => e.preventDefault());
addEventListener('drop', e => { e.preventDefault(); dragN = 0; el.drop.classList.remove('show'); addFiles(e.dataTransfer.files); });
const CHIPS = [
  { t: '💡 Explain', p: 'Explain how MTP (multi-token prediction) speeds up LLM decoding, in simple terms.' },
  { t: '🐍 Code', p: 'Write a Python script that finds duplicate files in a folder by hash.' },
  { t: '✍️ Write', p: 'Draft a short, friendly message inviting friends to a weekend game night.' },
  { t: '🖼️ Look at an image', p: 'What is in this image?', attach: true }
];
$('#chips').innerHTML = CHIPS.map(c => `<button class="chip" data-p="${esc(c.p)}"${c.attach ? ' data-attach="1"' : ''}>${c.t}</button>`).join('');
$('#chips').onclick = e => {
  const c = e.target.closest('.chip'); if (!c) return;
  el.input.value = c.dataset.p; autosize(); el.input.focus();
  if (c.dataset.attach) { toast('Now attach or paste a picture 📎'); el.file.click(); } else send();
};

/* ================= generation ================= */
function apiMessages(msgs) {
  const out = [];
  let sp = sysPrompt().trim();
  const dis = new Set(S.disabledTools || []);
  if (availMemories.length && S.toolsEnabled && (!dis.has('remember') || !dis.has('recall'))) {
    let memTxt = '';
    for (const m of availMemories.slice(-20)) {
      const line = `\n- ${m.text}`;
      if (memTxt.length + line.length > 1400) break;
      memTxt += line;
    }
    if (memTxt) sp = (sp ? sp + '\n\n' : '') + 'Saved facts about the user:' + memTxt;
  }
  if (sp) out.push({ role: 'system', content: sp });
  for (const m of msgs) {
    if (m.role === 'user') {
      const imgs = m.images || [];
      out.push({ role: 'user', content: imgs.length ? [{ type: 'text', text: m.content || 'Describe this image.' }, ...imgs.map(u => ({ type: 'image_url', image_url: { url: u } }))] : m.content });
    } else if (m.role === 'tool') {
      out.push({ role: 'tool', tool_call_id: m.tool_call_id || '', name: m.name || '', content: m.content || '' });
    } else if (m.role === 'assistant') {
      const item = { role: 'assistant' };
      if (m.tool_calls && m.tool_calls.length) item.tool_calls = m.tool_calls;
      const t = splitThink(m.content || '', m.reasoning || '').content;
      if (t) item.content = t;
      else if (!m.tool_calls || !m.tool_calls.length) item.content = '';
      else item.content = null;
      out.push(item);
    }
  }
  return out;
}
function send() {
  const text = el.input.value.trim();
  if (!text && !attachments.length) return;
  const s = selModel();
  if (!s || !s.online) { toast('No chat model is running', 'bad', { label: 'Open Models', fn: () => openSheet('models') }); return; }
  if (attachments.length && !s.vision) { toast(`${s.label} can't see images`, 'bad'); return; }
  let c = cur();
  if (!c) { c = { id: uid(), title: '', created: Date.now(), updated: Date.now(), pinned: false, messages: [], rev: 0 }; chats[c.id] = c; currentId = c.id; localStorage.setItem(LS_CUR, c.id); }
  if (!c.title) c.title = (text || 'Image').replace(/\s+/g, ' ').slice(0, 48);
  const um = { role: 'user', content: text, images: attachments.slice() };
  c.messages.push(um); c.updated = Date.now();
  el.input.value = ''; attachments = []; renderAttach(); autosize();
  el.empty.classList.add('gone');
  el.msgs.appendChild(userEl(um));
  saveChat(c);
  stick = true; requestAnimationFrame(() => el.thread.scrollTo({ top: el.thread.scrollHeight, behavior: reduced() ? 'auto' : 'smooth' }));
  generate(c, s);
}
function regenerate() {
  const c = cur(); if (!c || gen) return;
  while (c.messages.length && (c.messages[c.messages.length - 1].role === 'assistant' || c.messages[c.messages.length - 1].role === 'tool')) {
    c.messages.pop();
    if (el.msgs.lastElementChild) el.msgs.lastElementChild.remove();
  }
  const s = selModel(); if (!s || !s.online) { toast('No chat model is running', 'bad'); return; }
  generate(c, s);
}
function stopGen() { if (gen) { gen.stopped = true; gen.ctrl.abort(); } }
async function streamOnce(c, model, opts) {
  const { body, effort } = buildRequest(model, apiMessages(c.messages), opts);
  const m = { role: 'assistant', content: '', reasoning: '', streaming: true, modelLabel: model.label + (model.backend === 'engine' ? ' · ' + (model.quant || 'IQ3_XS') : ''), effort: effort || undefined };
  c.messages.push(m);
  const d = botEl(m, true); el.msgs.appendChild(d);
  $$('[data-act=regen]', el.msgs).forEach(r => r.remove());
  const ctrl = new AbortController();
  gen = { ctrl, backend: model.backend, stopped: false, chat: c.id }; updateSend();
  setMood(d._av, 'thinking'); setMood(brandAv, 'thinking');
  const t0 = performance.now(); let tFirst = null, tLast = null, tContent = null, chunks = 0, usage = null, finish = null, dirty = false;
  const streamedToolCalls = {};
  const paint = () => { dirty = false; if (d.isConnected) { fillBot(d, m, true); followBottom(); } };
  const schedule = () => { if (!dirty) { dirty = true; requestAnimationFrame(paint); } };
  try {
    const r = await fetch(`/proxy/${model.backend}/v1/chat/completions`, { method: 'POST', headers: HDR, credentials: 'same-origin', body: JSON.stringify(body), signal: ctrl.signal });
    if (r.status === 401) { showAuth(); throw new Error('Signed out'); }
    if (!r.ok) { let t = await r.text(); try { const j = JSON.parse(t); t = (j.error && (j.error.message || j.error)) || t; } catch { } throw new Error(`${r.status} · ${String(t).slice(0, 300)}`); }
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = '';
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
        if (!line.startsWith('data:')) continue;
        const p = line.slice(5).trim(); if (p === '[DONE]') continue;
        let j; try { j = JSON.parse(p); } catch { continue; }
        if (j.error) throw new Error(j.error.message || JSON.stringify(j.error));
        if (j.usage) usage = j.usage;
        for (const ch of j.choices || []) {
          const dl = ch.delta || {}; if (ch.finish_reason) finish = ch.finish_reason;
          const rc = dl.reasoning_content || dl.reasoning || '', cc = dl.content || '';
          if (rc || cc) {
            const now = performance.now(); if (tFirst == null) tFirst = now; tLast = now; chunks++;
            m.reasoning += rc; m.content += cc;
            const split = splitThink(m.content, m.reasoning);
            if (split.content && tContent == null) { tContent = now; if (split.reasoning) m.thinkSecs = (now - tFirst) / 1000; setMood(d._av, 'talking'); setMood(brandAv, 'talking'); }
            schedule();
          }
          const tcList = ch.message?.tool_calls || dl.tool_calls;
          if (tcList) {
            const now = performance.now(); if (tFirst == null) tFirst = now; tLast = now; chunks++;
            for (const tc of tcList) {
              const idx = tc.index ?? 0;
              if (!streamedToolCalls[idx]) {
                streamedToolCalls[idx] = { id: tc.id || `call_${Date.now()}_${idx}`, type: 'function', name: tc.function?.name || '', arguments: tc.function?.arguments || '' };
              } else {
                if (tc.id) streamedToolCalls[idx].id = tc.id;
                if (tc.function?.name) streamedToolCalls[idx].name += tc.function.name;
                if (tc.function?.arguments) streamedToolCalls[idx].arguments += tc.function.arguments;
              }
            }
            m.tool_calls = Object.values(streamedToolCalls).map(tc => ({ id: tc.id, type: 'function', function: { name: tc.name, arguments: tc.arguments } }));
            schedule();
          }
        }
      }
    }
    if (finish === 'length') m.error = 'Reply hit the token limit — raise “Max reply tokens” in Settings › Chat, or lower the effort.';
    if (tFirst == null && !gen.stopped) throw new Error('The model returned an empty reply.');
    setMood(d._av, 'done', 1400); setMood(brandAv, 'done', 1400);
  } catch (e) {
    if (gen.stopped) { m.stoppedByUser = true; setMood(d._av, 'idle'); setMood(brandAv, 'idle'); }
    else { m.error = String(e.message || e).replace(/^TypeError: /, ''); if (/Failed to fetch|NetworkError|network error/i.test(m.error)) m.error = 'Lost connection to the local server.'; setMood(d._av, 'error', 2200); setMood(brandAv, 'error', 2200); }
  }
  const tokens = usage && usage.completion_tokens, span = tFirst != null && tLast > tFirst ? (tLast - tFirst) / 1000 : 0;
  m.stats = { ttft: tFirst != null ? (tFirst - t0) / 1000 : null, tokens: tokens || chunks || null, estimated: !tokens,
              tps: span > 0.05 ? ((tokens || chunks) - 1) / span : null, model: model.id, finish };
  if (m.stoppedByUser) m.stats.stopped = true;
  delete m.streaming; delete m.stoppedByUser; c.updated = Date.now(); gen = null;
  if (Object.keys(streamedToolCalls).length) {
    m.tool_calls = Object.values(streamedToolCalls).map(tc => ({ id: tc.id, type: 'function', function: { name: tc.name, arguments: tc.arguments } }));
  }
  if (d.isConnected) { fillBot(d, m, true); followBottom(); }
  updateSend(); saveChat(c);
  return { m, finish };
}
async function generate(c, model) {
  let round = 0;
  const maxRounds = S.maxToolRounds || 5;
  let hasDeclined = false;

  while (round < maxRounds) {
    const { m } = await streamOnce(c, model, { noTools: false });
    if (m.error || m.stats.stopped || !m.tool_calls || !m.tool_calls.length) break;

    round++;
    for (const tc of m.tool_calls) {
      const fn = tc.function || {};
      let argsObj = {};
      try { argsObj = JSON.parse(fn.arguments || '{}'); } catch { argsObj = { raw: fn.arguments }; }

      const meta = toolMeta(fn.name);
      const risk = meta ? meta.risk : (fn.name === 'run_python' ? 'host' : 'network');
      const mustAsk = risk === 'host' || (!S.toolsAutoExec && risk !== 'safe');
      let confirmed = false;

      if (mustAsk) {
        let title = `Run ${meta ? meta.label : fn.name}?`;
        let msg = '';
        let extra = '';
        if (fn.name === 'run_python') {
          title = 'Allow Run Python?';
          msg = 'Mochi wants to run this code in your sandboxed files folder (no internet, no other PC folders):';
          extra = `<pre class="modal-code">${esc(argsObj.code || JSON.stringify(argsObj, null, 2))}</pre>`;
        } else {
          msg = `Mochi wants to run "${fn.name}" with these arguments:`;
          extra = `<pre class="modal-code">${esc(JSON.stringify(argsObj, null, 2))}</pre>`;
        }
        const ok = await confirmModal(title, msg, 'Run', 'thinking', null, extra);
        if (!ok) {
          const toolMsg = { role: 'tool', tool_call_id: tc.id, name: fn.name, content: 'Tool execution was declined by user.', error: true };
          c.messages.push(toolMsg);
          el.msgs.appendChild(toolEl(toolMsg));
          hasDeclined = true;
          continue;
        }
        confirmed = true;
      }

      let toolRes = null, toolImgs = [];
      try {
        const resp = await api('/api/tools/execute', 'POST', { tool: fn.name, arguments: argsObj, confirmed });
        toolRes = resp.ok ? (resp.result != null ? resp.result : (resp.output != null ? resp.output : '(empty output)')) : { error: resp.error || 'Execution failed' };
        if (resp.images && resp.images.length) toolImgs = resp.images;
      } catch (err) {
        toolRes = { error: err.message || 'Execution error' };
      }
      if (fn.name === 'remember' || fn.name === 'forget') loadMemories();

      const resStr = typeof toolRes === 'string' ? toolRes : JSON.stringify(toolRes, null, 2);
      const isErr = toolRes && typeof toolRes === 'object' && !!toolRes.error;
      const toolMsg = { role: 'tool', tool_call_id: tc.id, name: fn.name, content: resStr, error: isErr };
      if (toolImgs.length) toolMsg.images = toolImgs;
      c.messages.push(toolMsg);
      el.msgs.appendChild(toolEl(toolMsg));
      followBottom();
    }

    saveChat(c);
    if (hasDeclined) break;
  }

  // If the max tool-round limit was reached right after pushing tool outputs, always give Mochi one final turn without tools to write an answer.
  const lastMsg = c.messages[c.messages.length - 1];
  if (round >= maxRounds && !hasDeclined && lastMsg && lastMsg.role === 'tool') {
    await streamOnce(c, model, { noTools: true });
  }
}

/* ================= sheets ================= */
let sheetOpen = null;
function openSheet(name, tab) {
  closeMenu(); el.modelPicker.classList.remove('open');
  $$('.sheet').forEach(s => { s.classList.remove('open'); s.setAttribute('aria-hidden', 'true'); });
  if (name === 'models' && !isMaster()) return;
  sheetOpen = name; const sh = $('#' + name + 'Sheet');
  sh.classList.add('open'); sh.setAttribute('aria-hidden', 'false'); $('#sheetScrim').classList.add('show');
  if (name === 'models' && !isMaster()) return;
  if (name === 'models') { renderModels(); schedulePoll(50); refreshVram(); }
  if (name === 'settings') showTab(tab || curTab);
}
function closeSheets() {
  $$('.sheet').forEach(s => { s.classList.remove('open'); s.setAttribute('aria-hidden', 'true'); s.style.transform = ''; });
  $('#sheetScrim').classList.remove('show'); sheetOpen = null;
}
$('#sheetScrim').onclick = closeSheets;
$$('[data-close]').forEach(b => b.onclick = closeSheets);
$('#openModels').onclick = () => openSheet('models');
$('#openSettings').onclick = $('#openSettings2').onclick = () => openSheet('settings');
// swipe down to close on phones
$$('.sheet').forEach(sh => {
  const head = $('.sheet-head', sh); let y0 = null, dy = 0;
  head.addEventListener('touchstart', e => { if (narrow()) { y0 = e.touches[0].clientY; dy = 0; sh.style.transition = 'none'; } }, { passive: true });
  head.addEventListener('touchmove', e => { if (y0 != null) { dy = Math.max(0, e.touches[0].clientY - y0); sh.style.transform = `translateY(${dy}px)`; } }, { passive: true });
  head.addEventListener('touchend', () => { if (y0 == null) return; sh.style.transition = ''; sh.style.transform = ''; if (dy > 90) closeSheets(); y0 = null; });
});

/* ================= settings tabs ================= */
let curTab = 'look';
$('#setTabs').onclick = e => { const b = e.target.closest('[data-tab]'); if (b) showTab(b.dataset.tab); };
const row = (label, sub, ctl) => `<div class="row"><div class="lb">${label}${sub ? `<small>${sub}</small>` : ''}</div>${ctl}</div>`;
const tgl = (key, on, extra = '') => `<button class="tg${on ? ' on' : ''}" role="switch" aria-checked="${!!on}" data-k="${key}" ${extra}></button>`;
const segc = (key, opts, val) => `<div class="seg full" data-seg="${key}">${opts.map(([v, l]) => `<button data-v="${v}" class="${String(v) === String(val) ? 'on' : ''}">${l}</button>`).join('')}</div>`;
function showTab(t) {
  curTab = t; $$('#setTabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  const body = $('#settingsBody'); body._h = null;
  body.innerHTML = `<div class="tabpane">${TABS[t]()}</div>`;
  if (TABS_AFTER[t]) TABS_AFTER[t](body);
  $$('.seg.full', body).forEach(s => { const on = $('.on', s); if (!$('.seg-pill', s)) { /* simple style for in-sheet segs */ } });
}
const TABS = {
  look: () => `
    <div class="sec-title">Theme</div>${segc('theme', [['dark', '🌙 Dark'], ['light', '☀️ Light'], ['system', '💻 System']], S.theme)}
    <div class="sec-title">Accent</div><div class="swatches">${Object.entries(ACCENTS).map(([k, c]) => `<button class="swatch${S.accent === k ? ' on' : ''}" data-acc="${k}" title="${k}" style="background:linear-gradient(135deg,${c[0]},${c[1]})"></button>`).join('')}
      <label class="swatch custom${S.accent === 'custom' ? ' on' : ''}" title="Custom colour"><input type="color" id="accCustom" value="${esc(S.customAccent)}"></label></div>
    <div class="sec-title">Text size · ${S.fontSize}px</div><input type="range" class="rng" min="13" max="19" step="1" value="${S.fontSize}" data-range="fontSize">
    <div class="sec-title">Density</div>${segc('density', [['compact', 'Compact'], ['comfy', 'Comfortable'], ['spacious', 'Spacious']], S.density)}
    <div class="sec-title">Chat width</div>${segc('width', [['narrow', 'Narrow'], ['normal', 'Normal'], ['wide', 'Wide']], S.width)}
    ${row('Animated background', 'The soft aurora behind everything', tgl('aurora', S.aurora))}
    <p class="note">Animations also calm down automatically when your device asks for reduced motion.</p>`,
  chat: () => {
    const o = modelOptions();
    return `
    <div class="sec-title">System prompt preset</div>
    <div class="presets">${(S.presets || []).map(p => `<div class="preset${p.id === S.presetId ? ' on' : ''}" data-preset="${esc(p.id)}"><div class="pt"><b>${esc(p.name)}</b><small>${esc(p.text || '(empty — model default behaviour)')}</small></div>
      <div class="pa"><button class="icon-btn" data-pedit="${esc(p.id)}" title="Edit">${ICON.edit}</button>${PRESETS0.some(x => x.id === p.id) ? '' : `<button class="icon-btn" data-pdel="${esc(p.id)}" title="Delete">${ICON.del}</button>`}</div></div>`).join('')}</div>
    <div id="presetEdit"></div>
    <button class="btn-sm" id="presetAdd">＋ New preset</button>
    <div class="sec-title">Sending</div>
    ${row('Send with Enter', 'Off: Ctrl+Enter sends, Enter adds a line. Phones always use the send button.', tgl('sendOnEnter', S.sendOnEnter))}
    ${row('Show speed stats', 'TTFT, tok/s and tokens under each reply', tgl('showStats', S.showStats))}
    <div class="sec-title">Default model</div>
    <div class="field"><select id="defModel"><option value="">Automatic</option>${o.map(x => `<option value="${x.backend}|${esc(x.id)}"${sameModel(x, S.defaultModel) ? ' selected' : ''}>${esc(x.label)}</option>`).join('')}</select>
      <p class="note">The engine model if one is running, otherwise a loaded LM Studio model.</p></div>
    <div class="sec-title">Temperature</div>${segc('tempMode', [['auto', 'Auto (Qwen presets)'], ['manual', 'Manual']], S.tempMode)}
    <div id="tempRow" ${S.tempMode === 'manual' ? '' : 'hidden'}>${row('Temperature', 'Lower = focused, higher = creative', `<b id="tempOut">${(+S.temperature).toFixed(2)}</b>`)}<input type="range" class="rng" min="0" max="1.5" step="0.05" value="${S.temperature}" data-range="temperature"></div>
    <div class="sec-title">Max reply tokens</div>
    ${segc('maxTokens', [[0, 'Auto'], [1024, '1K'], [2048, '2K'], [4096, '4K'], [8192, '8K']], S.maxTokens)}
    <p class="note">Auto: Off 2K · Low 3K · Medium 4K · High 6K. Engine models have an 8K context, so long chats get a smaller reply budget automatically.</p>
    <div class="sec-title">Tool use</div>
    ${row('Enable tools', 'Let Mochi search the web, read pages, do math, remember facts and run sandboxed Python', tgl('toolsEnabled', S.toolsEnabled))}
    ${row('Auto-run web & file tools', 'Safe tools (math, time, memory) always run automatically. Run Python always asks first.', tgl('toolsAutoExec', S.toolsAutoExec))}
    <div class="sec-title">Max tool rounds</div>
    ${segc('maxToolRounds', [[1, '1'], [3, '3'], [5, '5'], [10, '10']], S.maxToolRounds || 5)}
    ${(() => {
      const dis = new Set(S.disabledTools || []);
      const groups = [];
      for (const t of availTools) {
        let g = groups.find(x => x.name === t.group);
        if (!g) { g = { name: t.group || 'Tools', items: [] }; groups.push(g); }
        g.items.push(t);
      }
      const riskLbl = { safe: 'safe', network: 'web', files: 'files', host: 'asks' };
      const body = groups.length ? groups.map(g => `<div class="tool-grp-lbl">${esc(g.name)}</div><div class="tool-grid">${g.items.map(t => {
        const on = !t.unavailable && !dis.has(t.name);
        return `<label class="tool-item${t.unavailable ? ' unavail' : ''}" title="${esc(t.unavailable || t.schema.function.description)}">
          <input type="checkbox" data-tool-tgl="${esc(t.name)}" ${on ? 'checked' : ''} ${t.unavailable ? 'disabled' : ''}>
          <span>${esc(t.label)}</span>
          <i class="risk-tag ${esc(t.risk)}">${esc(riskLbl[t.risk] || t.risk)}</i>
        </label>`;
      }).join('')}</div>`).join('') : '<p class="note">No tools available for this account.</p>';
      const activeCount = availTools.filter(t => !t.unavailable && !dis.has(t.name)).length;
      return `<details class="tool-pick"><summary><span>Choose active tools</span><span class="note">${activeCount} of ${availTools.length} on</span></summary><div class="tool-pick-body">${body}</div></details>`;
    })()}
    ${(auth.user && auth.user.tier !== 'limited') ? `<details class="tool-pick" id="memBox"><summary><span>Saved memories</span><span class="note">${availMemories.length} saved</span></summary>
      <div class="tool-pick-body" id="memBody">${availMemories.length ? `<div class="mem-list">${availMemories.slice().reverse().map(m => `<div class="mem-row" data-mid="${esc(m.id)}"><span>${esc(m.text)}</span><button type="button" data-mdel="${esc(m.id)}" title="Forget">✕</button></div>`).join('')}</div><div><button class="btn-sm danger" id="memClear">Clear all memories</button></div>` : '<p class="note">No memories saved yet. Ask Mochi to remember something about you.</p>'}</div></details>` : ''}
    <p class="note">Turning off tools you don’t need saves context on the 8K engine models.</p>
    <div class="sec-title">How the effort levels work</div>
    <div class="kv"><b>RDNA4 engine (27B, 9B)</b><span>Off = no thinking. Low / Medium cap thinking at ~768 / 2048 tokens (the engine closes the thought early). High = unlimited.</span>
      <b>LM Studio</b><span>Qwen3.5 9B in LM Studio: thinking on/off only — Low/Med/High only change the reply budget. Qwen3 4B Instruct (2507) has no thinking mode, so the slider is greyed out.</span></div>`;
  },
  mochi: () => `
    <div class="card" style="display:flex;gap:16px;align-items:center"><div class="avatar-slot md" id="mochiPreview" style="flex:none"></div><div><b>Mochi</b><p class="note" style="margin:4px 0 0">Your assistant’s face. Reacts while thinking, talking, finishing and on errors.</p></div></div>
    ${row('Show Mochi', 'Hide the avatar everywhere for a minimal look', tgl('mochi', S.mochi))}
    <div class="sec-title">Animation</div>${segc('mochiMotion', [['full', 'Lively'], ['subtle', 'Subtle'], ['static', 'Still']], S.mochiMotion)}
    <p class="note">Lively: idle bobbing, blinking, glances. Subtle: only reacts to what’s happening. Still: no motion at all.</p>
    <div class="acts" style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn-sm" data-mood="thinking">Preview thinking</button><button class="btn-sm" data-mood="talking">talking</button><button class="btn-sm" data-mood="done">happy</button><button class="btn-sm" data-mood="error">oops</button></div>`,
  net: () => `<div class="sec-title">Internet</div><div id="webPane"><div class="skel" style="height:120px"></div></div>
    <div class="sec-title">Local network (LAN)</div><div id="netPane"><div class="skel" style="height:80px"></div><div class="skel" style="height:140px"></div></div>`,
  accounts: () => `<div id="accPane"><div class="skel" style="height:70px"></div><div class="skel" style="height:70px"></div><div class="skel" style="height:160px"></div></div>`,
  account: () => {
    const u = auth.user || {}, m = isMaster(), hp = u.has_password, L = auth.limits;
    return `
    <div class="card acc-me"><div class="card-row"><div class="acc-av t-${esc(u.tier)}">${esc((u.username || '?')[0].toUpperCase())}</div>
      <div class="nm"><b>${esc(u.username || '')}</b><small>${tierBadge(u.tier)} · ${auth.skip ? 'this PC (login skipped)' : (auth.tunnel ? 'signed in via the internet' : (auth.local ? 'signed in on this PC' : 'signed in over the LAN'))}</small></div></div>
      ${L ? `<div class="acc-usage"><div class="vm-bar"><i style="width:${Math.min(100, 100 * L.used_today / Math.max(1, L.daily_cap))}%"></i></div><small>${L.used_today} of ${L.daily_cap} messages used today · replies up to ${L.max_tokens} tokens · ${L.models.length} model${L.models.length === 1 ? '' : 's'} allowed</small></div>` : ''}
      ${u.tier === 'user' ? '<p class="note" style="margin:8px 0 0">You can chat with any model the owner has running. Starting models and server settings are for Master accounts.</p>' : ''}</div>
    ${hp ? `<div class="sec-title">Change password</div>
      <form id="pwForm" class="field" style="display:flex;flex-direction:column;gap:8px">
        <input type="text" name="username" value="${esc(u.username || '')}" autocomplete="username" hidden>
        <input type="password" id="pwCur" placeholder="Current password" autocomplete="current-password" required>
        <input type="password" id="pwNew" placeholder="New password (8+ characters)" autocomplete="new-password" required minlength="8">
        <input type="password" id="pwNew2" placeholder="Confirm new password" autocomplete="new-password" required>
        <button class="btn-primary" type="submit">Change password</button><span class="note" id="pwMsg">Changing it signs out every other device.</span></form>`
    : (m && auth.local ? `<div class="sec-title">Create a password</div>
      <form id="pwSetup" class="field" style="display:flex;flex-direction:column;gap:8px">
        <input type="text" name="username" value="${esc(u.username || '')}" autocomplete="username" hidden>
        <input type="password" id="pwNew" placeholder="New password (8+ characters)" autocomplete="new-password" required minlength="8">
        <input type="password" id="pwNew2" placeholder="Confirm password" autocomplete="new-password" required>
        <button class="btn-primary" type="submit">Create password</button><span class="note" id="pwMsg">Needed for LAN / phone access. Stored as a salted PBKDF2 hash — never in plain text.</span></form>` : '')}
    ${m ? `<div class="sec-title">On this PC</div>
    ${row('Skip login on this PC', auth.local ? 'Lets http://127.0.0.1 open as the owner (Master) without a password. LAN, internet and every other account always need a password.' : 'Only changeable on the PC itself.', tgl('nologin', auth.localhost_no_login, auth.local && hp ? '' : 'disabled'))}` : ''}
    <div class="sec-title">Sessions</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn-sm" id="soThis">Sign out</button><button class="btn-sm" id="soAll">Sign out all devices</button></div>
    ${m && auth.local ? `<div class="sec-title">Mochi on this PC</div>
      <div class="card"><div class="card-row"><div class="nm"><b>Shut down Mochi</b><small>Stops the server, SearXNG search, any active internet link and unloads loaded models.</small></div>
      <button class="btn-sm danger" id="shutdownCardBtn">Shut down…</button></div></div>` : ''}
    <div class="sec-title">Chats</div>
    <p class="note">Your chats are private to your account: saved on the PC under <code>chat-ui\\data\\users</code> and synced to every device you sign in on. Export any chat from its ⋯ menu.</p>`;
  },
  keys: () => `<div class="kv">
    <kbd>Ctrl+Shift+O</kbd><span>New chat</span><kbd>Ctrl+K</kbd><span>Search chats</span><kbd>Ctrl+B</kbd><span>Toggle sidebar</span>
    <kbd>Ctrl+M</kbd><span>Models &amp; VRAM</span><kbd>Ctrl+,</kbd><span>Settings</span><kbd>Ctrl+Shift+L</kbd><span>Light / dark</span>
    <kbd>Alt+1…4</kbd><span>Effort Off / Low / Medium / High</span><kbd>Ctrl+Shift+R</kbd><span>Regenerate last reply</span>
    <kbd>Esc</kbd><span>Stop generating / close panels</span><kbd>/</kbd><span>Focus the message box</span>
    <kbd>${S.sendOnEnter ? 'Enter' : 'Ctrl+Enter'}</kbd><span>Send</span><kbd>${S.sendOnEnter ? 'Shift+Enter' : 'Enter'}</kbd><span>New line</span></div>`
};
const TABS_AFTER = {
  mochi: b => { const av = mountAvatar($('#mochiPreview', b)); $$('[data-mood]', b).forEach(x => x.onclick = () => setMood(av, x.dataset.mood, 2400)); },
  net: () => { renderInternet(); renderNet(true); },
  accounts: () => renderAccounts(),
  account: b => {
    const f = $('#pwForm', b), su = $('#pwSetup', b), msg = $('#pwMsg', b);
    if (f) f.onsubmit = async e => {
      e.preventDefault();
      if ($('#pwNew').value !== $('#pwNew2').value) { msg.textContent = "New passwords don't match"; msg.className = 'note bad'; return; }
      try { await api('/api/auth/password', 'POST', { current: $('#pwCur').value, password: $('#pwNew').value }); f.reset(); msg.textContent = 'Password changed. Other devices were signed out.'; msg.className = 'note ok'; toast('Password changed', 'ok'); }
      catch (ex) { msg.textContent = ex.message; msg.className = 'note bad'; }
    };
    if (su) su.onsubmit = async e => {
      e.preventDefault();
      if ($('#pwNew').value !== $('#pwNew2').value) { msg.textContent = "Passwords don't match"; msg.className = 'note bad'; return; }
      try { await api('/api/auth/setup', 'POST', { password: $('#pwNew').value }); auth.has_password = true; toast('Password created', 'ok'); showTab('account'); }
      catch (ex) { msg.textContent = ex.message; msg.className = 'note bad'; }
    };
    $('#soThis', b).onclick = () => { closeSheets(); logout(false); };
    $('#soAll', b).onclick = () => logout(true);
    if ($('#shutdownCardBtn', b)) $('#shutdownCardBtn', b).onclick = shutdownMochi;
    api('/api/auth/state').then(st => { const was = JSON.stringify(auth.limits); auth = Object.assign(auth, st); if (JSON.stringify(auth.limits) !== was && curTab === 'account') showTab('account'); }).catch(() => { });
  }
};
$('#settingsBody').addEventListener('click', async e => {
  const mdBtn = e.target.closest('[data-mdel]');
  if (mdBtn) {
    try { await api('/api/memory/' + mdBtn.dataset.mdel, 'DELETE'); await loadMemories(); showTab('chat'); toast('Memory forgotten', 'ok'); }
    catch (ex) { toast(ex.message, 'bad'); }
    return;
  }
  if (e.target.closest('#memClear')) {
    if (!await confirmModal('Clear all memories?', 'Mochi will forget all saved facts about you.', 'Clear all', 'error')) return;
    try { await api('/api/memory', 'DELETE'); await loadMemories(); showTab('chat'); toast('Memories cleared', 'ok'); }
    catch (ex) { toast(ex.message, 'bad'); }
    return;
  }
  const sb = e.target.closest('[data-seg] button');
  if (sb) {
    const k = sb.parentElement.dataset.seg; let v = sb.dataset.v; if (k === 'maxTokens' || k === 'maxToolRounds') v = +v;
    S[k] = v; saveSettings(); applyLook(); $$('button', sb.parentElement).forEach(x => x.classList.toggle('on', x === sb));
    if (k === 'tempMode') $('#tempRow').hidden = v !== 'manual';
    if (k === 'mochiMotion' || k === 'theme' || k === 'density' || k === 'width') setTimeout(renderEffort, 300);
    return;
  }
  const acc = e.target.closest('[data-acc]');
  if (acc) { S.accent = acc.dataset.acc; saveSettings(); applyLook(); $$('.swatch').forEach(x => x.classList.toggle('on', x === acc)); return; }
  const t = e.target.closest('.tg[data-k]');
  if (t && !t.disabled) {
    const k = t.dataset.k, on = !t.classList.contains('on');
    if (k === 'nologin') {
      try { const r = await api('/api/security', 'POST', { localhost_no_login: on }); auth.localhost_no_login = r.localhost_no_login; t.classList.toggle('on', r.localhost_no_login); toast(on ? 'This PC skips the login' : 'This PC now asks for the password too', 'ok'); }
      catch (ex) { toast(ex.message, 'bad'); }
      return;
    }
    S[k] = on; t.classList.toggle('on', on); t.setAttribute('aria-checked', on); saveSettings(); applyLook();
    if (k === 'sendOnEnter') updateHint();
    if (k === 'showStats') renderChat(false, true);
    if (k === 'toolsEnabled') updateToolsBtn();
    return;
  }
  const pr = e.target.closest('[data-preset]');
  if (pr && !e.target.closest('.pa')) { S.presetId = pr.dataset.preset; saveSettings(); $$('.preset').forEach(x => x.classList.toggle('on', x === pr)); toast('System prompt: ' + $('b', pr).textContent, 'ok'); return; }
  const pe = e.target.closest('[data-pedit]'); if (pe) return editPreset(pe.dataset.pedit);
  const pd = e.target.closest('[data-pdel]');
  if (pd) { S.presets = S.presets.filter(p => p.id !== pd.dataset.pdel); if (S.presetId === pd.dataset.pdel) S.presetId = 'mochi'; saveSettings(); showTab('chat'); return; }
  if (e.target.closest('#presetAdd')) return editPreset(null);
});
$('#settingsBody').addEventListener('input', e => {
  const r = e.target.closest('[data-range]');
  if (r) { const k = r.dataset.range; S[k] = +r.value; applyLook(); saveSettings();
    if (k === 'fontSize') r.previousElementSibling.textContent = `Text size · ${S.fontSize}px`;
    if (k === 'temperature') $('#tempOut').textContent = (+r.value).toFixed(2); }
  if (e.target.id === 'accCustom') { S.accent = 'custom'; S.customAccent = e.target.value; applyLook(); saveSettings(); $$('.swatch').forEach(x => x.classList.toggle('on', x.classList.contains('custom'))); }
});
$('#settingsBody').addEventListener('change', e => {
  if (e.target.id === 'defModel') { const v = e.target.value; S.defaultModel = v ? { backend: v.split('|')[0], id: v.slice(v.indexOf('|') + 1) } : null; saveSettings(); renderPicker(); }
  const tt = e.target.closest('[data-tool-tgl]');
  if (tt) {
    const name = tt.dataset.toolTgl;
    const set = new Set(S.disabledTools || []);
    if (tt.checked) set.delete(name); else set.add(name);
    S.disabledTools = [...set];
    saveSettings();
    const sum = tt.closest('.tool-pick').querySelector('summary .note');
    if (sum) {
      const cnt = availTools.filter(t => !t.unavailable && !set.has(t.name)).length;
      sum.textContent = `${cnt} of ${availTools.length} on`;
    }
  }
});
function editPreset(id) {
  const p = id ? S.presets.find(x => x.id === id) : { id: 'p' + uid(), name: '', text: '' };
  const box = $('#presetEdit');
  box.innerHTML = `<div class="card field" style="display:flex;flex-direction:column;gap:8px"><input type="text" id="peName" placeholder="Preset name" maxlength="40">
    <textarea class="field-ta" id="peText" placeholder="System prompt — how Mochi should behave"></textarea>
    <div style="display:flex;gap:8px"><button class="btn-sm primary" id="peSave">Save preset</button><button class="btn-sm" id="peCancel">Cancel</button></div></div>`;
  $('#peName').value = p.name; $('#peText').value = p.text; $('#peName').focus();
  $('#peCancel').onclick = () => { box.innerHTML = ''; };
  $('#peSave').onclick = () => {
    const name = $('#peName').value.trim() || 'Untitled', text = $('#peText').value;
    const i = S.presets.findIndex(x => x.id === p.id);
    if (i >= 0) S.presets[i] = { id: p.id, name, text }; else S.presets.push({ id: p.id, name, text });
    S.presetId = p.id; saveSettings(); showTab('chat'); toast('Preset saved', 'ok');
  };
}

/* ---- network (LAN) ---- */
async function renderNet(fetchFw) {
  const pane = $('#netPane'); if (!pane) return;
  try { lanInfo = await api('/api/lan'); } catch (ex) { pane.innerHTML = `<p class="note bad">${esc(ex.message)}</p>`; return; }
  const L = lanInfo, loc = auth.local, url = L.urls[0] || '';
  const dis = !loc || !L.has_password ? 'disabled' : '';
  let h = `<div class="card"><div class="card-row"><div class="nm"><b>LAN mode</b><small>${L.enabled ? '● On — reachable from devices on your Wi-Fi' : '○ Off — only this PC can open the app'}</small></div>${tgl('lan', L.enabled, dis)}</div>
    ${!L.has_password ? '<div class="warn">Create a password first (Account tab) — LAN mode always requires a login.</div>' : ''}
    ${!loc ? '<p class="note" style="margin-top:8px">For safety, network settings can only be changed on the PC itself.</p>' : ''}
    ${L.error ? `<p class="note bad">${esc(L.error)}</p>` : ''}</div>`;
  if (L.enabled && url) h += `<div class="card qr"><div class="qrbox">${window.QR ? QR.svg(url, { size: 136 }) : ''}</div><div><b>Open on your phone</b><p class="note" style="margin:4px 0">Scan with the camera, or type:</p><code>${esc(url)}</code>
      ${L.urls.length > 1 ? `<p class="note">Also: ${L.urls.slice(1).map(esc).join(', ')}</p>` : ''}<p class="note">Same Wi-Fi only. Sign in with your password.</p></div></div>`;
  h += `<div class="card"><div class="card-row"><div class="nm"><b>Start LAN mode with Windows</b><small>Runs the chat server hidden at sign-in (per-user, no admin).</small></div>${tgl('autostart', L.autostart, dis)}</div></div>
    <div class="sec-title">Windows Firewall</div><div class="card" id="fwCard"><div class="status"><span class="spin"></span>Checking firewall rules…</div></div>
    <p class="note">Traffic on the LAN is plain HTTP (not encrypted). Use it on your home Wi-Fi only, not on public networks.</p>`;
  pane.innerHTML = h;
  pane.onclick = async e => {
    const t = e.target.closest('.tg[data-k]'); if (!t || t.disabled) return;
    const on = !t.classList.contains('on'), k = t.dataset.k;
    if (k === 'lan' && on && !await confirmModal('Turn on LAN mode?', 'Devices on your home network will be able to reach the sign-in page at ' + (url || 'your PC’s IP') + '. Everything still needs your password.', 'Turn on', 'thinking')) return;
    t.classList.add('busy');
    try {
      await api('/api/lan', 'POST', k === 'lan' ? { enabled: on } : { autostart: on });
      if (k === 'lan') { await sleep(1300); toast(on ? 'LAN mode on 📱' : 'LAN mode off — local only', 'ok'); }
      else toast(on ? 'LAN mode will start with Windows' : 'Autostart removed', 'ok');
    } catch (ex) { toast(ex.message, 'bad'); }
    renderNet(false); refreshLanBadge();
  };
  fwCard(fetchFw);
}
async function fwCard(force) {
  const c = $('#fwCard'); if (!c) return;
  try {
    if (force || !fwInfo) fwInfo = await api('/api/lan/firewall');
    const f = fwInfo, prof = (f.profiles || []).map(p => `${esc(p.alias)}: ${esc(p.category)}`).join(', ');
    c.innerHTML = `<p class="note ${f.rule_needed ? 'warn' : 'ok'}" style="margin:0">${f.rule_needed ? '⚠ ' : '✓ '}${esc(f.verdict)}</p>
      <p class="note" style="margin:6px 0 0">Network: ${prof || 'unknown'}${f.portRule && f.portRule.length ? ' · port rule present' : ''}</p>
      ${f.rule_needed ? '<p class="note" style="margin:6px 0 0">To allow phones, right-click <code>Add-ChatUIFirewallRule.ps1</code> in the chat-ui folder › Run with PowerShell (as admin). It opens TCP 8765 for Private networks on your local subnet only. <code>Remove-ChatUIFirewallRule.ps1</code> undoes it.</p>' : ''}`;
  } catch (ex) { c.innerHTML = `<p class="note bad">${esc(ex.message)}</p>`; }
}
async function refreshLanBadge() {
  try { const st = await api('/api/auth/state'); auth = Object.assign(auth, st); applyRole(); } catch { }
}

/* ---- internet link: Tailscale Funnel (fixed link) or Cloudflare Quick Tunnel (changing link) ---- */
let webInfo = null, webT = null;
const TS_STATE = { Running: 'Connected', Stopped: 'Disconnected', NeedsLogin: 'Needs sign-in', NeedsMachineAuth: 'Waiting for approval', Starting: 'Starting…', NoState: 'Service not running' };
const breakUrl = u => esc(u).replace(/[./-]/g, m => m + '<wbr>');
async function renderInternet() {
  const pane = $('#webPane'); if (!pane) return;
  try { webInfo = await api('/api/internet'); } catch (ex) { pane.innerHTML = `<p class="note bad">${esc(ex.message)}</p>`; return; }
  const W = webInfo, loc = auth.local, on = W.state === 'on' || W.state === 'starting', T = W.tailscale || {}, A = T.action || {};
  const prov = on || W.state === 'error' ? W.provider : W.chosen, isTs = prov === 'tailscale';
  auth.internet = W.state === 'on'; applyRole();
  const dis = !loc || !W.has_password || !W.installed ? 'disabled' : '';
  const where = isTs ? 'Tailscale Funnel' : 'Cloudflare';
  const stTxt = { off: '○ Off — only your PC (and LAN, if on) can open Mochi', starting: `◌ Starting ${where}…`,
    on: W.connected ? '● On — anyone with the link can reach the sign-in page' : `● Link ready — waiting for ${where}…`, error: '⚠ ' + (W.error || 'Stopped') }[W.state] || W.state;
  let h = `<div class="card web-card s-${esc(W.state)}"><div class="card-row"><div class="nm"><b>Internet link</b><small>${esc(stTxt)}</small></div>
      <button class="tg${on ? ' on' : ''}${W.state === 'starting' ? ' busy' : ''}" role="switch" aria-checked="${on}" data-web="enabled" ${dis}></button></div>
    ${W.enable_url ? `<div class="warn ts-enable"><b>${/funnel/i.test(W.error) ? 'Funnel isn’t enabled for your tailnet yet.' : 'Tailscale needs you to approve this.'}</b> Open the link, approve it while signed in to Tailscale, then turn the internet link on again.
        <div class="web-acts"><a class="btn-sm primary" href="${esc(W.enable_url)}" target="_blank" rel="noopener noreferrer">${/funnel/i.test(W.error) ? 'Enable Funnel' : 'Open Tailscale'}</a><button class="btn-sm" data-webcopy="${esc(W.enable_url)}">Copy link</button></div></div>` : ''}
    ${!W.has_password ? '<div class="warn">Create a password first (Account tab) — the internet link always requires a login.</div>' : ''}
    ${!W.installed ? `<div class="warn">${isTs ? 'Tailscale is not installed.' : 'cloudflared.exe is missing (expected in C:\\Dev\\Tools\\cloudflared).'}</div>` : ''}
    ${!loc ? '<p class="note" style="margin-top:8px">For safety, the internet link can only be changed on the PC itself.</p>' : ''}
    <div class="web-prov"><span class="note">Link type</span><div class="seg full" id="webProv">
      <button data-v="tailscale" class="${W.chosen === 'tailscale' ? 'on' : ''}" ${!loc || !T.installed ? 'disabled' : ''}>Tailscale · fixed link</button>
      <button data-v="cloudflare" class="${W.chosen === 'cloudflare' ? 'on' : ''}" ${!loc || !W.cf_installed ? 'disabled' : ''}>Cloudflare · quick link</button></div></div>
    <p class="note" style="margin-top:8px">${W.chosen === 'tailscale'
      ? `Free Tailscale Funnel — <b>the link stays the same</b>. Anyone with the link sees the sign-in page; every account needs its password and “skip login” never applies.${T.fixed_url ? `<code class="url-block">${breakUrl(T.fixed_url)}</code>` : ''}`
      : 'Free Cloudflare Quick Tunnel — no account. Anyone with the link sees the sign-in page; every account needs its password and “skip login” never applies. <b>The link changes every time the tunnel or Mochi restarts.</b>'}</p></div>`;
  if (W.url) h += `<div class="card qr web-qr"><div class="qrbox">${window.QR ? QR.svg(W.url, { size: 136 }) : ''}</div><div style="min-width:0"><b>Your public link</b>
      <p class="note" style="margin:4px 0">Scan it with a phone, or share it:</p><code class="url-block" id="webUrl">${breakUrl(W.url)}</code>
      <div class="web-acts"><button class="btn-sm primary" data-webcopy="${esc(W.url)}">Copy link</button><a class="btn-sm" href="${esc(W.url)}" target="_blank" rel="noopener noreferrer">Open</a></div>
      <p class="note">HTTPS via ${isTs ? 'Tailscale Funnel · same link every time' : 'Cloudflare · new link after a restart'} · works from any network.</p></div></div>`;
  if (T.installed) {
    const st = T.state || 'NoState', up = st === 'Running', svcOn = T.service === 'running', busy = A.busy;
    const dot = up ? (T.online === false ? 'busy' : 'on') : st === 'NoState' || !svcOn ? 'off' : 'busy';
    const ldis = !loc || busy ? 'disabled' : '';
    const meta = [TS_STATE[st] || st, T.tailnet, T.host ? T.host.split('.')[0] : '', 'service ' + (T.service || '?'), T.version ? 'v' + T.version : ''].filter(Boolean);
    h += `<div class="card ts-card"><div class="card-row"><div class="nm"><b><span class="dot ${dot}"></span> Tailscale</b>
        <small class="meta-line">${meta.map(x => `<span>${esc(x)}</span>`).join('')}</small></div></div>
      ${busy ? `<p class="note"><span class="dot busy"></span> ${esc({ disconnect: 'Disconnecting…', reconnect: 'Reconnecting…', service_stop: 'Waiting for Windows permission to stop the service…', service_start: 'Waiting for Windows permission to start the service…' }[busy] || busy)}</p>`
        : A.msg && Date.now() / 1000 - (A.t || 0) < 120 ? `<p class="note ${A.ok ? '' : 'bad'}">${A.ok ? '✓' : '⚠'} ${esc(A.msg)}</p>` : ''}
      ${A.auth_url || (st === 'NeedsLogin' && T.auth_url) ? `<div class="web-acts"><a class="btn-sm primary" href="${esc(A.auth_url || T.auth_url)}" target="_blank" rel="noopener noreferrer">Sign in to Tailscale</a></div>` : ''}
      ${loc ? `<div class="web-acts ts-acts">
        ${up ? `<button class="btn-sm" data-ts="disconnect" ${ldis}>Disconnect</button>` : `<button class="btn-sm primary" data-ts="reconnect" ${ldis || (!svcOn ? 'disabled' : '')}>Reconnect</button>`}
        ${svcOn ? `<button class="btn-sm danger" data-ts="service_stop" ${ldis}>Stop service</button>` : `<button class="btn-sm" data-ts="service_start" ${ldis}>Start service</button>`}</div>
        <p class="note">Disconnect/Reconnect need no admin rights. Stopping or starting the Tailscale service asks for Windows permission (UAC) every time. Turning Tailscale off also turns the internet link off.</p>`
        : '<p class="note">Tailscale controls are only available on the PC itself.</p>'}</div>`;
  }
  h += `<div class="card"><div class="card-row"><div class="nm"><b>Start the internet link with Mochi</b><small>Turns the link on whenever the chat server starts${W.chosen === 'tailscale' ? '' : ' (a new link each time)'}.</small></div>
      <button class="tg${W.autostart ? ' on' : ''}" role="switch" aria-checked="${!!W.autostart}" data-web="autostart" ${dis}></button></div></div>`;
  pane.innerHTML = h;
  clearTimeout(webT);
  if (W.state === 'starting' || (W.state === 'on' && !W.connected) || A.busy || ['Starting', 'NoState'].includes(T.state) && T.service === 'running')
    webT = setTimeout(() => { if (curTab === 'net' && sheetOpen === 'settings') renderInternet(); }, 1500);
  pane.onclick = async e => {
    const cp = e.target.closest('[data-webcopy]');
    if (cp) { await copyText(cp.dataset.webcopy); const o = cp.textContent; cp.textContent = 'Copied ✓'; setTimeout(() => { cp.textContent = o; }, 1400); return; }
    const pv = e.target.closest('#webProv button'); 
    if (pv && !pv.disabled && !pv.classList.contains('on')) {
      if (on && !await confirmModal('Switch the link type?', 'The current internet link turns off. Turn it back on afterwards to get the new kind of link.', 'Switch', 'thinking')) return;
      try { await api('/api/internet', 'POST', { provider: pv.dataset.v }); toast(pv.dataset.v === 'tailscale' ? 'Using Tailscale Funnel (fixed link)' : 'Using a Cloudflare quick link', 'ok'); } catch (ex) { toast(ex.message, 'bad'); }
      return renderInternet();
    }
    const ta = e.target.closest('[data-ts]');
    if (ta && !ta.disabled) {
      const a = ta.dataset.ts;
      if (a === 'service_stop' && !await confirmModal('Stop the Tailscale service?', 'Windows will ask for permission. Tailscale (and the internet link, if on) stops on this PC until you start it again.', 'Stop service', 'thinking')) return;
      if (a === 'disconnect' && W.provider === 'tailscale' && on && !await confirmModal('Disconnect Tailscale?', 'The internet link turns off too.', 'Disconnect', 'thinking')) return;
      try { await api('/api/tailscale', 'POST', { action: a }); if (a.startsWith('service')) toast('Windows is asking for permission — check the UAC prompt', 'ok'); } catch (ex) { toast(ex.message, 'bad'); }
      return renderInternet();
    }
    const t = e.target.closest('.tg[data-web]'); if (!t || t.disabled) return;
    const k = t.dataset.web, nv = !t.classList.contains('on');
    if (k === 'enabled' && nv && !await confirmModal('Put Mochi on the internet?', W.chosen === 'tailscale'
      ? `Mochi becomes reachable at ${T.fixed_url || 'your fixed https://….ts.net link'} through Tailscale Funnel. Anyone with the link can reach the sign-in page — every account still needs its password. You can turn it off any time.`
      : 'Mochi gets a public https://….trycloudflare.com link. Anyone with the link can reach the sign-in page — every account still needs its password. You can turn it off any time.', 'Turn on', 'thinking')) return;
    t.classList.add('busy');
    try {
      await api('/api/internet', 'POST', { [k]: nv });
      toast(k === 'enabled' ? (nv ? 'Starting the internet link…' : 'Internet link off — the link no longer works') : (nv ? 'The internet link will start with Mochi' : 'Internet auto-start off'), 'ok');
    } catch (ex) { toast(ex.message, 'bad'); }
    renderInternet(); refreshLanBadge();
  };
}

/* ---- accounts (Master only) ---- */
const TIER_LBL = { master: 'Master', user: 'User', limited: 'Limited User' };
const tierBadge = t => `<span class="tier-badge t-${esc(t)}">${esc(TIER_LBL[t] || t)}</span>`;
const isMaster = () => !!(auth.perms && auth.perms.accounts);
let accData = null;
async function renderAccounts() {
  const pane = $('#accPane'); if (!pane) return;
  try { accData = await api('/api/accounts'); } catch (ex) { pane.innerHTML = `<p class="note bad">${esc(ex.message)}</p>`; return; }
  const A = accData, masters = A.accounts.filter(a => a.tier === 'master' && a.active).length;
  const boxes = (sel, name) => A.model_choices.length ? `<div class="acc-models">${A.model_choices.map(m => `<label class="chk"><input type="checkbox" name="${esc(name)}" value="${esc(m.key)}"${sel.includes(m.key) ? ' checked' : ''}><span>${esc(m.label)}</span></label>`).join('')}</div>` : '<p class="note">No models found.</p>';
  const nums = l => `<div class="acc-nums"><label>Messages per day<input type="number" min="0" max="100000" value="${+l.daily_cap}" data-lim="daily_cap"></label><label>Max reply tokens<input type="number" min="64" max="32768" step="64" value="${+l.max_tokens}" data-lim="max_tokens"></label></div>`;
  const card = (a, i) => {
    const lock = a.you || (a.tier === 'master' && a.active && masters <= 1);
    const why = a.you ? 'You can’t turn off or change your own account here' : 'The last active Master always stays on';
    const when = a.last_login ? 'signed in ' + ago(a.last_login * 1000) : 'never signed in';
    return `<div class="card acc-card${a.active ? '' : ' off'}" data-aid="${esc(a.id)}" style="animation-delay:${i * 40}ms">
      <div class="card-row"><div class="acc-av t-${esc(a.tier)}">${esc(a.username[0].toUpperCase())}</div>
        <div class="nm"><b>${esc(a.username)}${a.you ? ' <span class="you">you</span>' : ''}</b><small>${tierBadge(a.tier)} · ${a.active ? 'Active' : 'Turned off'} · ${when}${a.has_password ? '' : ' · no password yet'}</small></div>
        <button class="tg${a.active ? ' on' : ''}" role="switch" aria-checked="${a.active}" aria-label="Active" data-acc-active title="${lock ? why : (a.active ? 'Active — click to turn off' : 'Turned off — click to allow sign-in')}" ${lock ? 'disabled' : ''}></button></div>
      <div class="acc-acts">
        <div class="field"><select data-acc-tier aria-label="Tier" ${lock ? 'disabled title="' + why + '"' : ''}>${Object.entries(TIER_LBL).map(([k, l]) => `<option value="${k}"${a.tier === k ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
        <button class="btn-sm" data-acc-pw>Reset password</button>
        <button class="btn-sm danger" data-acc-del ${lock ? 'disabled' : ''}>Delete</button></div>
      <div class="acc-pw field" hidden><input type="password" placeholder="New password (8+ characters)" autocomplete="new-password" data-acc-newpw><button class="btn-sm primary" data-acc-pwsave>Save</button></div>
      ${a.tier === 'limited' ? `<details class="acc-lim"><summary>Limits · ${a.limits.daily_cap}/day · ${a.limits.max_tokens} tokens · ${a.limits.models.length} model${a.limits.models.length === 1 ? '' : 's'}</summary>
        ${boxes(a.limits.models, 'm-' + a.id)}${nums(a.limits)}<button class="btn-sm primary" data-acc-limsave>Save limits</button></details>` : ''}
    </div>`;
  };
  pane.innerHTML = `<div class="sec-title">Accounts · ${A.accounts.length}</div><div class="acc-list">${A.accounts.map(card).join('')}</div>
    <div class="sec-title">Create an account</div>
    <form class="card field acc-new" id="accNew" autocomplete="off">
      <input type="text" id="anUser" placeholder="Username (3–32: letters, digits, . _ -)" maxlength="32" autocomplete="off" autocapitalize="none" spellcheck="false" required>
      <input type="password" id="anPw" placeholder="Password (8+ characters)" autocomplete="new-password" required minlength="8">
      <div class="seg full" id="anTier">${Object.entries(TIER_LBL).map(([k, l]) => `<button type="button" data-v="${k}" class="${k === 'user' ? 'on' : ''}">${l}</button>`).join('')}</div>
      <button class="btn-primary" type="submit">Create account</button><span class="note" id="anMsg"></span></form>
    <div class="sec-title">Limited User defaults</div>
    <div class="card field acc-def" id="accDef"><p class="note" style="margin:0 0 8px">Used for new Limited Users — each one can be changed above.</p>${boxes(A.defaults.models, 'def')}${nums(A.defaults)}
      <button class="btn-sm primary" id="defSave">Save defaults</button></div>
    <div class="sec-title">What each tier can do</div>
    <div class="kv"><b>Master</b><span>Everything: start/stop models, VRAM, all settings, LAN and internet link, accounts.</span>
      <b>User</b><span>Chats with models that are already running. Own chats and look settings only — no model start/stop or server settings.</span>
      <b>Limited User</b><span>Only the models you tick, a daily message cap and a max reply length. Own chats only.</span></div>
    <p class="note">Turning an account off signs it out everywhere at once. Deleting an account also deletes its chats.</p>`;
  let tier = 'user'; const seg = $('#anTier');
  seg.onclick = e => { const b = e.target.closest('button'); if (!b) return; tier = b.dataset.v; $$('button', seg).forEach(x => x.classList.toggle('on', x === b)); };
  $('#accNew').onsubmit = async e => {
    e.preventDefault(); const msg = $('#anMsg'), name = $('#anUser').value.trim();
    try { await api('/api/accounts', 'POST', { username: name, password: $('#anPw').value, tier }); toast(`Account “${name}” created (${TIER_LBL[tier]})`, 'ok'); renderAccounts(); }
    catch (ex) { msg.textContent = ex.message; msg.className = 'note bad'; }
  };
  const lim = box => ({ models: $$('input[type=checkbox]:checked', box).map(x => x.value), daily_cap: +$('[data-lim=daily_cap]', box).value, max_tokens: +$('[data-lim=max_tokens]', box).value });
  $('#defSave').onclick = async () => { try { await api('/api/accounts/defaults', 'PUT', lim($('#accDef'))); toast('Limited User defaults saved', 'ok'); } catch (ex) { toast(ex.message, 'bad'); } };
  pane.onclick = async e => {
    const cardEl = e.target.closest('[data-aid]'); if (!cardEl) return;
    const id = cardEl.dataset.aid, a = A.accounts.find(x => x.id === id); if (!a) return;
    const patch = async (body, okMsg) => { try { await api('/api/accounts/' + id, 'PATCH', body); if (okMsg) toast(okMsg, 'ok'); } catch (ex) { toast(ex.message, 'bad'); } renderAccounts(); };
    const t = e.target.closest('[data-acc-active]');
    if (t) {
      if (t.disabled) return;
      const on = !t.classList.contains('on');
      if (!on && !await confirmModal(`Turn off “${a.username}”?`, 'They are signed out everywhere right away and can’t sign in until you turn the account back on.', 'Turn off', 'error')) return;
      t.classList.add('busy'); return patch({ active: on }, on ? `${a.username} can sign in again` : `${a.username} is turned off and signed out`);
    }
    if (e.target.closest('[data-acc-pw]')) { const p = $('.acc-pw', cardEl); p.hidden = !p.hidden; if (!p.hidden) $('input', p).focus(); return; }
    if (e.target.closest('[data-acc-pwsave]')) { const v = $('[data-acc-newpw]', cardEl).value; if (v.length < 8) return toast('Use at least 8 characters', 'bad'); return patch({ password: v }, `Password reset for ${a.username} — their other sessions were signed out`); }
    if (e.target.closest('[data-acc-limsave]')) return patch({ limits: lim($('.acc-lim', cardEl)) }, `Limits saved for ${a.username}`);
    const d = e.target.closest('[data-acc-del]');
    if (d && !d.disabled) {
      if (!await confirmModal(`Delete “${a.username}”?`, 'The account and all of its chats are deleted. This can’t be undone.', 'Delete', 'error')) return;
      try { await api('/api/accounts/' + id, 'DELETE'); toast(`${a.username} deleted`, 'ok'); } catch (ex) { toast(ex.message, 'bad'); }
      renderAccounts();
    }
  };
  pane.onchange = e => {
    const s = e.target.closest('[data-acc-tier]'); if (!s) return; const id = s.closest('[data-aid]').dataset.aid;
    api('/api/accounts/' + id, 'PATCH', { tier: s.value }).then(() => toast(`Tier changed to ${TIER_LBL[s.value]}`, 'ok')).catch(ex => toast(ex.message, 'bad')).finally(renderAccounts);
  };
}
function applyRole() {
  const m = isMaster();
  document.body.classList.toggle('not-master', !m);
  $('#openModels').hidden = !m; $('#vramMini').hidden = !m;
  $('#tabNet').hidden = !m; $('#tabAccounts').hidden = !m;
  if (!m && (curTab === 'net' || curTab === 'accounts')) curTab = 'look';
  $('#lanBadge').hidden = !(m && auth.lan); $('#webBadge').hidden = !(m && auth.internet);
  if ($('#shutdownBtn')) $('#shutdownBtn').hidden = !(m && auth.local);
}

/* ================= keyboard ================= */
document.addEventListener('keydown', e => {
  const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if (!auth.authed) return;
  if (e.key === 'Escape') {
    if (modalClose) return modalClose();
    if (!el.menu.hidden) return closeMenu();
    if (el.modelPicker.classList.contains('open')) return el.modelPicker.classList.remove('open');
    if (sheetOpen) return closeSheets();
    if (gen) return stopGen();
    if (narrow() && !el.app.classList.contains('side-closed')) return el.app.classList.add('side-closed');
    return;
  }
  if (mod && e.shiftKey && k === 'o') { e.preventDefault(); return newChat(); }
  if (mod && e.shiftKey && k === 'l') { e.preventDefault(); return $('#themeBtn').click(); }
  if (mod && e.shiftKey && k === 'r') { e.preventDefault(); return regenerate(); }
  if (mod && k === 'k') { e.preventDefault(); el.app.classList.remove('side-closed'); el.search.focus(); el.search.select(); return; }
  if (mod && k === 'b') { e.preventDefault(); return el.app.classList.toggle('side-closed'); }
  if (mod && k === 'm') { e.preventDefault(); if (!isMaster()) return; return sheetOpen === 'models' ? closeSheets() : openSheet('models'); }
  if (mod && k === ',') { e.preventDefault(); return sheetOpen === 'settings' ? closeSheets() : openSheet('settings'); }
  if (e.altKey && !mod && /^[1-4]$/.test(e.key)) { e.preventDefault(); setEffort(+e.key - 1); return; }
  if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); el.input.focus(); }
});

/* ================= avatars: idle life ================= */
document.addEventListener('pointermove', e => { if (S.mochiMotion === 'full') { lookAt(heroAv, e); lookAt(brandAv, e); lookAt(authAv, e); } }, { passive: true });
setInterval(() => {
  if (S.mochiMotion !== 'full' || reduced() || heroAv.getAttribute('data-state') !== 'idle') return;
  const f = $('.m-face', heroAv), x = (Math.random() * 8 - 4).toFixed(1), y = (Math.random() * 4 - 2).toFixed(1);
  f.style.transform = `translate(${x}px,${y}px)`; setTimeout(() => { f.style.transform = ''; }, 900);
}, 5200);
heroAv.addEventListener('click', () => setMood(heroAv, 'done', 1100)); heroAv.style.cursor = 'pointer';
const greet = ['Your private AI, running entirely on this PC.', 'No cloud, no logs — just you and your GPU.', 'Ask me anything. I live on your RX 9070 XT.'];
$('#heroSub').textContent = greet[Math.floor(Math.random() * greet.length)];

/* ================= boot ================= */
async function boot() {
  let st;
  try { st = await api('/api/auth/state'); }
  catch { $('#auth').hidden = false; $('#authTitle').textContent = 'Can’t reach the chat server'; $('#authText').textContent = 'Is it running on the PC?'; return; }
  auth = Object.assign(auth, st);
  if (!st.authed) return showAuth(st);
  $('#auth').hidden = true; el.app.hidden = false;
  applyRole();
  $('#logoutBtn').hidden = !!st.skip;
  $('#brandSub').textContent = (st.user ? st.user.username + ' · ' : '') + (st.local ? 'on ATHEREAL' : st.tunnel ? 'via the internet' : 'via your Wi-Fi');
  try {
    const srv = await api('/api/settings');
    if (srv && Object.keys(srv).length) { S = Object.assign({}, DEFAULTS, srv); localStorage.setItem(LS_SET, JSON.stringify(S)); }
    else { S = Object.assign({}, DEFAULTS); saveSettings(); } // a new account starts from the defaults, not from whoever used this browser before
  } catch { }
  if (!Array.isArray(S.presets) || !S.presets.length) S.presets = PRESETS0;
  applyLook();
  await migrateLocal();
  await Promise.all([loadTools(), loadMemories()]);
  listLoading = true; renderList();
  await refreshList();
  const last = localStorage.getItem(LS_CUR);
  if (last && chatList.some(c => c.id === last)) openChat(last); else { currentId = null; renderChat(); }
  autosize(); updateSend(); renderEffort();
  pollModels(); refreshVram();
  clearInterval(listT); listT = setInterval(() => { if (document.visibilityState === 'visible') refreshList(); }, 5000);
  if (isMaster() && !st.has_password && st.local) setTimeout(() => toast('Tip: create a password to use Mochi from your phone', '', { label: 'Set up', fn: () => openSheet('settings', 'account') }), 1600);
  if (!narrow()) el.input.focus();
  requestAnimationFrame(renderEffort);
}
boot();
})();
