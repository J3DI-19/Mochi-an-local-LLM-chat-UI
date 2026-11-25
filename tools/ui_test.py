"""End-to-end UI test for Local AI Chat v2 using headless Chromium (Edge/Chrome) over the DevTools protocol. Python stdlib only.
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
WAIT_DONE = """new Promise(r=>{const t0=Date.now();const f=()=>{const s=document.querySelector('#sendBtn');if(!s.classList.contains('stop')||Date.now()-t0>%d)return r(Date.now()-t0);setTimeout(f,150)};setTimeout(f,300)})"""
LAST = """(()=>{const m=[...document.querySelectorAll('.msg.bot')].pop();return m?{text:m.querySelector('.content').innerText.slice(0,500),think:!m.querySelector('.think').hidden,thinkLen:m.querySelector('.tbody').textContent.length,stats:[...m.querySelectorAll('.stat')].map(x=>x.innerText).join(' | '),err:m.querySelector('.errbox').innerText}:null})()"""
def login(c, url=None):
    c.go(url or A.url, 2.5)
    st = c.js("fetch('/api/auth/state').then(r=>r.json())")
    if st["authed"]: return "already authed (local no-login)" if not st["session"] else "session"
    mode = "setup" if not st["has_password"] else "login"
    c.js("(()=>{const p=document.querySelector('#authPw');p.value=%s;document.querySelector('#authPw2').value=%s;document.querySelector('#authForm').requestSubmit()})()" % (json.dumps(PW), json.dumps(PW)))
    time.sleep(2.5)
    return mode + ": " + ("ok" if c.js("!document.querySelector('#app').hidden") else "FAILED " + c.js("document.querySelector('#authErr').innerText"))
def ask(c, text, shot_mid=None, wait_ms=300000):
    c.js(f"""(()=>{{const i=document.querySelector('#input');i.value={json.dumps(text)};i.dispatchEvent(new Event('input'));document.querySelector('#sendBtn').click()}})()""")
    if shot_mid: time.sleep(shot_mid[1]); c.shot(shot_mid[0])
    ms = c.js(WAIT_DONE % wait_ms); time.sleep(0.8); r = c.js(LAST); r["ms"] = ms; return r
def use_model(c, backend, mid):
    return c.js(f"""(async()=>{{document.querySelector('#modelBtn').click();await {SLEEP % 400};
      const b=[...document.querySelectorAll('.mm-item')].find(x=>x.dataset.b==={json.dumps(backend)}&&x.dataset.id==={json.dumps(mid)});
      if(!b)return 'missing';b.click();await {SLEEP % 400};return document.querySelector('#modelName').innerText}})()""")
def effort(c, e): return c.js(f"(async()=>{{const sl=document.querySelector('#effortSlider');if(sl.getAttribute('aria-disabled')==='true')return 'disabled';sl.focus();sl.dispatchEvent(new KeyboardEvent('keydown',{{key:'Home',bubbles:true}}));for(let i=0;i<['off','low','medium','high'].indexOf('{e}');i++)sl.dispatchEvent(new KeyboardEvent('keydown',{{key:'ArrowRight',bubbles:true}}));await {SLEEP % 300};return document.querySelector('#effortNote').innerText}})()")
def wait_job(c, secs=300):
    return c.js("new Promise(r=>{const t0=Date.now();const f=()=>fetch('/api/models').then(x=>x.json()).then(j=>{if(j.job.state!=='running')return r(j.job.state+(j.job.error?': '+j.job.error:''));if(Date.now()-t0>%d)return r('timeout');setTimeout(f,1000)});setTimeout(f,800)})" % (secs * 1000))
def tab(c, name): c.js(f"(async()=>{{document.querySelector('#openSettings').click();await {SLEEP % 300};document.querySelector('[data-tab={name}]').click();await {SLEEP % 600}}})()")

USERTAB = []
try:
    c = connect(); desktop(c)
    for step in A.steps.split(","):
        print("==", step, flush=True)
        if step in ("setup", "login"): print("  ", login(c))
        elif step == "shots":
            c.go(A.url, 3); c.js("document.querySelector('#newChat').click()"); time.sleep(1); c.shot("v2-01-empty")
            c.js("(async()=>{document.querySelector('#openModels').click()})()"); time.sleep(4); c.shot("v2-02-models")
            c.js("document.querySelector('#sheetScrim').click()"); time.sleep(0.6)
            for t in ("look", "chat", "mochi", "net", "account", "keys"):
                tab(c, t); time.sleep(3 if t == "net" else 0.6); c.shot(f"v2-03-settings-{t}")
            c.js("document.querySelector('#sheetScrim').click()"); time.sleep(0.5)
            c.js("(()=>{document.querySelector('#modelBtn').click()})()"); time.sleep(0.6); c.shot("v2-04-model-menu"); c.js("document.body.click()")
            c.js("(()=>{const b=document.querySelector('.chat-item [data-menu]');if(b)b.click()})()"); time.sleep(0.5); c.shot("v2-05-chat-menu"); c.js("document.querySelector('#chatList').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))")
            c.js("(()=>{const s=document.querySelector('#search');s.value='python';s.dispatchEvent(new Event('input'))})()"); time.sleep(1); c.shot("v2-06-search")
            c.js("(()=>{const s=document.querySelector('#search');s.value='';s.dispatchEvent(new Event('input'))})()"); time.sleep(0.5)
            c.js("(()=>{const i=[...document.querySelectorAll('.chat-item')][0];if(i)i.click()})()"); time.sleep(1.5); c.shot("v2-07-chat")
            c.js("(async()=>{document.querySelector('[data-tab]');})()")
            print("  errors:", c.errors() or "none")
        elif step == "light":
            c.js("(()=>{document.querySelector('#themeBtn').click()})()"); time.sleep(0.8); c.shot("v2-08-chat-light"); c.js("document.querySelector('#themeBtn').click()"); time.sleep(0.5)
        elif step == "mobile":
            mobile(c); c.go(A.url, 3); c.shot("v2-m01-chat")
            c.js("document.querySelector('#sideToggle').click()"); time.sleep(0.8); c.shot("v2-m02-sidebar"); c.js("document.querySelector('#scrim').click()"); time.sleep(0.5)
            c.js("document.querySelector('#openModels').click()"); time.sleep(3.5); c.shot("v2-m03-models"); c.js("document.querySelector('#sheetScrim').click()"); time.sleep(0.6)
            tab(c, "net"); time.sleep(3); c.shot("v2-m04-settings-net"); c.js("document.querySelector('#sheetScrim').click()"); time.sleep(0.5)
            c.js("document.querySelector('#newChat').click()"); time.sleep(0.8); c.shot("v2-m05-empty")
            print("  errors:", c.errors() or "none"); desktop(c)
        elif step == "mlogin":
            # login screen at phone width in a fresh context
            c2 = new_session_tab(); mobile(c2); c2.go(A.url, 2.5); c2.shot("v2-m00-login"); c2.call("Page.close")
        elif step == "sync":
            print("  session A:", login(c))
            c2 = new_session_tab(); desktop(c2)
            print("  session B:", login(c2))
            tag = "sync-" + str(int(time.time()))
            cid = c.js(f"""(async()=>{{const id='sync'+Date.now().toString(36);const r=await fetch('/api/chats/'+id,{{method:'PUT',headers:{{'Content-Type':'application/json','X-Local-Chat':'1'}},body:JSON.stringify({{title:'{tag}',messages:[{{role:'user',content:'hello from session A'}}]}})}});return id}})()""")
            time.sleep(6.5)
            seen = c2.js(f"[...document.querySelectorAll('.chat-item')].some(x=>x.innerText.includes('{tag}'))")
            print("  B sees chat created by A within 6.5s:", seen)
            c2.js(f"(()=>{{const i=[...document.querySelectorAll('.chat-item')].find(x=>x.innerText.includes('{tag}'));i&&i.click()}})()"); time.sleep(1.5)
            c.js(f"""(async()=>{{const g=await (await fetch('/api/chats/{cid}')).json();g.messages.push({{role:'assistant',content:'reply added by session A'}});g.updated=Date.now();await fetch('/api/chats/{cid}',{{method:'PUT',headers:{{'Content-Type':'application/json','X-Local-Chat':'1'}},body:JSON.stringify(g)}})}})()""")
            time.sleep(6.5)
            print("  B's open chat updated live:", c2.js("document.querySelector('#messages').innerText.includes('reply added by session A')"))
            c2.js(f"(async()=>{{await fetch('/api/chats/{cid}',{{method:'PATCH',headers:{{'Content-Type':'application/json','X-Local-Chat':'1'}},body:JSON.stringify({{title:'{tag}-renamed',pinned:true}})}})}})()"); time.sleep(6.5)
            print("  A sees rename+pin from B:", c.js(f"(()=>{{const i=[...document.querySelectorAll('.chat-item')].find(x=>x.innerText.includes('{tag}-renamed'));return !!i&&!!i.querySelector('.pin')}})()"))
            r = c.js(f"fetch('/api/chats/{cid}/export?format=md').then(r=>r.text())"); print("  export md ok:", "hello from session A" in r)
            c.js(f"fetch('/api/chats/{cid}',{{method:'DELETE',headers:{{'X-Local-Chat':'1'}}}}).then(r=>r.status)"); time.sleep(6)
            print("  B list drops deleted chat:", not c2.js(f"[...document.querySelectorAll('.chat-item')].some(x=>x.innerText.includes('{tag}'))"))
            print("  errors A:", c.errors() or "none", " B:", c2.errors() or "none"); c2.call("Page.close")
        elif step.startswith("chat:"):
            _, backend, mid, eff = step.split(":")
            c.go(A.url, 3); c.js("document.querySelector('#newChat').click()"); time.sleep(0.5)
            print("  model:", use_model(c, backend, mid), "| effort:", effort(c, eff))
            r = ask(c, "A farmer has 17 sheep. All but 9 run away. How many are left? Answer with the number and one short sentence.", (f"v2-chat-{backend}-{eff}-mid", 2.5))
            print("  reply:", json.dumps(r, ensure_ascii=False)); c.shot(f"v2-chat-{backend}-{eff}-done")
            print("  errors:", c.errors() or "none")
        elif step.startswith("lmtoggle:"):
            key = step.split(":", 1)[1]
            c.go(A.url, 3); c.js("document.querySelector('#openModels').click()"); time.sleep(3)
            c.js(f"document.querySelector('[data-lm=\"{key}\"]').click()"); time.sleep(1)
            if c.js("document.querySelector('#modal').classList.contains('open')"): c.shot("v2-lm-confirm"); c.js("document.querySelector('#modalYes').click()")
            time.sleep(2); c.shot("v2-lm-loading"); print("  load:", wait_job(c)); time.sleep(3); c.shot("v2-lm-loaded")
            print("  loaded:", c.js(f"fetch('/api/models').then(r=>r.json()).then(j=>j.lmstudio.models.find(m=>m.key=='{key}').loaded)"))
            c.js(f"document.querySelector('[data-lm=\"{key}\"]').click()"); time.sleep(1)
            if c.js("document.querySelector('#modal').classList.contains('open')"): c.js("document.querySelector('#modalYes').click()")
            print("  unload:", wait_job(c)); time.sleep(2)
            print("  loaded after unload:", c.js(f"fetch('/api/models').then(r=>r.json()).then(j=>j.lmstudio.models.find(m=>m.key=='{key}').loaded)"))
            print("  errors:", c.errors() or "none")
        elif step.startswith("lmload:") or step.startswith("lmunload:"):
            act, key = step.split(":", 1); want = act == "lmload"
            c.go(A.url, 3); c.js("document.querySelector('#openModels').click()"); time.sleep(3)
            if c.js(f"document.querySelector('[data-lm=\"{key}\"]').classList.contains('on')") != want:
                c.js(f"document.querySelector('[data-lm=\"{key}\"]').click()"); time.sleep(1)
                if c.js("document.querySelector('#modal').classList.contains('open')"): c.shot(f"v2-{act}-confirm"); c.js("document.querySelector('#modalYes').click()")
                print("  ", act, wait_job(c)); time.sleep(2.5)
            c.shot(f"v2-{act}-{key}"); c.js("document.querySelector('#sheetScrim').click()")
            print("  errors:", c.errors() or "none")
        elif step in ("engine_on", "engine_off"):
            c.go(A.url, 3); c.js("document.querySelector('#openModels').click()"); time.sleep(3)
            on = c.js("document.querySelector('[data-eng]').classList.contains('on')")
            if on != (step == "engine_on"):
                c.js("document.querySelector('[data-eng]').click()"); time.sleep(1); c.shot(f"v2-{step}-confirm")
                c.js("document.querySelector('#modalYes').click()"); time.sleep(6); c.shot(f"v2-{step}-progress")
                print("  ", step, wait_job(c, 300)); time.sleep(4)
            c.shot(f"v2-{step}-done"); print("  models:", c.js("fetch('/api/models').then(r=>r.json()).then(j=>'engine='+j.engine.online+' loaded='+j.lmstudio.models.filter(m=>m.loaded).map(m=>m.key).join('+'))"))
            print("  errors:", c.errors() or "none")
        elif step.startswith("eng:"):
            # eng:<key>:on|off - the engine model's own toggle in the Models panel (switching stops the other one)
            _, key, want = step.split(":"); want = want == "on"
            c.go(A.url, 3); c.js("document.querySelector('#openModels').click()"); time.sleep(3)
            sel = json.dumps('[data-eng="' + key + '"]')
            if c.js(f"document.querySelector({sel}).classList.contains('on')") != want:
                c.js(f"document.querySelector({sel}).click()"); time.sleep(1)
                print("  confirm:", c.js("document.querySelector('#modal').innerText.replace(/\\s+/g,' ').slice(0,260)"))
                c.shot(f"v4-eng-{key}-{'on' if want else 'off'}-confirm"); c.js("document.querySelector('#modalYes').click()")
                time.sleep(5); c.shot(f"v4-eng-{key}-progress"); print("  job:", wait_job(c, 300)); time.sleep(4)
            c.shot(f"v4-eng-{key}-{'on' if want else 'off'}-done")
            print("  engines:", c.js("fetch('/api/models').then(r=>r.json()).then(j=>j.engines.map(e=>e.key+'='+e.online).join(' ')+' lm='+j.lmstudio.models.filter(m=>m.loaded).map(m=>m.key).join('+'))"))
            print("  picker:", c.js("document.querySelector('#modelName').innerText+' / '+document.querySelector('#modelSub').innerText"))
            print("  errors:", c.errors() or "none"); c.js("document.querySelector('#sheetScrim').click()")
        elif step.startswith("img:"):
            # img:<model id>:<png path> - attach an image through the real file input and ask about it (effort off)
            _, mid, img = step.split(":", 2)
            c.go(A.url, 3); c.js("document.querySelector('#newChat').click()"); time.sleep(0.5)
            print("  model:", use_model(c, "engine", mid), "| effort:", effort(c, "off"))
            doc = c.call("DOM.getDocument")["root"]["nodeId"]; nid = c.call("DOM.querySelector", nodeId=doc, selector="#fileInput")["nodeId"]
            c.call("DOM.setFileInputFiles", nodeId=nid, files=[img]); time.sleep(1.5)
            print("  attached:", c.js("document.querySelectorAll('#attachRow img, #attachRow .att').length"))
            r = ask(c, "Which region has the tallest bar in this chart, and what is its value? One short sentence.", (f"v4-img-mid", 2.0))
            print("  reply:", json.dumps(r, ensure_ascii=False)); c.shot("v4-img-done")
            print("  errors:", c.errors() or "none")
        # ---------------- v5: accounts, tiers, internet link ----------------
        elif step == "v5setup":  # the owner (skip login on this PC) creates the Master password in Settings > Account
            c.go(A.url, 3); st = c.js("fetch('/api/auth/state').then(r=>r.json())")
            print("  owner:", st.get("user", {}).get("username"), st.get("user", {}).get("tier"), "| skip:", st.get("skip"), "| has_password:", st.get("has_password"))
            if not st.get("has_password"):
                tab(c, "account"); c.shot("v5-01-account-owner")
                c.js("(()=>{document.querySelector('#pwNew').value=%s;document.querySelector('#pwNew2').value=%s;document.querySelector('#pwSetup').requestSubmit()})()" % (json.dumps(PW), json.dumps(PW)))
                time.sleep(2)
            print("  has_password now:", c.js("fetch('/api/auth/state').then(r=>r.json()).then(j=>j.has_password)"), "| errors:", c.errors() or "none")
        elif step == "v5masterlogin":  # turn 'skip login' off, sign in as Master through the login form, turn it back on
            c.go(A.url, 3); tab(c, "account")
            c.js("document.querySelector('.tg[data-k=nologin]').click()"); time.sleep(1.2)
            c.js("(async()=>{await fetch('/api/auth/logout',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:'{}'})})()"); time.sleep(0.5)
            c.go(A.url, 3); print("  login page shown:", c.js("!document.querySelector('#auth').hidden"), "| username field:", c.js("!document.querySelector('#authUserWrap').hidden")); c.shot("v5-02-login-local")
            c.js("(()=>{document.querySelector('#authUser').value='atharva';document.querySelector('#authPw').value=%s;document.querySelector('#authForm').requestSubmit()})()" % json.dumps(PW))
            time.sleep(3); st = c.js("fetch('/api/auth/state').then(r=>r.json())")
            print("  signed in:", st["authed"], st.get("user", {}).get("username"), st.get("user", {}).get("tier"), "| session:", st["session"], "| app shown:", c.js("!document.querySelector('#app').hidden"))
            tab(c, "account"); c.js("document.querySelector('.tg[data-k=nologin]').click()"); time.sleep(1.2)
            print("  skip login back on:", c.js("fetch('/api/auth/state').then(r=>r.json()).then(j=>j.localhost_no_login)"), "| errors:", c.errors() or "none")
            c.js("document.querySelector('#sheetScrim').click()")
        elif step.startswith("v5create:"):  # v5create:<lm model key> - Master creates a User and a Limited User in Settings > Accounts
            lm = step.split(":", 1)[1]
            c.go(A.url, 3); tab(c, "accounts"); time.sleep(1.5); c.shot("v5-03-accounts-empty")
            for name, tier in (("t5user", "user"), ("t5lim", "limited")):
                c.js("""(async()=>{document.querySelector('#anUser').value=%s;document.querySelector('#anPw').value=%s;
                    document.querySelector('#anTier button[data-v=%s]').click();document.querySelector('#accNew').requestSubmit()})()""" % (json.dumps(name), json.dumps(PW + "-" + name), tier))
                time.sleep(2)
            # Limited User: only the given LM Studio model, 2 messages a day, 64-token replies
            r = c.js("""(async()=>{const card=[...document.querySelectorAll('[data-aid]')].find(x=>x.querySelector('.nm b').innerText.startsWith('t5lim'));
                const d=card.querySelector('details');d.open=true;await %s;
                card.querySelectorAll('input[type=checkbox]').forEach(x=>x.checked=x.value===%s);
                card.querySelector('[data-lim=daily_cap]').value=2;card.querySelector('[data-lim=max_tokens]').value=64;card.querySelector('[data-acc-limsave]').click();await %s;
                return [...document.querySelectorAll('[data-aid] .nm b')].map(x=>x.innerText).join(', ')})()""" % (SLEEP % 300, json.dumps("lmstudio:" + lm), SLEEP % 1500))
            print("  accounts:", r); time.sleep(1); c.shot("v5-04-accounts-created")
            c.js("(()=>{const d=[...document.querySelectorAll('[data-aid] details')][0];if(d)d.open=true})()"); time.sleep(0.5); c.shot("v5-05-limited-limits")
            print("  limited:", c.js("fetch('/api/accounts').then(r=>r.json()).then(j=>JSON.stringify(j.accounts.filter(a=>a.tier==='limited').map(a=>a.limits)))"), "| errors:", c.errors() or "none")
        elif step.startswith("v5user:"):  # v5user:<lm model key> - a User in its own browser session
            lm = step.split(":", 1)[1]
            u = new_session_tab(); desktop(u); u.go(A.url, 2)
            print("  login:", u.js("fetch('/api/auth/login',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:JSON.stringify({username:'t5user',password:%s})}).then(r=>r.status)" % json.dumps(PW + "-t5user")))
            u.go(A.url, 3)
            print("  ui:", u.js("JSON.stringify({brand:document.querySelector('#brandSub').innerText,models:!document.querySelector('#openModels').hidden,vram:!document.querySelector('#vramMini').hidden,net:!document.querySelector('#tabNet').hidden,accounts:!document.querySelector('#tabAccounts').hidden,chats:document.querySelectorAll('.chat-item').length})"))
            probes = [("GET", "/api/accounts", None), ("POST", "/api/accounts", {"username": "evil", "password": "xxxxxxxxxx", "tier": "master"}), ("PATCH", "/api/accounts/u000000000000", {"tier": "master"}),
                      ("PUT", "/api/accounts/defaults", {"daily_cap": 999}), ("POST", "/api/jobs", {"action": "engine_start", "key": "9b"}), ("POST", "/api/jobs", {"action": "lm_unload", "key": lm}),
                      ("GET", "/api/vram", None), ("GET", "/api/lan", None), ("POST", "/api/lan", {"enabled": True}), ("POST", "/api/internet", {"enabled": True}), ("GET", "/api/internet", None),
                      ("POST", "/api/security", {"localhost_no_login": False}), ("POST", "/proxy/lmstudio/api/v1/models/load", {"model": lm}), ("POST", "/proxy/lmstudio/v1/embeddings", {"model": "x", "input": "a"})]
            res = u.js("Promise.all(%s.map(([m,p,b])=>fetch(p,{method:m,headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:b?JSON.stringify(b):undefined}).then(r=>m+' '+p+' '+r.status)))" % json.dumps(probes))
            print("  direct Master APIs as User:"); [print("    ", x) for x in res]
            print("  model:", use_model(u, "lmstudio", lm)); r = ask(u, "Reply with exactly: hello from user", wait_ms=120000)
            print("  chat:", json.dumps({k: r[k] for k in ("text", "stats", "err")}, ensure_ascii=False)); u.shot("v5-06-user-chat")
            u.js("document.querySelector('#modelBtn').click()"); time.sleep(0.6); u.shot("v5-07-user-model-menu"); u.js("document.body.click()")
            tab(u, "account"); time.sleep(0.8); u.shot("v5-08-user-account")
            print("  own chats:", u.js("fetch('/api/chats').then(r=>r.json()).then(j=>j.chats.length)"), "| errors:", u.errors() or "none")
            open(os.path.join(A.out, ".user_ctx"), "w").write("ok"); USERTAB.append(u)
        elif step.startswith("v5limited:"):  # v5limited:<allowed lm key>:<a model it may not use>
            _, lm, other = step.split(":", 2)
            l = new_session_tab(); desktop(l); l.go(A.url, 2)
            print("  login:", l.js("fetch('/api/auth/login',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:JSON.stringify({username:'t5lim',password:%s})}).then(r=>r.status)" % json.dumps(PW + "-t5lim")))
            l.go(A.url, 3)
            print("  model menu:", l.js("(async()=>{document.querySelector('#modelBtn').click();await %s;const x=[...document.querySelectorAll('.mm-item')].map(b=>b.dataset.b+':'+b.dataset.id);document.body.click();return x.join(', ')})()" % (SLEEP % 400)))
            print("  model:", use_model(l, "lmstudio", lm)); r = ask(l, "Write a 300-word story about a cat.", wait_ms=120000)
            print("  chat 1 (UI, 64-token cap):", json.dumps({k: r[k] for k in ("stats", "err")}, ensure_ascii=False), "| text chars:", len(r["text"])); l.shot("v5-09-limited-chat")
            post = "(b)=>fetch('/proxy/lmstudio/v1/chat/completions',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:JSON.stringify(b)}).then(async r=>{const j=await r.json().catch(()=>({}));return r.status+' '+(j.error||('completion_tokens='+(j.usage||{}).completion_tokens))})"
            print("  disallowed model:", l.js("(%s)({model:%s,messages:[{role:'user',content:'hi'}],max_tokens:20})" % (post, json.dumps(other))))
            print("  engine path:", l.js("fetch('/proxy/engine/v1/chat/completions',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:JSON.stringify({model:'qwen3.5-9b-hauhaucs-q6k',messages:[]})}).then(r=>r.status)"))
            print("  chat 2 (direct, asks 4000 tokens):", l.js("(%s)({model:%s,messages:[{role:'user',content:'Write a 500-word essay about rivers.'}],max_tokens:4000,temperature:0})" % (post, json.dumps(lm))))
            print("  chat 3 (over the daily cap of 2):", l.js("(%s)({model:%s,messages:[{role:'user',content:'hi'}],max_tokens:8})" % (post, json.dumps(lm))))
            r = ask(l, "hi again", wait_ms=60000); print("  chat 3 in the UI:", json.dumps({k: r[k] for k in ("text", "err")}, ensure_ascii=False)[:300]); l.shot("v5-10-limited-cap")
            tab(l, "account"); time.sleep(0.8); l.shot("v5-11-limited-account")
            print("  usage:", l.js("fetch('/api/auth/state').then(r=>r.json()).then(j=>JSON.stringify(j.limits))"), "| errors:", l.errors() or "none")
        elif step == "v5inactive":  # Master turns the User off in Settings > Accounts: its open session dies at once and it can't sign in
            c.go(A.url, 3); tab(c, "accounts"); time.sleep(1.5)
            c.js("(async()=>{const card=[...document.querySelectorAll('[data-aid]')].find(x=>x.querySelector('.nm b').innerText.startsWith('t5user'));card.querySelector('[data-acc-active]').click()})()")
            time.sleep(0.8); c.shot("v5-12-turnoff-confirm"); c.js("document.querySelector('#modalYes').click()"); time.sleep(2); c.shot("v5-13-user-off")
            print("  t5user active:", c.js("fetch('/api/accounts').then(r=>r.json()).then(j=>j.accounts.find(a=>a.username==='t5user').active)"))
            if USERTAB:
                u = USERTAB[0]
                print("  User's open session now signed in as:", u.js("fetch('/api/auth/state').then(r=>r.json()).then(j=>(j.user&&j.user.username)+(j.skip?' (PC skip-login fallback)':''))"))
                print("  User login again:", u.js("fetch('/api/auth/login',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:JSON.stringify({username:'t5user',password:%s})}).then(async r=>r.status+' '+(await r.json()).error)" % json.dumps(PW + "-t5user")))
                u.go(A.url, 3); print("  User tab now shows:", u.js("document.querySelector('#auth').hidden ? 'app as '+((document.querySelector('.brand')||{}).innerText||'').replace(/\\s+/g,' ').slice(0,40) : 'login page'"))
            print("  errors:", c.errors() or "none")
        elif step == "v5neton":  # Master turns the internet link on in Settings > Network
            c.go(A.url, 3); tab(c, "net"); time.sleep(2); c.shot("v5-14-network-off")
            c.js("document.querySelector('.tg[data-web=enabled]').click()"); time.sleep(0.8); c.shot("v5-15-internet-confirm"); c.js("document.querySelector('#modalYes').click()")
            t0 = time.time(); w = {}
            while time.time() - t0 < 60:
                w = c.js("fetch('/api/internet').then(r=>r.json())")
                if w.get("connected") or w.get("state") == "error": break
                time.sleep(1.5)
            print("  internet:", w.get("provider"), w.get("state"), "| connected:", w.get("connected"), "| url:", w.get("url"), "| after %.1fs" % (time.time() - t0), w.get("error") or "")
            if w.get("enable_url"):
                time.sleep(1.5); print("  enable link shown in UI:", c.js("(document.querySelector('.ts-enable a')||{}).href||'none'"))
            time.sleep(2.5); c.shot("v5-16-internet-on")
            print("  badge:", c.js("!document.querySelector('#webBadge').hidden"), "| errors:", c.errors() or "none")
            if w.get("url"): open(os.path.join(A.out, "public_url.txt"), "w").write(w["url"])
        elif step == "v5remote":  # the public link in a fresh browser: login page (no skip), sign in as Master, cookie is Secure
            url = open(os.path.join(A.out, "public_url.txt")).read().strip()
            r = new_session_tab(); desktop(r)
            for i in range(10):
                try: r.go(url, 4); ok = r.js("!!document.querySelector('#authForm')")
                except Exception: ok = False
                if ok: break
                time.sleep(3)
            st = r.js("fetch('/api/auth/state').then(r=>r.json())")
            print("  remote state:", json.dumps({k: st.get(k) for k in ("authed", "skip", "local", "tunnel", "has_password")}))
            print("  login page:", r.js("!document.querySelector('#auth').hidden"), "| app hidden:", r.js("document.querySelector('#app').hidden"), "| note:", r.js("document.querySelector('#authNote').innerText"))
            r.shot("v5-17-remote-login")
            print("  remote API without login:", r.js("Promise.all(['/api/chats','/api/accounts','/api/models'].map(p=>fetch(p).then(x=>p+' '+x.status)))"))
            r.js("(()=>{document.querySelector('#authUser').value='atharva';document.querySelector('#authPw').value='wrong-password';document.querySelector('#authForm').requestSubmit()})()"); time.sleep(2.5)
            print("  wrong password:", r.js("document.querySelector('#authErr').innerText"))
            r.js("(()=>{document.querySelector('#authUser').value='atharva';document.querySelector('#authPw').value=%s;document.querySelector('#authForm').requestSubmit()})()" % json.dumps(PW)); time.sleep(4)
            st = r.js("fetch('/api/auth/state').then(r=>r.json())")
            print("  signed in remotely:", st["authed"], st.get("user", {}).get("tier"), "| tunnel:", st.get("tunnel"), "| brand:", r.js("document.querySelector('#brandSub').innerText"))
            ck = [x for x in r.call("Network.getCookies", urls=[url]).get("cookies", []) if x["name"] == "lac_session"]
            print("  cookie:", {k: ck[0][k] for k in ("secure", "httpOnly", "sameSite")} if ck else "none")
            tab(r, "net"); time.sleep(2); print("  remote toggle disabled:", r.js("document.querySelector('.tg[data-web=enabled]').disabled")); r.shot("v5-18-remote-network")
            print("  remote POST /api/internet:", r.js("fetch('/api/internet',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:'{\"enabled\":false}'}).then(async x=>x.status+' '+(await x.json()).error)"))
            print("  remote POST /api/tailscale:", r.js("fetch('/api/tailscale',{method:'POST',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:'{\"action\":\"disconnect\"}'}).then(async x=>x.status+' '+(await x.json()).error)"))
            print("  remote sees Tailscale buttons:", r.js("document.querySelectorAll('[data-ts]').length"), "| provider switch disabled:", r.js("[...document.querySelectorAll('#webProv button')].every(b=>b.disabled)"))
            r.js("document.querySelector('#sheetScrim').click()"); time.sleep(0.5); r.shot("v5-19-remote-app")
            print("  errors:", r.errors() or "none")
        elif step == "v5netoff":
            c.go(A.url, 3); tab(c, "net"); time.sleep(2)
            c.js("document.querySelector('.tg[data-web=enabled]').click()"); time.sleep(3); c.shot("v5-20-internet-off")
            print("  internet:", c.js("fetch('/api/internet').then(r=>r.json()).then(j=>j.state+' '+j.url)"), "| errors:", c.errors() or "none")
        elif step == "v5cleanup":  # delete the test accounts in the UI
            c.go(A.url, 3); tab(c, "accounts"); time.sleep(1.5)
            for name in ("t5user", "t5lim"):
                c.js("(async()=>{const card=[...document.querySelectorAll('[data-aid]')].find(x=>x.querySelector('.nm b').innerText.startsWith(%s));if(card)card.querySelector('[data-acc-del]').click()})()" % json.dumps(name))
                time.sleep(0.8)
                if name == "t5user": c.shot("v5-21-delete-confirm")
                c.js("document.querySelector('#modalYes').click()"); time.sleep(2)
            print("  accounts left:", c.js("fetch('/api/accounts').then(r=>r.json()).then(j=>j.accounts.map(a=>a.username+'/'+a.tier).join(', '))")); c.shot("v5-22-accounts-after")
            print("  last Master protected:", c.js("fetch('/api/accounts').then(r=>r.json()).then(j=>fetch('/api/accounts/'+j.accounts[0].id,{method:'PATCH',headers:{'X-Local-Chat':'1','Content-Type':'application/json'},body:'{\"active\":false}'})).then(async r=>r.status+' '+(await r.json()).error)"))
            print("  errors:", c.errors() or "none")
        elif step.startswith("v6prov:"):  # pick the link type in Settings > Network
            pv = step.split(":", 1)[1]
            c.go(A.url, 3); tab(c, "net"); time.sleep(2.5)
            c.js("document.querySelector('#webProv button[data-v=%s]').click()" % pv); time.sleep(1)
            if c.js("document.querySelector('#modal').classList.contains('open')"): c.js("document.querySelector('#modalYes').click()")
            time.sleep(2.5); w = c.js("fetch('/api/internet').then(r=>r.json())")
            print("  chosen:", w.get("chosen"), "| ui:", c.js("(document.querySelector('#webProv .on')||{}).innerText"), "| errors:", c.errors() or "none"); c.shot("v6-prov-" + pv)
        elif step == "v6tsview":
            c.go(A.url, 3); tab(c, "net"); time.sleep(3)
            t = c.js("fetch('/api/internet').then(r=>r.json())").get("tailscale", {})
            print("  tailscale:", json.dumps({k: t.get(k) for k in ("installed", "state", "service", "host", "tailnet", "fixed_url", "version")}))
            print("  card:", c.js("(document.querySelector('.ts-card .nm small')||{}).innerText"), "| buttons:", c.js("[...document.querySelectorAll('[data-ts]')].map(b=>b.innerText).join(', ')"))
            c.js("document.querySelector('.ts-card').scrollIntoView({block:'center'})"); time.sleep(0.6); c.shot("v6-ts-card"); print("  errors:", c.errors() or "none")
        elif step.startswith("v6ts:"):  # Disconnect / Reconnect buttons (no admin)
            a = step.split(":", 1)[1]
            c.go(A.url, 3); tab(c, "net"); time.sleep(3)
            c.js("document.querySelector('[data-ts=%s]').click()" % a); time.sleep(1)
            if c.js("document.querySelector('#modal').classList.contains('open')"): c.js("document.querySelector('#modalYes').click()")
            t0 = time.time(); t = {}
            while time.time() - t0 < 60:
                time.sleep(1.5); t = c.js("fetch('/api/internet').then(r=>r.json())").get("tailscale", {})
                if not (t.get("action") or {}).get("busy"): break
            time.sleep(2.5)
            print("  %s ->" % a, t.get("state"), "|", json.dumps({k: (t.get("action") or {}).get(k) for k in ("ok", "msg")}), "| after %.1fs" % (time.time() - t0))
            print("  card:", c.js("(document.querySelector('.ts-card')||{}).innerText||''").replace("\n", " / ")[:240])
            c.js("document.querySelector('.ts-card').scrollIntoView({block:'center'})"); time.sleep(0.4); c.shot("v6-ts-" + a); print("  errors:", c.errors() or "none")
        elif step == "vram":
            print("  ", json.dumps(c.js("fetch('/api/vram').then(r=>r.json())")))
        elif step.startswith("shot:"):
            c.shot(step.split(":", 1)[1])
finally:
    br.terminate()
    try: br.wait(10)
    except Exception: br.kill()
    shutil.rmtree(prof, ignore_errors=True)
