import sys, os, shutil
root = sys.argv[1]
bk = os.path.join(root, "backup-v4"); os.makedirs(os.path.join(bk, "static"), exist_ok=True)
for f in ("server.py", "static/app.js"):
    d = os.path.join(bk, f)
    if not os.path.exists(d): shutil.copy2(os.path.join(root, f), d)
def patch(path, reps):
    p = os.path.join(root, path); s = open(p, encoding="utf-8").read()
    for a, b, n in reps:
        c = s.count(a)
        if c != n: sys.exit(f"{path}: expected {n} of {a[:70]!r}, found {c}")
        s = s.replace(a, b)
    open(p, "w", encoding="utf-8", newline="").write(s); print("patched", path, len(reps))

# ---------------- server.py ----------------
patch("server.py", [
('ENGINE_MODEL = "qwen3.8-27b-hauhaucs-iq3xs"\n',
 '''# RDNA4 engine models: one at a time on the engine port; each Start script stops the other one first.
ENGINE_MODELS = [
    {"key": "27b", "id": "qwen3.8-27b-hauhaucs-iq3xs", "name": "Qwen3.8 27B \\u00b7 IQ3_XS", "short": "27B", "quant": "IQ3_XS", "start": "Start-Qwen27B.ps1",
     "vram_gb": 13, "speed": "~100 tok/s", "expect": 32, "vision": True, "efforts": ["off", "low", "medium", "high"]},
    {"key": "9b", "id": "qwen3.5-9b-hauhaucs-q6k", "name": "Qwen3.5 9B \\u00b7 Q6_K", "short": "9B", "quant": "Q6_K", "start": "Start-Qwen9B.ps1",
     "vram_gb": 8, "speed": "~155 tok/s", "expect": 24, "vision": True, "efforts": ["off", "low", "medium", "high"]},
]
ENGINE_MODEL = ENGINE_MODELS[0]["id"]
def engine_model(key=None, mid=None): return next((m for m in ENGINE_MODELS if m["key"] == key or m["id"] == mid), None)
def engine_running():
    st = engine_status()
    return next((m for m in ENGINE_MODELS if st["online"] and m["id"] in st["models"]), None)
''', 1),
('''    return {"engine": {**eng, "id": ENGINE_MODEL, "name": "Qwen3.8 27B \u00b7 IQ3_XS", "vision": True, "efforts": ["off", "low", "medium", "high"]},''',
 '''    engines = [{**m, "online": bool(eng["online"] and m["id"] in eng["models"])} for m in ENGINE_MODELS]
    return {"engine": {**eng, "id": ENGINE_MODEL, "name": "Qwen3.8 27B \u00b7 IQ3_XS", "vision": True, "efforts": ["off", "low", "medium", "high"]}, "engines": engines,''', 1),
('JOB = {"id": 0, "kind": None, "label": "",', 'JOB = {"id": 0, "kind": None, "target": None, "label": "",', 1),
('def start_job(kind, label, fn, expect):', 'def start_job(kind, label, fn, expect, target=None):', 1),
('JOB.update(id=JOB["id"] + 1, kind=kind, label=label,', 'JOB.update(id=JOB["id"] + 1, kind=kind, target=target, label=label,', 1),
('''            if wait_engine is True and engine_status()["online"]: return None
            if code is not None:
                if wait_engine is True: return None if engine_status()["online"] else f"{name} exited ({code})"''',
 '''            if wait_engine and engine_ready(wait_engine): return None
            if code is not None:
                if wait_engine: return None if engine_ready(wait_engine) else f"{name} exited ({code})"''', 1),
('def lm_load(key, ctx):', '''def engine_ready(want):  # want: True (any engine model) or a model id (that model must be the one serving)
    st = engine_status()
    return st["online"] and (want is True or want in st["models"])
def lm_load(key, ctx):''', 1),
('''        if action == "engine_start":
            ok = start_job(action, "Starting the 27B (unloads LM Studio models)", lambda: run_script("Start-Qwen27B.ps1", "-UnloadLMStudio", wait_engine=True), 32)
        elif action == "engine_stop":
            ok = start_job(action, "Stopping the 27B", lambda: run_script("Stop-Qwen27B.ps1"), 4)''',
 '''        if action == "engine_start":
            em = engine_model(key or "27b")
            if not em: return self.send_json(400, {"error": "unknown engine model"})
            cur = engine_running()
            if cur and cur["id"] == em["id"]: return self.send_json(409, {"error": f"the {em['short']} is already running"})
            label = f"Switching to the {em['short']} (stops the {cur['short']})" if cur else f"Starting the {em['short']} (unloads LM Studio models)"
            ok = start_job(action, label, lambda: run_script(em["start"], "-UnloadLMStudio", wait_engine=em["id"]), em["expect"] + (6 if cur else 0), target=em["id"])
        elif action == "engine_stop":
            cur = engine_running()
            ok = start_job(action, f"Stopping the {cur['short'] if cur else 'engine model'}", lambda: run_script("Stop-Qwen27B.ps1"), 4, target=cur["id"] if cur else None)''', 1),
('"error": "the 27B is running and uses most of the VRAM - stop it first"', '"error": "an engine model (27B/9B) is running and uses most of the VRAM - stop it first"', 1),
])

# ---------------- app.js ----------------
patch("static/app.js", [
('''  const e = models.engine;
  out.push({ backend: 'engine', id: ENGINE_ID, label: 'Qwen3.8 27B', sub: 'IQ3_XS · RDNA4 engine', online: !!e.online, vision: true, think: 'full' });''',
 '''  const engs = models.engines || [{ key: '27b', id: ENGINE_ID, name: 'Qwen3.8 27B', short: '27B', quant: 'IQ3_XS', online: !!models.engine.online, vision: true }];
  for (const e of engs) out.push({ backend: 'engine', id: e.id, key: e.key, short: e.short, quant: e.quant, label: e.name.split(' · ')[0], sub: e.quant + ' · RDNA4 engine', online: !!e.online, vision: !!e.vision, think: 'full' });''', 1),
("el.modelSub.textContent = s ? (s.backend === 'engine' ? '27B · RDNA4' : 'LM Studio') : '';",
 "el.modelSub.textContent = s ? (s.backend === 'engine' ? (s.short || '27B') + ' · RDNA4' : 'LM Studio') : '';", 1),
("  if (o.backend === 'engine') toggleEngine(true); else toggleLM(o.id, true);",
 "  if (o.backend === 'engine') toggleEngine(true, o.id); else toggleLM(o.id, true);", 1),
("""      const ok = await confirmModal('Stop the 27B first?', 'The 27B is using most of the GPU memory. Stop it before loading LM Studio models?', 'Stop 27B', 'thinking');""",
 """      const cur = engineOn(); const nm = cur ? cur.short : 'engine model';
      const ok = await confirmModal(`Stop the ${nm} first?`, `The ${nm} (RDNA4 engine) is using most of the GPU memory. Stop it before loading LM Studio models?`, `Stop ${nm}`, 'thinking');""", 1),
("""async function toggleEngine(on) {
  if (on) {
    const lmLoaded = (models && models.lmstudio.models || []).filter(m => m.loaded).map(m => m.name);
    const ok = await confirmModal('Start Qwen3.8 27B?', `It needs ~13 GB of VRAM, so all LM Studio models get unloaded${lmLoaded.length ? ' (' + lmLoaded.join(', ') + ')' : ''}. Turning the 27B off later won't reload them — switch them back on here when you need them.`, 'Start 27B', 'thinking');
    if (ok) startJob({ action: 'engine_start' });
  } else {
    if (await confirmModal('Stop the 27B?', 'Frees ~13 GB of VRAM. LM Studio models stay unloaded until you switch them on.', 'Stop', 'idle')) startJob({ action: 'engine_stop' });
  }
  renderModels();
}""",
 """function engineList() { return (models && models.engines) || []; }
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
}""", 1),
("toast(job.label.replace(/^(Starting|Stopping|Loading|Unloading)/, m => ({ Starting: 'Started', Stopping: 'Stopped', Loading: 'Loaded', Unloading: 'Unloaded' })[m]).replace(/ \\(unloads LM Studio models\\)/, ''), 'ok');",
 "toast(job.label.replace(/^(Starting|Stopping|Loading|Unloading|Switching)/, m => ({ Starting: 'Started', Stopping: 'Stopped', Loading: 'Loaded', Unloading: 'Unloaded', Switching: 'Switched' })[m]).replace(/ \\((unloads LM Studio models|stops the [^)]*)\\)/, ''), 'ok');", 1),
("      if (job.kind === 'engine_start') { const o = modelOptions().find(x => x.backend === 'engine'); if (o) useModel(o, true); }",
 "      if (job.kind === 'engine_start') { const o = modelOptions().find(x => x.backend === 'engine' && (x.id === job.target || !job.target) && x.online) || modelOptions().find(x => x.backend === 'engine' && x.id === job.target); if (o) useModel(o, true); }", 1),
("'ie-serve': '27B engine (ie-serve)'", "'ie-serve': 'RDNA4 engine (ie-serve)'", 1),
("""  const busy = k => run && ((k === 'engine' && /^engine_/.test(job.kind)) || (job.kind && job.kind.startsWith('lm_') && job.label.includes(k)));""",
 """  const busy = k => run && ((k.startsWith('engine:') && /^engine_/.test(job.kind) && (!job.target || job.target === k.slice(7) || (job.kind === 'engine_start' && (engineOn() || {}).id === k.slice(7)))) || (job.kind && job.kind.startsWith('lm_') && job.label.includes(k)));""", 1),
("""  h += `<div class="sec-title">RDNA4 engine</div>
  <div class="card${s && s.backend === 'engine' ? ' hl' : ''}"><div class="card-row"><div class="nm"><b>Qwen3.8 27B · IQ3_XS</b><small>${e.online ? '● Online · ~110 tok/s' : '○ Off'} · ctx 8K · MTP · vision</small></div>
    ${tg(e.online, 'data-eng', busy('engine'))}</div>
    <div class="tags"><span class="tag">Uncensored</span><span class="tag">Thinking: Off/Low/Med/High</span><span class="tag">~13 GB VRAM</span></div>
    ${!e.online ? '<div class="warn">Turning it on unloads every LM Studio model to free VRAM. They aren’t reloaded automatically when it’s turned off.</div>' : ''}
    <div class="acts">${e.online && !(s && s.backend === 'engine') ? '<button class="btn-sm primary" data-use="engine">Use for chat</button>' : ''}${e.online && s && s.backend === 'engine' ? '<span class="status">✓ In use for chat</span>' : ''}</div></div>`;""",
 """  const engs = engineList(), anyOn = engineOn();
  h += `<div class="sec-title">RDNA4 engine <small style="font-weight:400;opacity:.7">· one model at a time</small></div>`;
  for (const em of engs) {
    const inUse = s && s.backend === 'engine' && s.id === em.id;
    h += `<div class="card${inUse ? ' hl' : ''}"><div class="card-row"><div class="nm"><b>${esc(em.name)}</b><small>${em.online ? '● Online · ' + esc(em.speed) : '○ Off'} · ctx 8K · MTP · vision</small></div>
    ${tg(em.online, `data-eng="${esc(em.key)}"`, busy('engine:' + em.id))}</div>
    <div class="tags"><span class="tag">Uncensored</span><span class="tag">Thinking: Off/Low/Med/High</span><span class="tag">~${em.vram_gb} GB VRAM</span></div>
    ${!em.online ? `<div class="warn">${anyOn ? `Turning it on stops the ${esc(anyOn.short)} first (one engine model at a time). ` : ''}LM Studio models get unloaded to free VRAM and aren’t reloaded automatically when it’s turned off.</div>` : ''}
    <div class="acts">${em.online && !inUse ? `<button class="btn-sm primary" data-use="engine:${esc(em.id)}">Use for chat</button>` : ''}${em.online && inUse ? '<span class="status">✓ In use for chat</span>' : ''}</div></div>`;
  }""", 1),
("""  if (t.hasAttribute('data-eng')) return toggleEngine(!t.classList.contains('on'));""",
 """  if (t.hasAttribute('data-eng')) return toggleEngine(!t.classList.contains('on'), t.dataset.eng);""", 1),
("""  if (t.dataset.use) { const o = modelOptions().find(x => t.dataset.use === 'engine' ? x.backend === 'engine' : x.id === t.dataset.use);""",
 """  if (t.dataset.use) { const u = t.dataset.use, o = modelOptions().find(x => u.startsWith('engine:') ? x.backend === 'engine' && x.id === u.slice(7) : x.backend === 'lmstudio' && x.id === u);""", 1),
("pick a vision model (27B or a “vision” LM Studio model)", "pick a vision model (an engine model or a “vision” LM Studio model)", 1),
("modelLabel: model.label + (model.backend === 'engine' ? ' · IQ3_XS' : '')", "modelLabel: model.label + (model.backend === 'engine' ? ' · ' + (model.quant || 'IQ3_XS') : '')", 1),
("Automatic (27B if running, else a loaded LM Studio model)", "Automatic (the engine model if running, else a loaded LM Studio model)", 1),
("The 27B has an 8K context, so long chats", "Engine models have an 8K context, so long chats", 1),
("<b>27B engine</b><span>Off = no thinking.", "<b>RDNA4 engine (27B, 9B)</b><span>Off = no thinking.", 1),
("<b>LM Studio</b><span>Qwen3.5 9B: thinking on/off only", "<b>LM Studio</b><span>Qwen3.5 9B in LM Studio: thinking on/off only", 1),
])
