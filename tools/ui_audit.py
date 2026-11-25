"""(harness copied from ui_test.py) End-to-end UI test for Local AI Chat v2 using headless Chromium (Edge/Chrome) over the DevTools protocol. Python stdlib only.
  set LAC_PW=<test password>   (read from the environment, never printed)
  python ui_test.py --browser "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --out shots --steps shots,mobile,sync
Steps: setup (create password via UI if none), login, shots, mobile, sync (two separate browser sessions), chat:<backend>:<model>:<effort>,
       lmtoggle:<key> (load then unload via the Models panel), lan (screenshot of the network tab),
       v5: v5setup, v5masterlogin, v5create:<lm key>, v5user:<lm key>, v5limited:<lm key>:<other model>, v5inactive, v5neton, v5remote, v5netoff, v5cleanup."""
import argparse, base64, json, os, socket, struct, subprocess, sys, tempfile, time, urllib.request, shutil

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8765/")
ap.add_argument("--browser", required=True); ap.add_argument("--out", default="shots"); ap.add_argument("--steps", default="login,shots")
ap.add_argument("--port", type=int, default=9333)
A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
PW = os.environ.get("LAC_PW", "")

class WS:
    def __init__(self, url):
        host, rest = url[5:].split("/", 1); h, p = host.split(":")
        self.s = socket.create_connection((h, int(p))); key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(f"GET /{rest} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf: buf += self.s.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
    def _read(self, n):
        while len(self.buf) < n:
            d = self.s.recv(1 << 20)
            if not d: raise ConnectionError("ws closed")
            self.buf += d
        r, self.buf = self.buf[:n], self.buf[n:]; return r
    def send(self, text):
        data = text.encode(); mask = os.urandom(4); hdr = bytearray([0x81])
        n = len(data)
        if n < 126: hdr.append(0x80 | n)
        elif n < 65536: hdr.append(0x80 | 126); hdr += struct.pack(">H", n)
        else: hdr.append(0x80 | 127); hdr += struct.pack(">Q", n)
        self.s.sendall(bytes(hdr) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
    def recv(self):
        msg = b""
        while True:
            b0, b1 = self._read(2); n = b1 & 0x7F
            if n == 126: n = struct.unpack(">H", self._read(2))[0]
            elif n == 127: n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n); op = b0 & 0x0F
            if op == 9: continue
            msg += payload
            if b0 & 0x80: return msg.decode("utf-8", "replace")

class CDP:
    def __init__(self, ws): self.ws = ws; self.i = 0; self.events = []
    def call(self, method, **params):
        self.i += 1; mid = self.i; self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == mid:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            self.events.append(m)
    def js(self, expr, await_=True):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_, returnByValue=True)
        if r.get("exceptionDetails"): raise RuntimeError("JS: " + json.dumps(r["exceptionDetails"])[:400])
        return r["result"].get("value")
    def shot(self, name):
        d = self.call("Page.captureScreenshot", format="png")["data"]
        p = os.path.join(A.out, name + ".png"); open(p, "wb").write(base64.b64decode(d)); print("  screenshot", p, flush=True)
    def go(self, url, settle=1.5):
        self.call("Page.navigate", url=url); time.sleep(settle)
    def errors(self):
        out = []
        for e in self.events:
            if e.get("method") == "Runtime.exceptionThrown": out.append("EXC " + json.dumps(e["params"]["exceptionDetails"])[:300])
            elif e.get("method") == "Runtime.consoleAPICalled" and e["params"]["type"] in ("error", "assert"): out.append("console.error " + json.dumps(e["params"]["args"])[:300])
            elif e.get("method") == "Log.entryAdded" and e["params"]["entry"]["level"] == "error": out.append("log " + e["params"]["entry"].get("text", "")[:300])
        self.events = []; return out


prof = tempfile.mkdtemp(prefix="lac-ui-")
br = subprocess.Popen([A.browser, "--headless=new", f"--remote-debugging-port={A.port}", f"--user-data-dir={prof}", "--no-first-run",
                       "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars", "--window-size=1440,900", "about:blank"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def connect(target_id=None):
    for _ in range(60):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{A.port}/json/list", timeout=1))
            page = [t for t in tabs if t["type"] == "page" and (target_id is None or t["id"] == target_id)][0]; break
        except Exception: time.sleep(0.5)
    c = CDP(WS(page["webSocketDebuggerUrl"]))
    for m in ("Page.enable", "Runtime.enable", "Log.enable"): c.call(m)
    return c
_bc = []
def browser_cdp():
    if not _bc:
        v = json.load(urllib.request.urlopen(f"http://127.0.0.1:{A.port}/json/version", timeout=2)); _bc.append(CDP(WS(v["webSocketDebuggerUrl"])))
    return _bc[0]
def new_session_tab():
    b = browser_cdp(); ctx = b.call("Target.createBrowserContext")["browserContextId"]
    t = b.call("Target.createTarget", url="about:blank", browserContextId=ctx)["targetId"]; return connect(t)
def desktop(c): c.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False); c.call("Emulation.setTouchEmulationEnabled", enabled=False)
def mobile(c): c.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True); c.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

SLEEP = "new Promise(r=>setTimeout(r,%d))"
# ---------------- layout audit of the right-hand panels ----------------
# Fake data for states that can't be produced safely for real (internet link on / error, many accounts). Client-side only: the page's fetch is stubbed.
LONG = "https://a-very-long-machine-name-for-testing.tail79b51f-example.ts.net/"
STUBS = {
  "net-on": {"/api/internet": {"state": "on", "url": LONG, "connected": True, "error": "", "autostart": True, "installed": True, "has_password": True, "since": 1, "provider": "tailscale", "chosen": "tailscale", "enable_url": "", "cf_installed": True,
             "tailscale": {"installed": True, "state": "Running", "host": LONG[8:-1], "online": True, "tailnet": "someone.with-a-long-github-name.github", "service": "running", "version": "1.104.7", "fixed_url": LONG, "action": {"busy": "", "msg": "connected", "ok": True, "t": 9e12}}}},
  "net-err": {"/api/internet": {"state": "error", "url": "", "connected": False, "error": "Funnel is not enabled on your tailnet.", "autostart": False, "installed": True, "has_password": True, "since": 0, "provider": "tailscale", "chosen": "tailscale",
             "enable_url": "https://login.tailscale.com/f/funnel?node=nK7RDRYP1Y11CNTRL", "cf_installed": True,
             "tailscale": {"installed": True, "state": "Stopped", "host": "athereal.tail79b51f.ts.net", "online": False, "tailnet": "j3di-19.github", "service": "running", "version": "1.104.7", "fixed_url": "https://athereal.tail79b51f.ts.net/", "action": {"busy": "", "msg": "Tailscale needs you to sign in again: open the link below", "ok": False, "auth_url": "https://login.tailscale.com/a/abcdef0123456789", "t": 9e12}}}},
}
def acc_stub():
    now = time.time()
    def u(i, name, tier, active=True, lim=None):
        d = {"id": "u%012x" % i, "username": name, "tier": tier, "active": active, "created": now - i * 1000, "has_password": True, "last_login": now - 300, "me": i == 1}
        if lim: d["limits"] = lim
        return d
    return {"accounts": [u(1, "atharva", "master"), u(2, "a.really-long-username_32chars", "user"), u(3, "guest-phone", "limited", True, {"models": ["lmstudio:qwen3-4b-instruct-2507"], "daily_cap": 50, "max_tokens": 1024, "used_today": 12}),
                         u(4, "old.account", "user", False)],
            "defaults": {"models": [], "daily_cap": 50, "max_tokens": 1024},
            "model_choices": [{"key": "engine:qwen3.6-27b-iq3xxs-mtp-very-long-model-name", "label": "Qwen3.6 27B · IQ3_XXS · MTP draft (RDNA4 engine, very long name)", "online": False},
                              {"key": "lmstudio:qwen3-4b-instruct-2507", "label": "Qwen3 4B Instruct 2507 (LM Studio)", "online": True},
                              {"key": "lmstudio:qwen3.5-9b-uncensored-hauhaucs-aggressive", "label": "Qwen3.5 9B Uncensored HauhauCS Aggressive (LM Studio)", "online": False}],
            "tiers": {}}
STUBS["accounts"] = {"/api/accounts": acc_stub()}
STUB_JS = """(()=>{let S=null;try{S=JSON.parse(sessionStorage.getItem('__stub')||'null')}catch(e){}if(!S)return;const of=window.fetch.bind(window);
window.fetch=(u,o)=>{const p=String(u).split('?')[0];if(S[p]&&(!o||!o.method||o.method==='GET'))return Promise.resolve(new Response(JSON.stringify(S[p]),{status:200,headers:{'Content-Type':'application/json'}}));return of(u,o)}})()"""

AUDIT_JS = r"""(()=>{
const sheet=[...document.querySelectorAll('.sheet.open')][0]; if(!sheet) return {err:'no open sheet'};
const body=sheet.querySelector('.sheet-body'), br=body.getBoundingClientRect(), sr=sheet.getBoundingClientRect();
const vis=e=>{const cs=getComputedStyle(e);if(cs.display==='none'||cs.visibility==='hidden'||+cs.opacity===0)return false;const r=e.getBoundingClientRect();return r.width>0.5&&r.height>0.5};
const ownText=e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim());
const name=e=>{let s=e.tagName.toLowerCase();if(e.id)s+='#'+e.id;if(e.classList.length)s+='.'+[...e.classList].slice(0,2).join('.');const t=(e.innerText||e.value||'').trim().replace(/\s+/g,' ').slice(0,28);return s+(t?' "'+t+'"':'')};
const issues=[];const add=(k,m)=>{if(issues.length<80)issues.push(k+': '+m)};
// whole body scroll to measure everything
const all=[...sheet.querySelectorAll('*')].filter(vis);
const INTER='button,a,input,select,textarea,.tg,summary,label.switch,.seg';
const cand=all.filter(e=>!e.closest('svg')&&!e.classList.contains('seg-pill')&&(e.matches(INTER)||ownText(e)||e.matches('code,kbd,.dot,.acc-av,.tier-badge,.qrbox,img,canvas,.vm-bar'))&&!(e.parentElement&&e.parentElement.closest(INTER)&&!e.matches(INTER)));
// 1) horizontal overflow outside the panel / its card
for(const e of cand){const r=e.getBoundingClientRect();
  if(e.closest('.tabs'))continue;
  if(r.right>sr.right+0.5||r.left<sr.left-0.5)add('OUTSIDE-PANEL',name(e)+' x='+Math.round(r.left-sr.left)+'..'+Math.round(r.right-sr.left)+' panel w='+Math.round(sr.width));
  const card=e.parentElement&&e.parentElement.closest('.card,.mcard,.acc-card');
  if(card&&card!==e){const c=card.getBoundingClientRect();if(r.right>c.right+0.5||r.left<c.left-0.5)add('OUTSIDE-CARD',name(e)+' sticks out of '+name(card).slice(0,40)+' by '+Math.round(Math.max(r.right-c.right,c.left-r.left))+'px')}}
// 2) clipped / truncated text
for(const e of all){if(e.closest('svg')||e.matches('input,textarea,select'))continue;const cs=getComputedStyle(e);
  if(e.scrollWidth>e.clientWidth+1&&e.clientWidth>0&&(cs.overflowX==='hidden'||cs.overflowX==='clip')&&ownText(e))add(cs.textOverflow==='ellipsis'?'TRUNCATED':'CLIPPED',name(e)+' needs '+e.scrollWidth+'px has '+e.clientWidth)}
const tabs=sheet.querySelector('.tabs');if(tabs&&tabs.scrollWidth>tabs.clientWidth+1)add('TABS-SCROLL','tab bar needs '+tabs.scrollWidth+'px has '+tabs.clientWidth+' (some tabs hidden)');
for(const e of all){if(e.closest('svg'))continue;if(document.documentElement.scrollWidth>innerWidth+1){add('PAGE-HSCROLL','page is '+document.documentElement.scrollWidth+'px wide');break}}
// 3) overlaps & cramped neighbours
const inBody=e=>body.contains(e), visR=r=>!(r.bottom<=br.top+1||r.top>=br.bottom-1);
const boxes=e=>getComputedStyle(e).display==='inline'?[...e.getClientRects()]:[e.getBoundingClientRect()];
const pool=cand.filter(e=>!inBody(e)||visR(e.getBoundingClientRect()));
for(let i=0;i<pool.length;i++){const a=pool[i],ra=a.getBoundingClientRect(),ba=boxes(a);
  for(let j=i+1;j<pool.length;j++){const b=pool[j];if(a.contains(b)||b.contains(a))continue;const rb=b.getBoundingClientRect();
    if(inBody(a)!==inBody(b))continue;  // body content scrolling under the sticky header is expected
    const ix=Math.min(ra.right,rb.right)-Math.max(ra.left,rb.left),iy=Math.min(ra.bottom,rb.bottom)-Math.max(ra.top,rb.top);
    let hit=null;if(ix>1.5&&iy>1.5){for(const x of ba)for(const y of boxes(b)){const jx=Math.min(x.right,y.right)-Math.max(x.left,y.left),jy=Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top);if(jx>1.5&&jy>1.5)hit=[jx,jy]}}
    if(hit){add('OVERLAP',name(a)+' <> '+name(b)+' ('+Math.round(hit[0])+'x'+Math.round(hit[1])+')')}
    else if(a.matches(INTER)&&b.matches(INTER)&&iy>4&&ix>-4&&ix<=1.5&&!a.closest('.seg')&&!b.closest('.seg')&&!a.closest('.tabs'))add('CRAMPED',name(a)+' | '+name(b)+' gap '+Math.round(-ix)+'px')}}
// toasts / banners on top of the open panel
for(const t of document.querySelectorAll('.toast')){if(!vis(t))continue;const r=t.getBoundingClientRect();const ix=Math.min(r.right,sr.right)-Math.max(r.left,sr.left),iy=Math.min(r.bottom,sr.bottom)-Math.max(r.top,sr.top);if(ix>1&&iy>1)add('TOAST-OVER-PANEL',name(t)+' covers '+Math.round(ix)+'x'+Math.round(iy)+'px of the panel')}
// 4) small tap targets on phones
if(innerWidth<600)for(const e of cand)if(e.matches('button,a,.tg,select,input')&&!e.closest('.tabs,.es-labels')){const r=e.getBoundingClientRect();if(r.height<28)add('SMALL-TAP',name(e)+' h='+Math.round(r.height))}
return {issues,panel:Math.round(sr.width),scroll:body.scrollHeight,view:body.clientHeight,head_sticky:getComputedStyle(sheet.querySelector('.sheet-head')).position};
})()"""

SIZES = [("1280", 1280, 800, False), ("1440", 1440, 900, False), ("1920", 1920, 1080, False), ("phone", 390, 844, True)]
SECTIONS = [("look", None), ("chat", None), ("mochi", None), ("net", None), ("net-on", "net-on"), ("net-err", "net-err"), ("account", None), ("accounts", "accounts"), ("keys", None), ("models", None)]
import re as _re
only = [s for s in A.steps.split(",") if s] if A.steps not in ("login,shots",) else []
total = {}
try:
    c = connect()
    c.call("Page.addScriptToEvaluateOnNewDocument", source=STUB_JS)
    for sz, w, h, mob in SIZES:
        if mob: c.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=2, mobile=True)
        else: c.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
        for sec, stub in SECTIONS:
            if only and sec not in only: continue
            c.go("about:blank", 0.2)
            c.go(A.url, 0.1); c.js("sessionStorage.setItem('__stub', %s)" % json.dumps(json.dumps(STUBS[stub]) if stub else "null")); c.go(A.url, 2.8)
            if sec == "models": c.js("(async()=>{document.querySelector('#openModels').click();await %s})()" % (SLEEP % 1500))
            else: c.js("(async()=>{document.querySelector('#openSettings').click();await %s;document.querySelector('[data-tab=%s]').click();await %s})()" % (SLEEP % 400, sec.split('-')[0], SLEEP % 1200))
            if sec == "accounts": c.js("(()=>{const d=document.querySelector('.acc-card details.acc-lim');if(d)d.open=true})()")
            time.sleep(1.4)
            r = c.js(AUDIT_JS)
            iss = r.get("issues", []) if isinstance(r, dict) else [str(r)]
            errs = [e for e in c.errors() if "Failed to load resource" not in e]
            total[(sz, sec)] = len([i for i in iss if not i.startswith("TRUNCATED")])
            print(f"== {sz} {sec}: panel {r.get('panel')}px, content {r.get('scroll')}/{r.get('view')}px, {len(iss)} findings, JS errors: {errs or 'none'}", flush=True)
            for i in iss: print("   ", i)
            c.shot(f"{sz}-{sec}")
            if r.get("scroll", 0) > r.get("view", 0) + 40:  # also the bottom of long sections
                c.js("(()=>{const b=document.querySelector('.sheet.open .sheet-body');b.scrollTop=b.scrollHeight})()"); time.sleep(0.6); c.shot(f"{sz}-{sec}-bottom")
                r2 = c.js(AUDIT_JS)
                for i in r2.get("issues", []):
                    if i not in iss: print("    (bottom)", i)
    print("SUMMARY (non-truncation findings):", sum(total.values()), json.dumps({f"{a}/{b}": n for (a, b), n in total.items() if n}))
finally:
    br.terminate()
    try: br.wait(10)
    except Exception: br.kill()
