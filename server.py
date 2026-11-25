"""Local AI Chat v2 - stdlib-only server for the chat UI (ATHEREAL).

Serves ./static, proxies the OpenAI API of the 27B engine (127.0.0.1:8080) and LM Studio (127.0.0.1:1234) with SSE pass-through,
and adds: login (PBKDF2 + HttpOnly SameSite=Strict session cookies, rate limited), server-side chats/settings in ./data,
a models panel (LM Studio REST load/unload, the fixed engine Start/Stop scripts), a VRAM monitor (Windows perf counters),
LAN mode (0.0.0.0, private RFC1918 clients only, login always required), a per-user autostart entry (HKCU Run),
accounts with tiers (Master / User / Limited User; data/accounts.json) and an optional internet link through a free
Cloudflare Quick Tunnel (cloudflared, no account; login always required, never "skip login").
No user input is ever executed: the only programs run are the fixed bench-config scripts, cloudflared with fixed arguments
and fixed PowerShell perf-counter / firewall-status / process queries.
"""
import argparse, atexit, base64, hashlib, hmac, http.client, ipaddress, json, os, re, secrets, shutil, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, quote
import mochi_tools

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA = os.path.join(HERE, "data")
CHATS = os.path.join(DATA, "chats")
LOGS = os.path.join(HERE, "logs")
BENCH = os.path.normpath(os.path.join(HERE, "..", "bench-config"))
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--engine", default="127.0.0.1:8080")
ap.add_argument("--lmstudio", default="127.0.0.1:1234")
ap.add_argument("--log", default=None)
ap.add_argument("--lan", action="store_true", help="start in LAN mode (used by the autostart entry; needs a password)")
ARGS = ap.parse_args()
UP = {"engine": ARGS.engine, "lmstudio": ARGS.lmstudio}
PORT = ARGS.port
# RDNA4 engine models: one at a time on the engine port; each Start script stops the other one first.
ENGINE_MODELS = [
    {"key": "27b", "id": "qwen3.8-27b-hauhaucs-iq3xs", "name": "Qwen3.8 27B \u00b7 IQ3_XS", "short": "27B", "quant": "IQ3_XS", "start": "Start-Qwen27B.ps1",
     "vram_gb": 13, "speed": "~100 tok/s", "expect": 32, "vision": True, "efforts": ["off", "low", "medium", "high"]},
    {"key": "9b", "id": "qwen3.5-9b-hauhaucs-q6k", "name": "Qwen3.5 9B \u00b7 Q6_K", "short": "9B", "quant": "Q6_K", "start": "Start-Qwen9B.ps1",
     "vram_gb": 8, "speed": "~155 tok/s", "expect": 24, "vision": True, "efforts": ["off", "low", "medium", "high"]},
]
ENGINE_MODEL = ENGINE_MODELS[0]["id"]
def engine_model(key=None, mid=None): return next((m for m in ENGINE_MODELS if m["key"] == key or m["id"] == mid), None)
def engine_running():
    st = engine_status()
    return next((m for m in ENGINE_MODELS if st["online"] and m["id"] in st["models"]), None)
RUN_KEY, RUN_NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "LocalAIChatLAN"
FW_RULE = "Local AI Chat (LAN TCP 8765)"
MAX_BODY = 64 * 1024 * 1024
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json", ".webmanifest": "application/manifest+json"}
for d in (DATA, CHATS, LOGS): os.makedirs(d, exist_ok=True)
LOCK = threading.RLock()

def log(msg): sys.stderr.write(time.strftime("%H:%M:%S ") + msg + "\n")
def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return default
def jsave(path, obj):
    with LOCK:
        tmp = f"{path}.{secrets.token_hex(4)}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass

# ---------------- config / accounts ----------------
CFG_PATH, AUTH_PATH, SESS_PATH, SET_PATH = (os.path.join(DATA, n) for n in ("config.json", "auth.json", "sessions.json", "settings.json"))
ACC_PATH, USAGE_PATH, USERS = os.path.join(DATA, "accounts.json"), os.path.join(DATA, "usage.json"), os.path.join(DATA, "users")
os.makedirs(USERS, exist_ok=True)
CFG = {"lan": False, "localhost_no_login": True, "internet_autostart": False, "internet_provider": "tailscale"}
CFG.update(jload(CFG_PATH, {}))
def save_cfg(): jsave(CFG_PATH, CFG)
PBKDF2_ITERS = 390000
TIERS = {"master": "Master", "user": "User", "limited": "Limited User"}
LIMIT_DEFAULTS = {"models": [], "daily_cap": 50, "max_tokens": 1024}
UID_RE = re.compile(r"^u[0-9a-f]{12}$")
UNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
def hash_pw(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERS)
    return {"algo": "pbkdf2_sha256", "iterations": PBKDF2_ITERS, "salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(h).decode()}
_DUMMY = hash_pw(secrets.token_hex(8))
def verify_pw(rec, pw):
    rec = rec or _DUMMY  # unknown user / no password: same PBKDF2 cost, always false
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(rec["salt"]), int(rec["iterations"]))
    return hmac.compare_digest(h, base64.b64decode(rec["hash"])) and rec is not _DUMMY
ACC = jload(ACC_PATH, None)
def save_acc(): jsave(ACC_PATH, ACC)
def user_dir(uid):
    if not UID_RE.match(uid or ""): raise ValueError("bad account id")
    d = os.path.join(USERS, uid); os.makedirs(os.path.join(d, "chats"), exist_ok=True); return d
def migrate_accounts():
    """v4 had one password (auth.json) and one chat folder; that owner becomes the first Master account."""
    global ACC
    if isinstance(ACC, dict) and isinstance(ACC.get("users"), dict) and ACC["users"]:
        ACC.setdefault("limited_defaults", dict(LIMIT_DEFAULTS)); return
    uid = "u" + secrets.token_hex(6)
    old = jload(AUTH_PATH, {})
    ACC = {"v": 1, "users": {uid: {"id": uid, "username": "atharva", "tier": "master", "active": True, "created": int(time.time()),
                                   "pw": {k: old[k] for k in ("algo", "iterations", "salt", "hash")} if old.get("hash") else None}},
           "limited_defaults": dict(LIMIT_DEFAULTS)}
    d = user_dir(uid)
    for fn in os.listdir(CHATS):
        if fn.endswith(".json") and os.path.isfile(os.path.join(CHATS, fn)): os.replace(os.path.join(CHATS, fn), os.path.join(d, "chats", fn))
    if os.path.isfile(SET_PATH): shutil.copy2(SET_PATH, os.path.join(d, "settings.json"))
    save_acc()
    if os.path.isfile(AUTH_PATH): os.replace(AUTH_PATH, AUTH_PATH + ".migrated")
    log(f"accounts: migrated the existing owner to Master account 'atharva' ({'with' if old.get('hash') else 'no'} password yet)")
def users(): return ACC["users"]
def get_user(uid): return users().get(uid or "")
def find_user(name):
    n = (name or "").strip().lower()
    return next((u for u in users().values() if u["username"].lower() == n), None)
def active_masters(): return [u for u in users().values() if u["tier"] == "master" and u["active"]]
def owner():  # the PC owner: the oldest active Master (used by 'skip login on this PC' and first-time setup)
    m = sorted(active_masters(), key=lambda u: u["created"]); return m[0] if m else None
def has_password():  # someone can sign in with a password (LAN / internet need this)
    return any(u.get("pw") for u in active_masters())
def limits_of(u):
    d = ACC.get("limited_defaults") or LIMIT_DEFAULTS
    lim = dict(d); lim.update(u.get("limits") or {}); return lim
def clean_limits(b, base):
    out = dict(base)
    if "models" in b:
        ms = b["models"]
        if not isinstance(ms, list): raise ValueError("models must be a list")
        out["models"] = [str(x)[:200] for x in ms if re.match(r"^(engine|lmstudio):[^\s]{1,190}$", str(x))][:50]
    if "daily_cap" in b: out["daily_cap"] = max(0, min(100000, int(b["daily_cap"])))
    if "max_tokens" in b: out["max_tokens"] = max(64, min(32768, int(b["max_tokens"])))
    return out
def user_view(u, me=None):
    return {"id": u["id"], "username": u["username"], "tier": u["tier"], "tier_name": TIERS[u["tier"]], "active": u["active"], "created": u["created"],
            "last_login": u.get("last_login"), "has_password": bool(u.get("pw")), "you": bool(me and me["id"] == u["id"]),
            "limits": limits_of(u) if u["tier"] == "limited" else None, "sessions": sum(1 for s in SESS.values() if s.get("uid") == u["id"])}
# ---- usage (Limited User daily cap) ----
USAGE = jload(USAGE_PATH, {})
def today(): return time.strftime("%Y-%m-%d")
def used_today(uid):
    r = USAGE.get(uid) or {}
    return r.get("n", 0) if r.get("day") == today() else 0
def take_message(u):
    """counts one chat request against a Limited User's daily cap; False when the cap is reached"""
    with LOCK:
        cap = limits_of(u)["daily_cap"]; n = used_today(u["id"])
        if n >= cap: return False
        USAGE[u["id"]] = {"day": today(), "n": n + 1}; jsave(USAGE_PATH, USAGE); return True
# ---- sessions ----
SESS = jload(SESS_PATH, {})  # sha256(token) -> {created, expires, ip, ua, uid, via}
SESSION_DAYS = 30
def tok_hash(t): return hashlib.sha256(t.encode()).hexdigest()
def new_session(uid, ip, ua, via="local"):
    t = secrets.token_urlsafe(32)
    with LOCK:
        now = time.time()
        for k in [k for k, v in SESS.items() if v["expires"] < now]: SESS.pop(k)
        SESS[tok_hash(t)] = {"created": int(now), "expires": int(now + SESSION_DAYS * 86400), "ip": ip, "ua": (ua or "")[:120], "uid": uid, "via": via}
        jsave(SESS_PATH, SESS)
    return t
def session_user(t):
    if not t: return None
    s = SESS.get(tok_hash(t))
    if not s or s["expires"] <= time.time(): return None
    u = get_user(s.get("uid"))
    return u if u and u["active"] else None
def drop_session(t=None, all_=False, uid=None, keep=None):
    with LOCK:
        if all_: SESS.clear()
        elif uid:
            for k in [k for k, v in SESS.items() if v.get("uid") == uid and k != keep]: SESS.pop(k)
        elif t: SESS.pop(tok_hash(t), None)
        jsave(SESS_PATH, SESS)
# ---- login throttling: per client IP, per username (lockout) and globally for remote clients ----
FAILS, UFAILS, GLOBAL_FAILS = {}, {}, []
def rate_limited(ip, name=None, remote=False):
    now = time.time()
    with LOCK:
        f = [t for t in FAILS.get(ip, []) if now - t < 600]; FAILS[ip] = f
        if len(f) >= 5: return int(600 - (now - f[-5])) + 1
        if name:
            uf = [t for t in UFAILS.get(name, []) if now - t < 900]; UFAILS[name] = uf
            if len(uf) >= 8: return int(900 - (now - uf[-8])) + 1
        if remote:
            g = [t for t in GLOBAL_FAILS if now - t < 600]; GLOBAL_FAILS[:] = g
            if len(g) >= 60: return int(600 - (now - g[-60])) + 1
    return 0
def note_fail(ip, name=None, remote=False):
    now = time.time()
    with LOCK:
        FAILS.setdefault(ip, []).append(now)
        if name: UFAILS.setdefault(name, []).append(now)
        if remote: GLOBAL_FAILS.append(now)
def perms(u):
    m = bool(u and u["tier"] == "master")
    return {"manage_models": m, "server_settings": m, "accounts": m, "vram": m}

# ---------------- network helpers ----------------
def is_private_ip(ip):
    try: a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError: return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped: a = a.ipv4_mapped
    if a.is_loopback or a.is_private or a.is_link_local: return True
    return False
def is_loopback(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
        if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped: a = a.ipv4_mapped
        return a.is_loopback
    except ValueError: return False
def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ips.append(s.getsockname()[0]); s.close()
    except OSError: pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips: ips.append(ip)
    except OSError: pass
    return [ip for ip in ips if is_private_ip(ip) and not is_loopback(ip)]
def port_open(hp, timeout=0.4):
    h, p = hp.rsplit(":", 1)
    try:
        with socket.create_connection((h, int(p)), timeout=timeout): return True
    except OSError: return False
def http_json(hp, method, path, body=None, timeout=3.0):
    c = http.client.HTTPConnection(hp, timeout=timeout)
    try:
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"})
        r = c.getresponse(); raw = r.read()
        try: data = json.loads(raw) if raw else {}
        except ValueError: data = {"raw": raw[:300].decode("utf-8", "replace")}
        return r.status, data
    except Exception as e: return 0, {"error": str(e)}
    finally: c.close()
def ps(script, timeout=20):
    flags = 0x08000000 if os.name == "nt" else 0
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=timeout, creationflags=flags)
    return r.stdout

# ---------------- backends / models ----------------
_lm_cache = {"t": 0, "data": None}
def lm_models(max_age=2.0):
    if time.time() - _lm_cache["t"] < max_age and _lm_cache["data"] is not None: return _lm_cache["data"]
    if not port_open(UP["lmstudio"], 0.25):
        _lm_cache.update(t=time.time(), data=None); return None
    st, d = http_json(UP["lmstudio"], "GET", "/api/v1/models", timeout=3)
    data = d.get("models") if st == 200 else None
    _lm_cache.update(t=time.time(), data=data); return data
def engine_status():
    if not port_open(UP["engine"]): return {"online": False, "models": []}
    st, d = http_json(UP["engine"], "GET", "/v1/models", timeout=2.5)
    return {"online": st == 200, "models": [m.get("id") for m in d.get("data", [])] if st == 200 else []}
def models_view():
    eng = engine_status(); lm = lm_models(); out = []
    for m in lm or []:
        caps = m.get("capabilities") or {}
        out.append({"key": m.get("key"), "name": m.get("display_name") or m.get("key"), "type": m.get("type"), "params": m.get("params_string"),
                    "quant": (m.get("quantization") or {}).get("name"), "size": m.get("size_bytes"), "vision": bool(caps.get("vision")),
                    "reasoning": (caps.get("reasoning") or {}).get("allowed_options"), "loaded": bool(m.get("loaded_instances")),
                    "instances": [i.get("id") for i in m.get("loaded_instances") or []],
                    "context": ((m.get("loaded_instances") or [{}])[0].get("config") or {}).get("context_length")})
    engines = [{**m, "online": bool(eng["online"] and m["id"] in eng["models"])} for m in ENGINE_MODELS]
    return {"engine": {**eng, "id": ENGINE_MODEL, "name": "Qwen3.8 27B · IQ3_XS", "vision": True, "efforts": ["off", "low", "medium", "high"]}, "engines": engines,
            "lmstudio": {"online": lm is not None, "models": out}, "job": job_view()}

def model_choices():  # every chat model a Master can allow for Limited Users
    out = [{"key": f"engine:{m['id']}", "label": m["name"] + " (RDNA4 engine)"} for m in ENGINE_MODELS]
    for m in lm_models() or []:
        if m.get("type") in ("llm", "vlm"): out.append({"key": f"lmstudio:{m.get('key')}", "label": (m.get("display_name") or m.get("key")) + " (LM Studio)"})
    return out
def model_online(backend, mid):
    if backend == "engine": return mid in engine_status()["models"]
    if backend == "lmstudio": return any(m.get("key") == mid and m.get("loaded_instances") for m in lm_models() or [])
    return False
def models_for(u):
    v = models_view()
    if u["tier"] == "master": v["can_manage"] = True; return v
    allowed = set(limits_of(u)["models"]) if u["tier"] == "limited" else None
    ok = lambda b, i: allowed is None or f"{b}:{i}" in allowed
    v["engines"] = [e for e in v["engines"] if e["online"] and ok("engine", e["id"])]
    v["engine"] = {**v["engine"], "online": any(e["id"] == v["engine"]["id"] for e in v["engines"])}
    v["lmstudio"] = {"online": v["lmstudio"]["online"], "models": [m for m in v["lmstudio"]["models"] if m["loaded"] and m["type"] in ("llm", "vlm") and ok("lmstudio", m["key"])]}
    v["can_manage"] = False
    return v

# ---------------- jobs (one at a time) ----------------
JOB = {"id": 0, "kind": None, "target": None, "label": "", "state": "idle", "started": 0, "ended": 0, "error": "", "log": "", "expect": 30}
def job_view():
    with LOCK: j = dict(JOB)
    j["elapsed"] = round((j["ended"] or time.time()) - j["started"], 1) if j["started"] else 0
    lines = [l for l in tail(j.pop("log")).splitlines() if l.strip()] if j.get("log") else []
    j["last"] = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", lines[-1])[-160:] if lines else ""
    return j
def tail(path, n=3000):
    try:
        with open(path, "rb") as f: f.seek(0, 2); s = f.tell(); f.seek(max(0, s - n)); return f.read().decode("utf-8", "replace")
    except OSError: return ""
def start_job(kind, label, fn, expect, target=None):
    with LOCK:
        if JOB["state"] == "running": return False
        JOB.update(id=JOB["id"] + 1, kind=kind, target=target, label=label, state="running", started=time.time(), ended=0, error="", log="", expect=expect)
    def run():
        try:
            err = fn()
            with LOCK: JOB.update(state="failed" if err else "done", error=err or "", ended=time.time())
        except Exception as e:
            with LOCK: JOB.update(state="failed", error=str(e), ended=time.time())
        _lm_cache["t"] = 0
    threading.Thread(target=run, daemon=True).start(); return True
def run_script(name, arg=None, wait_engine=None):
    logp = os.path.join(LOGS, f"job-{name}.log"); JOB["log"] = logp
    flags = 0x08000000 if os.name == "nt" else 0
    with open(logp, "wb") as lf:
        p = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", os.path.join(BENCH, name)] + ([arg] if arg else []),
                             stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=BENCH, creationflags=flags)
        t0 = time.time()
        while time.time() - t0 < 300:
            code = p.poll()
            if wait_engine and engine_ready(wait_engine): return None
            if code is not None:
                if wait_engine: return None if engine_ready(wait_engine) else f"{name} exited ({code})"
                return None if code == 0 else f"{name} exited ({code})"
            time.sleep(1)
    return f"{name} timed out"
def engine_ready(want):  # want: True (any engine model) or a model id (that model must be the one serving)
    st = engine_status()
    return st["online"] and (want is True or want in st["models"])
def lm_load(key, ctx):
    body = {"model": key}
    if ctx: body["context_length"] = ctx
    st, d = http_json(UP["lmstudio"], "POST", "/api/v1/models/load", body, timeout=600)
    if st != 200: return f"LM Studio load {key}: {d.get('error') or d}"[:300]
def lm_unload(key):
    m = next((m for m in lm_models(0) or [] if m.get("key") == key), None)
    if not m: return f"unknown model {key}"
    for inst in m.get("loaded_instances") or []:
        st, d = http_json(UP["lmstudio"], "POST", "/api/v1/models/unload", {"instance_id": inst["id"]}, timeout=120)
        if st != 200: return f"LM Studio unload {key}: {d.get('error') or d}"[:300]
# ---------------- VRAM monitor (persistent PowerShell reading perf counters) ----------------
VRAM = {"t": 0, "data": None, "proc": None, "last_req": 0, "total_mb": None, "gpu": None}
VRAM_PS = r"""
$ErrorActionPreference='SilentlyContinue'
while ($true) {
  $s = (Get-Counter -Counter '\GPU Adapter Memory(*)\Dedicated Usage','\GPU Adapter Memory(*)\Shared Usage','\GPU Process Memory(*)\Dedicated Usage','\GPU Process Memory(*)\Shared Usage').CounterSamples
  $names = @{}; Get-Process | ForEach-Object { $names[$_.Id] = $_.ProcessName }
  $ad = @{}; $pr = @{}
  foreach ($x in $s) {
    $kind = if ($x.Path -like '*shared usage') { 'shared' } else { 'dedicated' }
    $inst = $x.InstanceName
    $luid = if ($inst -match '(luid_0x[0-9a-f]+_0x[0-9a-f]+)') { $Matches[1] } else { '' }
    if ($x.Path -like '*gpu adapter memory*') { if (-not $ad[$luid]) { $ad[$luid] = @{luid=$luid; dedicated=0; shared=0} }; $ad[$luid][$kind] += [int64]$x.CookedValue }
    elseif ($inst -match '^pid_(\d+)_') { $id=[int]$Matches[1]; $k="$id|$luid"; if (-not $pr[$k]) { $pr[$k] = @{pid=$id; luid=$luid; name=$names[$id]; dedicated=0; shared=0} }; $pr[$k][$kind] += [int64]$x.CookedValue }
  }
  $o = @{ adapters = @($ad.Values); procs = @($pr.Values | Where-Object { $_.dedicated -gt 33554432 -or $_.shared -gt 268435456 }) }
  [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress -Depth 4)); [Console]::Out.Flush()
  Start-Sleep -Seconds 2
}
"""
def gpu_total():
    if VRAM["total_mb"] is not None: return
    try:
        import winreg
        best = (0, None)
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}")
        for i in range(64):
            try: sub = winreg.EnumKey(k, i)
            except OSError: break
            try:
                s = winreg.OpenKey(k, sub); size = winreg.QueryValueEx(s, "HardwareInformation.qwMemorySize")[0]; desc = winreg.QueryValueEx(s, "DriverDesc")[0]
            except OSError: continue
            score = size + (1 << 50 if re.search(r"Radeon|NVIDIA|GeForce|Arc", desc) else 0)
            if score > best[0]: best = (score, (desc, size))
        if best[1]: VRAM["gpu"], VRAM["total_mb"] = best[1][0], round(best[1][1] / 2**20)
    except Exception as e:
        log(f"gpu total: {e}"); VRAM["total_mb"] = 0
def vram_reader():
    flags = 0x08000000 if os.name == "nt" else 0
    p = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", "-"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=flags)
    VRAM["proc"] = p
    p.stdin.write(VRAM_PS + "\n"); p.stdin.close()
    try:
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"): continue
            try: d = json.loads(line)
            except ValueError: continue
            VRAM["data"], VRAM["t"] = d, time.time()
            if time.time() - VRAM["last_req"] > 60: break
    finally:
        try: p.kill()
        except Exception: pass
        VRAM["proc"] = None
def vram_view():
    VRAM["last_req"] = time.time()
    if os.name != "nt": return {"available": False}
    gpu_total()
    if VRAM["proc"] is None: threading.Thread(target=vram_reader, daemon=True).start()
    d = VRAM["data"]
    if not d or time.time() - VRAM["t"] > 15: return {"available": True, "pending": True, "gpu": VRAM["gpu"], "total_mb": VRAM["total_mb"]}
    ads = d.get("adapters") or []
    if isinstance(ads, dict): ads = [ads]
    main = max(ads, key=lambda a: a.get("dedicated", 0)) if ads else {"luid": "", "dedicated": 0, "shared": 0}
    procs = d.get("procs") or []
    if isinstance(procs, dict): procs = [procs]
    procs = [p for p in procs if p.get("luid") == main.get("luid")]
    procs.sort(key=lambda p: -p.get("dedicated", 0))
    mb = lambda b: round(b / 2**20)
    return {"available": True, "gpu": VRAM["gpu"], "total_mb": VRAM["total_mb"], "used_mb": mb(main.get("dedicated", 0)), "shared_mb": mb(main.get("shared", 0)),
            "procs": [{"pid": p.get("pid"), "name": p.get("name") or "?", "dedicated_mb": mb(p.get("dedicated", 0)), "shared_mb": mb(p.get("shared", 0))} for p in procs[:8]],
            "age": round(time.time() - VRAM["t"], 1)}

# ---------------- LAN / autostart / firewall ----------------
SERVER = {"srv": None, "host": "127.0.0.1", "error": ""}
def lan_view():
    ips = lan_ips()
    return {"enabled": SERVER["host"] == "0.0.0.0", "configured": CFG.get("lan", False), "ips": ips, "port": PORT,
            "urls": [f"http://{ip}:{PORT}/" for ip in ips], "error": SERVER["error"], "has_password": has_password(), "autostart": autostart_get()}
def autostart_cmd():
    psx = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")
    return f'"{psx}" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{os.path.join(HERE, "Start-ChatUI.ps1")}" -NoBrowser -Lan'
def autostart_get():
    if os.name != "nt": return False
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY); v = winreg.QueryValueEx(k, RUN_NAME)[0]; return bool(v)
    except OSError: return False
def autostart_set(on):
    import winreg
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    if on: winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_cmd())
    else:
        try: winreg.DeleteValue(k, RUN_NAME)
        except FileNotFoundError: pass
_fw = {"t": 0, "data": None}
def firewall_view():
    if time.time() - _fw["t"] < 60 and _fw["data"]: return _fw["data"]
    exe = sys.executable.replace("'", "''")
    script = f"""
$ErrorActionPreference='SilentlyContinue'
$prof = @(Get-NetConnectionProfile | ForEach-Object {{ @{{alias=$_.InterfaceAlias; category=[string]$_.NetworkCategory}} }})
$fwp = @(Get-NetFirewallProfile | ForEach-Object {{ @{{name=$_.Name; enabled=[bool]$_.Enabled}} }})
$port = @(Get-NetFirewallRule -DisplayName '{FW_RULE}' | ForEach-Object {{ @{{name=$_.DisplayName; enabled=[string]$_.Enabled; profile=[string]$_.Profile; action=[string]$_.Action}} }})
$app = @(Get-NetFirewallApplicationFilter | Where-Object {{ $_.Program -eq '{exe}' }} | ForEach-Object {{ $r = $_ | Get-NetFirewallRule; @{{name=$r.DisplayName; dir=[string]$r.Direction; action=[string]$r.Action; profile=[string]$r.Profile; enabled=[string]$r.Enabled}} }})
@{{profiles=$prof; firewall=$fwp; portRule=$port; appRules=$app}} | ConvertTo-Json -Compress -Depth 4
"""
    try: d = json.loads(ps(script, 30) or "{}")
    except Exception as e: d = {"error": str(e)}
    fix = lambda v: v if isinstance(v, list) else ([v] if v else [])
    for k in ("profiles", "firewall", "portRule", "appRules"): d[k] = fix(d.get(k))
    allow_app = [r for r in d["appRules"] if r.get("dir") == "Inbound" and r.get("enabled") == "True" and r.get("action") == "Allow" and ("Private" in r.get("profile", "") or r.get("profile") == "Any")]
    block_app = [r for r in d["appRules"] if r.get("dir") == "Inbound" and r.get("enabled") == "True" and r.get("action") == "Block"]
    port_ok = [r for r in d["portRule"] if r.get("enabled") == "True" and r.get("action") == "Allow"]
    cats = {p.get("category") for p in d["profiles"]}
    if block_app: verdict, need = "A Windows Firewall rule BLOCKS python.exe inbound; phones will be refused until it is removed.", True
    elif "Public" in cats and not port_ok: verdict, need = "This network is set to Public; a Private-profile rule won't apply. Set the Wi-Fi network to Private.", True
    elif port_ok: verdict, need = "Allowed by the 'Local AI Chat' port rule.", False
    elif allow_app: verdict, need = "Allowed by an existing Windows Firewall rule for python.exe (Private networks).", False
    else: verdict, need = "No inbound rule found: other devices will probably be blocked. Run Add-ChatUIFirewallRule.ps1 as admin.", True
    d.update(verdict=verdict, rule_needed=need, python=sys.executable)
    _fw.update(t=time.time(), data=d); return d

# ---------------- internet link (free Cloudflare Quick Tunnel, no account) ----------------
CLOUDFLARED = os.environ.get("MOCHI_CLOUDFLARED", r"C:\Dev\Tools\cloudflared\cloudflared.exe")
TUN_PID = os.path.join(DATA, "cloudflared.pid")
TUNNEL = {"proc": None, "state": "off", "url": "", "host": "", "connected": False, "error": "", "started": 0, "provider": "", "enable_url": ""}
_JOB = {"h": None}
def _kill_with_us(p):
    """Windows job object with KILL_ON_JOB_CLOSE: cloudflared dies with this server even if it is killed."""
    if os.name != "nt": return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not _JOB["h"]:
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            h = k32.CreateJobObjectW(None, None)
            class BASIC(ctypes.Structure):
                _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t),
                            ("e", wintypes.DWORD), ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]
            class IOC(ctypes.Structure): _fields_ = [(n, ctypes.c_uint64) for n in ("r1", "r2", "r3", "r4", "r5", "r6")]
            class EXT(ctypes.Structure):
                _fields_ = [("basic", BASIC), ("io", IOC), ("pm", ctypes.c_size_t), ("jm", ctypes.c_size_t), ("ppm", ctypes.c_size_t), ("pjm", ctypes.c_size_t)]
            info = EXT(); info.basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(wintypes.HANDLE(h), 9, ctypes.byref(info), ctypes.sizeof(info)): return
            _JOB["h"] = h
        k32.AssignProcessToJobObject(wintypes.HANDLE(_JOB["h"]), wintypes.HANDLE(int(p._handle)))
    except Exception as e: log(f"tunnel: job object not set ({e})")
def _stale_tunnel():  # a cloudflared left over from an earlier run (only ours: same exe path)
    try: pid = int(open(TUN_PID).read().strip())
    except (OSError, ValueError): return
    exe = CLOUDFLARED.replace("'", "''")
    ps(f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; if ($p -and $p.Path -eq '{exe}') {{ Stop-Process -Id {pid} -Force }}", 15)
    try: os.remove(TUN_PID)
    except OSError: pass
def cf_view():
    return {"state": TUNNEL["state"], "url": TUNNEL["url"], "connected": TUNNEL["connected"], "error": TUNNEL["error"],
            "autostart": bool(CFG.get("internet_autostart")), "installed": os.path.isfile(CLOUDFLARED), "has_password": has_password(),
            "since": TUNNEL["started"]}
def cf_start():
    with LOCK:
        if TUNNEL["proc"] and TUNNEL["proc"].poll() is None: return
        if not os.path.isfile(CLOUDFLARED): TUNNEL.update(state="error", error=f"cloudflared not found at {CLOUDFLARED}"); return
        TUNNEL.update(state="starting", url="", host="", connected=False, error="", enable_url="", started=time.time(), provider="cloudflare")
        p = subprocess.Popen([CLOUDFLARED, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, cwd=os.path.dirname(CLOUDFLARED), creationflags=0x08000000 if os.name == "nt" else 0)
        _kill_with_us(p); TUNNEL["proc"] = p
        with open(TUN_PID, "w") as f: f.write(str(p.pid))
    def reader():
        with open(os.path.join(LOGS, "cloudflared.log"), "ab") as lf:
            lf.write(time.strftime("\n--- %Y-%m-%d %H:%M:%S start\n").encode())
            for line in p.stdout:
                lf.write(line); lf.flush()
                m = re.search(rb"https://([a-z0-9-]+\.trycloudflare\.com)", line)
                if m and TUNNEL["proc"] is p and not TUNNEL["url"]:
                    host = m.group(1).decode(); TUNNEL.update(url="https://" + host + "/", host=host, state="on"); log(f"internet link: https://{host}/")
                if b"Registered tunnel connection" in line and TUNNEL["proc"] is p: TUNNEL["connected"] = True
        code = p.wait()
        if TUNNEL["proc"] is p:
            TUNNEL.update(proc=None, state="error", url="", host="", connected=False, error=f"cloudflared exited ({code}); see logs\\cloudflared.log")
            log(TUNNEL["error"])
    threading.Thread(target=reader, daemon=True).start()
def cf_stop():
    with LOCK:
        p = TUNNEL["proc"]; TUNNEL.update(proc=None, state="off", url="", host="", connected=False, error="")
    if p and p.poll() is None:
        p.terminate()
        try: p.wait(5)
        except subprocess.TimeoutExpired: p.kill()
    try: os.remove(TUN_PID)
    except OSError: pass


# ---------------- internet link, option 2: Tailscale Funnel (fixed https://<pc>.<tailnet>.ts.net link) ----------------
TAILSCALE = os.environ.get("MOCHI_TAILSCALE", r"C:\Program Files\Tailscale\tailscale.exe")
TS_ACT = {"busy": "", "msg": "", "ok": True, "t": 0}
_TSS = {"t": 0, "d": None}
_UP_FLAG = re.compile(r"^--[a-z][a-z0-9-]*(=[A-Za-z0-9._:@/,-]*)?$")
def ts_run(args, timeout=20):
    """Runs Tailscale's own CLI with fixed arguments (no shell). A command that waits for the user is cut off at `timeout`."""
    if not os.path.isfile(TAILSCALE): return -1, "Tailscale is not installed"
    try:
        p = subprocess.Popen([TAILSCALE] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=0x08000000 if os.name == "nt" else 0)
    except OSError as e: return -1, str(e)
    try: out, _ = p.communicate(timeout=timeout); return p.returncode, out.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        p.kill(); out, _ = p.communicate(); return None, out.decode("utf-8", "replace")
def _js(out):
    try: return json.loads(out[out.index("{"):])
    except (ValueError, TypeError): return None
def ts_service():
    if os.name != "nt": return ""
    try:
        r = subprocess.run(["sc.exe", "query", "Tailscale"], capture_output=True, text=True, timeout=8, creationflags=0x08000000)
        m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", r.stdout); return (m.group(1).lower() if m else "missing")
    except Exception: return ""
def ts_status(fresh=False):
    if not os.path.isfile(TAILSCALE): return {"installed": False}
    if not fresh and _TSS["d"] and time.time() - _TSS["t"] < 3: return _TSS["d"]
    code, out = ts_run(["status", "--json"], 10); j = _js(out)
    d = {"installed": True, "service": ts_service()}
    if not j: d.update(state="NoState", error=(out or "").strip()[:300] or "the Tailscale service isn't answering")
    else:
        me = j.get("Self") or {}
        d.update(state=j.get("BackendState") or "", host=(me.get("DNSName") or "").rstrip("."), online=bool(me.get("Online")),
                 tailnet=(j.get("CurrentTailnet") or {}).get("Name") or "", ips=(j.get("TailscaleIPs") or [])[:2],
                 version=(j.get("Version") or "").split("-")[0], auth_url=j.get("AuthURL") or "",
                 health=[str(x)[:240] for x in (j.get("Health") or [])][:4])
    _TSS.update(t=time.time(), d=d); return d
def funnel_ours(host):
    """True when Tailscale is funnelling https://host:443 to this server."""
    if not host: return False
    code, out = ts_run(["funnel", "status", "--json"], 10); j = _js(out) or {}
    key = f"{host}:443"
    if not (j.get("AllowFunnel") or {}).get(key): return False
    hs = ((j.get("Web") or {}).get(key) or {}).get("Handlers") or {}
    return any(re.search(rf"//(127\.0\.0\.1|localhost):{PORT}/?$", str(h.get("Proxy") or "")) for h in hs.values())
def ts_start():
    st = ts_status(True)
    with LOCK:
        TUNNEL.update(provider="tailscale", state="starting", url="", host="", connected=False, error="", enable_url="", started=time.time())
    if not st.get("installed"): TUNNEL.update(state="error", error="Tailscale is not installed"); return
    if st.get("state") != "Running":
        TUNNEL.update(state="error", error=f"Tailscale isn't connected ({st.get('state') or 'service stopped'}) - reconnect it below", enable_url=st.get("auth_url") or ""); return
    def work():
        code, out = ts_run(["funnel", "--bg", "--yes", str(PORT)], 15)
        host = st["host"]
        if TUNNEL["provider"] != "tailscale" or TUNNEL["state"] != "starting": return
        if funnel_ours(host):
            TUNNEL.update(state="on", host=host, url=f"https://{host}/", connected=True); log(f"internet link (Tailscale Funnel): https://{host}/")
        else:
            urls = re.findall(r"https://login\.tailscale\.com/\S+", out or "")
            msg = " ".join(l.strip() for l in (out or "").splitlines() if l.strip() and "http" not in l)
            msg = re.sub(r"\s*To enable,? visit:?\s*$", "", msg, flags=re.I)[:300] or f"tailscale funnel failed ({code})"
            if code is None and not urls: msg = "Tailscale is waiting for something: " + msg
            TUNNEL.update(state="error", error=msg, enable_url=urls[0].rstrip(".,") if urls else ""); log(f"internet link (Tailscale): {msg}")
            if code is None: ts_run(["funnel", "--https=443", "off"], 10)  # don't leave a half-made config behind
    threading.Thread(target=work, daemon=True).start()
def ts_funnel_off():
    host = ts_status(True).get("host") or TUNNEL.get("host")
    if not host or not funnel_ours(host): return True
    ts_run(["funnel", "--https=443", "off"], 15)
    if funnel_ours(host): ts_run(["serve", "--https=443", "off"], 15)
    ok = not funnel_ours(host)
    if not ok: log("internet link (Tailscale): could not turn Funnel off")
    return ok
def ts_stop():
    with LOCK: TUNNEL.update(state="off", url="", host="", connected=False, error="", enable_url="")
    ts_funnel_off()
def ts_check():
    """Keeps the shown state honest if Funnel / Tailscale was changed outside Mochi."""
    if TUNNEL["provider"] != "tailscale" or TUNNEL["state"] != "on" or time.time() - TUNNEL.get("_chk", 0) < 5: return
    TUNNEL["_chk"] = time.time()
    st = ts_status(True)
    if st.get("state") != "Running": TUNNEL["connected"] = False; return
    if not funnel_ours(TUNNEL["host"]):
        TUNNEL.update(state="error", url="", host="", connected=False, error="Funnel was turned off outside Mochi"); drop_internet_sessions()
    else: TUNNEL["connected"] = True
def _stale_funnel():  # Funnel config lives on in Tailscale: never let a link survive a Mochi restart unless auto-start is on
    if os.path.isfile(TAILSCALE) and not CFG.get("internet_autostart"):
        host = ts_status(True).get("host")
        if host and funnel_ours(host): log("internet link: turning off a Funnel left over from an earlier run"); ts_funnel_off()
def ts_action(action):
    """Local-PC-only Tailscale controls. Runs in the background; the UI polls /api/internet."""
    def done(ok, msg): TS_ACT.update(busy="", ok=ok, msg=msg, t=time.time()); _TSS["t"] = 0; log(f"tailscale {action}: {msg}")
    def work():
        try:
            if action in ("disconnect", "service_stop") and TUNNEL["provider"] == "tailscale" and TUNNEL["state"] in ("on", "starting"): tunnel_stop()
            if action == "disconnect":
                code, out = ts_run(["down"], 20); return done(code == 0, "disconnected" if code == 0 else out.strip()[:300])
            if action == "reconnect":
                code, out = ts_run(["up", "--timeout=25s"], 35)
                m = re.search(r"tailscale up ([^\r\n]+)", out or "") if code != 0 else None
                if m and "requires mentioning all" in out:  # Tailscale tells us the exact flags it needs; use them only if they are plain flags
                    flags = [f for f in m.group(1).split() if not f.startswith("--timeout")]
                    if flags and all(_UP_FLAG.match(f) for f in flags): code, out = ts_run(["up", "--timeout=25s"] + flags, 35)
                urls = re.findall(r"https://login\.tailscale\.com/\S+", out or "")
                if urls: TS_ACT["auth_url"] = urls[0]; return done(False, "Tailscale needs you to sign in again: open the link below")
                return done(code == 0, "connected" if code == 0 else (out or "").strip()[:300])
            if action in ("service_stop", "service_start"):  # needs admin: Windows shows its own UAC prompt on this PC every time
                verb = "Stop-Service" if action == "service_stop" else "Start-Service"
                out = ps("try { $p = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList "
                         f"'-NoProfile','-NonInteractive','-Command','{verb} -Name Tailscale'; 'exit ' + $p.ExitCode }} catch {{ 'fail ' + $_.Exception.Message }}", 180)
                svc = ts_service(); want = "stopped" if action == "service_stop" else "running"
                if svc == want: return done(True, f"service {svc}")
                return done(False, ("Windows permission was declined" if "cancel" in (out or "").lower() else (out or "").strip()[:200] or "no change") + f" (service {svc or '?'})")
            done(False, "unknown action")
        except Exception as e: done(False, str(e)[:200])
    if TS_ACT["busy"]: return False
    TS_ACT.update(busy=action, msg="", auth_url=""); threading.Thread(target=work, daemon=True).start(); return True

# ---------------- internet link: whichever provider is chosen ----------------
def provider(): return CFG.get("internet_provider") if CFG.get("internet_provider") in ("tailscale", "cloudflare") else "tailscale"
def tunnel_active(): return TUNNEL["state"] == "on" and (TUNNEL["provider"] == "tailscale" or bool(TUNNEL["proc"]))
def tunnel_start(): return ts_start() if provider() == "tailscale" else cf_start()
def tunnel_stop(quiet=False):
    was = TUNNEL["provider"]
    if TUNNEL["proc"]: cf_stop()
    if was == "tailscale" or not quiet: ts_stop() if os.path.isfile(TAILSCALE) else None
    TUNNEL.update(provider="", state="off", url="", host="", connected=False, error="", enable_url="")
    drop_internet_sessions()
def tunnel_view(local=False):
    ts_check()
    v = cf_view(); v.update(provider=TUNNEL["provider"] or provider(), chosen=provider(), enable_url=TUNNEL.get("enable_url", ""),
                            cf_installed=os.path.isfile(CLOUDFLARED))
    st = ts_status() if os.path.isfile(TAILSCALE) else {"installed": False}
    v["tailscale"] = {k: st.get(k) for k in ("installed", "state", "host", "online", "tailnet", "service", "version", "error", "auth_url")}
    v["tailscale"]["fixed_url"] = f"https://{st['host']}/" if st.get("host") else ""
    v["tailscale"]["action"] = {k: TS_ACT.get(k) for k in ("busy", "msg", "ok", "auth_url", "t")}
    v["installed"] = os.path.isfile(TAILSCALE) if provider() == "tailscale" else os.path.isfile(CLOUDFLARED)
    return v
def drop_internet_sessions():
    # sessions signed in through the link end with it (the next link has a new hostname anyway)
    with LOCK:
        to_drop = [k for k, v in SESS.items() if v.get("via") == "internet"]
        if to_drop:
            for k in to_drop: SESS.pop(k)
            jsave(SESS_PATH, SESS)
SX_PID = os.path.join(DATA, "searxng.pid")
def _stale_searxng():
    try: pid = int(open(SX_PID).read().strip())
    except (OSError, ValueError): return
    ps(f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like '*run_searxng.py*') {{ Stop-Process -Id {pid} -Force }}", 15)
    try: os.remove(SX_PID)
    except OSError: pass

INITIAL_STATE = {"lan": False, "internet_autostart": False, "engine": None, "lmstudio": []}
SHUTDOWN_EVT = threading.Event()
_SHUTTING_DOWN = False
def shutdown_preview():
    eng = engine_running()
    lms = [m for m in (lm_models(0) or []) if m.get("loaded_instances")]
    sx = mochi_tools.sx_view()
    return {
        "engine": {"id": eng["id"], "short": eng["short"], "name": eng["name"]} if eng else None,
        "lmstudio_loaded": [{"key": m.get("key"), "name": m.get("display_name") or m.get("key")} for m in lms],
        "internet": {"active": tunnel_active() or TUNNEL["state"] == "starting", "provider": TUNNEL.get("provider") or provider(), "url": TUNNEL.get("url") or ""},
        "searxng": {"running": sx["state"] in ("on", "starting"), "state": sx["state"]},
        "lan": {"enabled": SERVER["host"] == "0.0.0.0", "was_enabled_at_start": INITIAL_STATE["lan"]},
    }
def perform_shutdown(unload_models=True, restore_lan=True):
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN: return
    _SHUTTING_DOWN = True
    log("shutdown: stopping Mochi and cleaning up...")
    try: tunnel_stop(quiet=False)
    except Exception as e: log(f"shutdown tunnel: {e}")
    try: mochi_tools.sx_stop()
    except Exception as e: log(f"shutdown searxng: {e}")
    if unload_models:
        try:
            eng = engine_running()
            if eng:
                log(f"shutdown: stopping engine ({eng['short']})")
                run_script("Stop-Qwen27B.ps1")
        except Exception as e: log(f"shutdown engine: {e}")
        try:
            for m in (lm_models(0) or []):
                if m.get("loaded_instances"):
                    log(f"shutdown: unloading LM Studio model {m.get('key')}")
                    lm_unload(m["key"])
        except Exception as e: log(f"shutdown lmstudio: {e}")
    if restore_lan and CFG.get("lan") and not INITIAL_STATE["lan"]:
        CFG["lan"] = False; save_cfg()
        log("shutdown: restored LAN mode to off (as before Mochi opened)")
    try:
        if VRAM.get("proc"): VRAM["proc"].kill()
    except Exception: pass
    try:
        pidf = os.path.join(HERE, "server.pid")
        if os.path.isfile(pidf): os.remove(pidf)
    except OSError: pass
    try:
        if SERVER["srv"]: SERVER["srv"].shutdown(); SERVER["srv"].server_close()
    except Exception: pass
    SHUTDOWN_EVT.set()
def _cleanup_on_exit():
    try: tunnel_stop(quiet=True)
    except Exception: pass
    try: mochi_tools.sx_stop()
    except Exception: pass
atexit.register(_cleanup_on_exit)

# ---------------- chats ----------------
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
INDEXES = {}  # account id -> {chat id -> meta}
def chat_path(uid, cid): return os.path.join(user_dir(uid), "chats", cid + ".json")
def meta_of(c):
    last = next((m for m in reversed(c.get("messages", [])) if m.get("content")), None)
    return {"id": c["id"], "title": c.get("title") or "New chat", "created": c.get("created", 0), "updated": c.get("updated", 0), "pinned": bool(c.get("pinned")),
            "rev": c.get("rev", 0), "count": len(c.get("messages", [])), "preview": (last or {}).get("content", "")[:120]}
def index_for(uid):
    with LOCK:
        if uid not in INDEXES:
            idx = {}; d = os.path.join(user_dir(uid), "chats")
            for fn in os.listdir(d):
                if fn.endswith(".json"):
                    c = jload(os.path.join(d, fn), None)
                    if c and ID_RE.match(c.get("id", "")): idx[c["id"]] = meta_of(c)
            INDEXES[uid] = idx
        return INDEXES[uid]
def save_chat(uid, c):
    with LOCK:
        idx = index_for(uid)
        old = jload(chat_path(uid, c["id"]), {}) if c["id"] in idx else {}
        c["rev"] = int(old.get("rev", 0)) + 1
        c.setdefault("created", int(time.time() * 1000))
        jsave(chat_path(uid, c["id"]), c); idx[c["id"]] = meta_of(c)
        return c["rev"]
def search_user_chats(uid, q_str, limit=50):
    IDX = index_for(uid)
    s = (q_str or "").strip().lower()[:100]
    res = []
    if s:
        for cid, meta in sorted(IDX.items(), key=lambda kv: -kv[1]["updated"]):
            c = jload(chat_path(uid, cid), {}); hit = None
            if s in (c.get("title") or "").lower(): hit = c.get("title")
            else:
                for m in c.get("messages", []):
                    t = m.get("content") or ""; i = t.lower().find(s)
                    if i >= 0: hit = ("…" if i > 40 else "") + t[max(0, i - 40): i + 80]; break
            if hit: res.append({**meta, "snippet": hit})
            if len(res) >= limit: break
    return res
def system_status_text():
    eng = engine_running(); lm = lm_models(0); vr = vram_view(); sx = mochi_tools.sx_view()
    lines = ["Mochi PC Status (ATHEREAL):"]
    lines.append(f"- RDNA4 engine: {eng['name']} (online)" if eng else "- RDNA4 engine: off")
    if lm is None: lines.append("- LM Studio: offline")
    else:
        loaded = [m.get("display_name") or m.get("key") for m in lm if m.get("loaded_instances")]
        lines.append(f"- LM Studio: online ({len(loaded)} loaded: {', '.join(loaded)})" if loaded else "- LM Studio: online (no models loaded)")
    if vr.get("available") and vr.get("used_mb") is not None:
        lines.append(f"- GPU VRAM ({vr.get('gpu') or 'GPU'}): {vr['used_mb']} MB dedicated / {vr.get('total_mb')} MB total, {vr.get('shared_mb', 0)} MB shared")
    lines.append(f"- LAN mode: {'on' if SERVER['host'] == '0.0.0.0' else 'off'} · Internet link: {'on (' + TUNNEL.get('provider', '') + ')' if tunnel_active() else 'off'}")
    lines.append(f"- Web search (SearXNG): {sx['state']}")
    return "\n".join(lines)
mochi_tools.configure(log=log, user_dir=user_dir, logs_dir=LOGS, sx_pid_file=SX_PID, kill_with_us=_kill_with_us,
                      search_chats=search_user_chats, system_status=system_status_text)

def clean_chat(c, cid):
    if not isinstance(c, dict) or not isinstance(c.get("messages", []), list): raise ValueError("bad chat")
    msgs = []
    for m in c.get("messages", [])[:2000]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant", "tool"): continue
        keep = {k: m[k] for k in ("role", "content", "reasoning", "images", "stats", "error", "modelLabel", "thinkSecs", "effort", "imagesDropped", "tool_calls", "tool_call_id", "name") if k in m}
        msgs.append(keep)
    return {"id": cid, "title": str(c.get("title") or "")[:120], "created": int(c.get("created") or time.time() * 1000),
            "updated": int(c.get("updated") or time.time() * 1000), "pinned": bool(c.get("pinned")), "messages": msgs}
def to_markdown(c):
    out = [f"# {c.get('title') or 'Chat'}", ""]
    for m in c.get("messages", []):
        if m["role"] == "user": who = "You"
        elif m["role"] == "tool": who = f"Tool ({m.get('name', 'output')})"
        else: who = f"Mochi ({m.get('modelLabel', '')})"
        out += [f"## {who}", ""]
        if m.get("images"): out += [f"*[{len(m['images'])} image(s)]*", ""]
        if m.get("tool_calls"):
            out += ["```json\n" + json.dumps(m["tool_calls"], ensure_ascii=False, indent=2) + "\n```", ""]
        if m.get("content"): out += [m.get("content", ""), ""]
    return "\n".join(out)

# ---------------- HTTP ----------------
LOCAL_HOSTS = ("127.0.0.1", "localhost")
class H(BaseHTTPRequestHandler):
    server_version = "LocalAIChat/2.0"
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *a):
        msg = fmt % a
        if "/api/vram" in msg or "/api/status" in msg or "/api/chats " in msg: return
        log(f"{self.client_address[0]} {msg}")
    # --- request context ---
    def ctx(self):
        ip = self.client_address[0]
        host = (self.headers.get("Host") or "").lower()
        hn, _, hp = host.rpartition(":") if ":" in host else (host, "", "")
        hn = hn.strip("[]")
        cf = any(self.headers.get(h) for h in ("Cf-Connecting-Ip", "Cf-Ray", "Cf-Visitor", "Cdn-Loop", "X-Forwarded-For", "Cf-Ipcountry", "X-Forwarded-Proto",
                                                "X-Forwarded-Host", "Forwarded", "Tailscale-Funnel-Request", "Tailscale-User-Login", "Tailscale-Headers-Info"))
        tun_host = TUNNEL["host"]
        # Traffic through the tunnel reaches us from cloudflared on 127.0.0.1, so it is told apart by its Cloudflare headers / public Host,
        # never treated as "this PC": it always needs a password and never gets 'skip login'.
        tunnel = is_loopback(ip) and (cf or (tun_host and hn == tun_host))
        if tunnel:
            if not (tunnel_active() and tun_host and hn == tun_host and hp in ("", "443")): return None  # tunnel off, or an old / foreign hostname
            rip = ((self.headers.get("Cf-Connecting-Ip") if TUNNEL["provider"] == "cloudflare" else (self.headers.get("X-Forwarded-For") or "").split(",")[0]) or "").strip()[:64] or "internet"
            local_host = False
        else:
            if hp != str(PORT): return None
            hn_lower = hn.lower()
            sys_host = socket.gethostname().lower()
            local_host = hn_lower in LOCAL_HOSTS or hn_lower == sys_host or hn_lower == f"{sys_host}.local"
            lan_host_ok = (SERVER["host"] == "0.0.0.0" and (
                is_private_ip(hn) or
                hn_lower.endswith(".local") or
                hn_lower == sys_host
            ))
            if not (local_host or lan_host_ok): return None
            if not is_private_ip(ip): return None
            rip = ip
        origin = self.headers.get("Origin")
        if origin and origin != "null" and urlsplit(origin).netloc.lower() != host: return None
        # Clicking the public link is a cross-site document navigation. Let that page load.
        # Cross-site API calls, form posts, and embeds stay forbidden.
        if (self.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
            mode = (self.headers.get("Sec-Fetch-Mode") or "").lower()
            dest = (self.headers.get("Sec-Fetch-Dest") or "").lower()
            path = urlsplit(self.path).path
            nav = self.command in ("GET", "HEAD") and mode == "navigate" and dest == "document" and not path.startswith("/api/") and not path.startswith("/proxy/")
            if not nav: return None
        local = is_loopback(ip) and local_host and not tunnel
        tok = None
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "lac_session": tok = v
        user = session_user(tok); skip = False
        if not user and local and CFG.get("localhost_no_login", True):
            user = owner(); skip = bool(user)  # only on the PC itself, and only ever the Master owner
        return {"ip": rip, "local": local, "tunnel": bool(tunnel), "user": user, "authed": bool(user), "skip": skip, "token": tok, "host": host,
                "session": bool(session_user(tok))}
    def sec_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY"); self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin"); self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        if getattr(self, "_https", False): self.send_header("Strict-Transport-Security", "max-age=86400")
    def send_json(self, code, obj, headers=None):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.sec_headers()
        for k, v in (headers or {}).items():
            for vv in (v if isinstance(v, list) else [v]): self.send_header(k, vv)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(b)
    def body(self):
        return self._raw
    def jbody(self):
        raw = self.body()
        try: return json.loads(raw or b"{}")
        except ValueError: raise ValueError("invalid JSON")
    def do_HEAD(self): self.do_GET()
    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PUT(self): self.route("PUT")
    def do_PATCH(self): self.route("PATCH")
    def do_DELETE(self): self.route("DELETE")
    def route(self, method):
        self._https = False
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            self.close_connection = True
            return self.send_json(413, {"error": "request too large"})
        self._raw = self.rfile.read(n) if n else b""
        c = self.ctx()
        if c is None:
            self.close_connection = True
            return self.send_json(403, {"error": "forbidden"})
        self._https = c["tunnel"]
        u = urlsplit(self.path); path = u.path; q = parse_qs(u.query)
        if method != "GET" and self.headers.get("X-Local-Chat") != "1": return self.send_json(403, {"error": "missing X-Local-Chat header"})
        try:
            if not path.startswith("/api/") and not path.startswith("/proxy/"):
                return self.static(path) if method in ("GET", "HEAD") else self.send_json(405, {"error": "method"})
            if path.startswith("/api/auth/"): return self.auth(method, path, c)
            if not c["authed"]: return self.send_json(401, {"error": "login required"})
            if path.startswith("/proxy/"): return self.proxy(method, path, u.query, c)
            return self.api(method, path, q, c)
        except ValueError as e:
            return self.send_json(400, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
    # --- auth ---
    def auth_state(self, c):
        u = c["user"]; st = {"authed": c["authed"], "has_password": has_password(), "local": c["local"], "tunnel": c["tunnel"], "lan": SERVER["host"] == "0.0.0.0",
                             "internet": tunnel_active(), "localhost_no_login": CFG.get("localhost_no_login", True), "session": c["session"], "skip": c["skip"]}
        if u:
            st["user"] = {"id": u["id"], "username": u["username"], "tier": u["tier"], "tier_name": TIERS[u["tier"]], "has_password": bool(u.get("pw"))}
            st["perms"] = perms(u)
            if u["tier"] == "limited":
                lim = limits_of(u); st["limits"] = {**lim, "used_today": used_today(u["id"])}
            o = owner(); st["owner_setup"] = bool(c["local"] and o and o["id"] == u["id"] and not u.get("pw"))
        return st
    def auth(self, method, path, c):
        if path == "/api/auth/state" and method == "GET": return self.send_json(200, self.auth_state(c))
        if method != "POST": return self.send_json(405, {"error": "method"})
        b = self.jbody(); ua = self.headers.get("User-Agent"); remote = not c["local"]
        if path == "/api/auth/setup":  # first password for the Master owner; only on the PC itself
            o = owner()
            if not o or o.get("pw"): return self.send_json(409, {"error": "a password already exists"})
            if not c["local"]: return self.send_json(403, {"error": "create the password on the PC itself (http://127.0.0.1:%d)" % PORT})
            pw = str(b.get("password") or "")
            if len(pw) < 8: return self.send_json(400, {"error": "use at least 8 characters"})
            with LOCK: o["pw"] = hash_pw(pw); save_acc()
            t = new_session(o["id"], c["ip"], ua); log(f"password created for '{o['username']}' (local)")
            return self.send_json(200, {"ok": True}, {"Set-Cookie": self.cookie(t, c)})
        if path == "/api/auth/login":
            name = str(b.get("username") or "").strip()[:64]
            if not name and c["local"] and owner(): name = owner()["username"]  # the PC owner may sign in with just the password, as before
            key = name.lower()
            wait = rate_limited(c["ip"], key, remote)
            if wait: return self.send_json(429, {"error": f"too many attempts, try again in {wait // 60 + 1} min", "retry": wait})
            u = find_user(name); pw = str(b.get("password") or "")
            ok = verify_pw(u.get("pw") if u else None, pw)
            if not ok:
                note_fail(c["ip"], key, remote); log(f"login failed from {c['ip']}" + (" (internet)" if c["tunnel"] else "")); time.sleep(0.6)
                return self.send_json(401, {"error": "wrong username or password" if has_password() else "no password set yet - create one on the PC"})
            if not u["active"]: return self.send_json(403, {"error": "this account is turned off - ask the owner to turn it back on"})
            FAILS.pop(c["ip"], None); UFAILS.pop(key, None)
            with LOCK: u["last_login"] = int(time.time()); save_acc()
            t = new_session(u["id"], c["ip"], ua, "internet" if c["tunnel"] else ("local" if c["local"] else "lan"))
            log(f"login ok: '{u['username']}' from {c['ip']}" + (" (internet)" if c["tunnel"] else ""))
            return self.send_json(200, {"ok": True}, {"Set-Cookie": self.cookie(t, c)})
        if path == "/api/auth/logout":
            u = c["user"]
            if b.get("all") and u and c["session"]: drop_session(uid=u["id"])
            else: drop_session(c["token"])
            return self.send_json(200, {"ok": True}, {"Set-Cookie": "lac_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict" + ("; Secure" if c["tunnel"] else "")})
        if path == "/api/auth/password":  # change your own password
            u = c["user"]
            if not u: return self.send_json(401, {"error": "login required"})
            wait = rate_limited(c["ip"], u["username"].lower(), remote)
            if wait: return self.send_json(429, {"error": "too many attempts", "retry": wait})
            if not verify_pw(u.get("pw"), str(b.get("current") or "")): note_fail(c["ip"], u["username"].lower(), remote); return self.send_json(401, {"error": "current password is wrong"})
            new = str(b.get("password") or "")
            if len(new) < 8: return self.send_json(400, {"error": "use at least 8 characters"})
            with LOCK: u["pw"] = hash_pw(new); save_acc()
            drop_session(uid=u["id"]); t = new_session(u["id"], c["ip"], ua, "internet" if c["tunnel"] else "local")
            log(f"password changed for '{u['username']}'; other sessions signed out")
            return self.send_json(200, {"ok": True}, {"Set-Cookie": self.cookie(t, c)})
        return self.send_json(404, {"error": "not found"})
    def cookie(self, t, c): return f"lac_session={t}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Strict" + ("; Secure" if c["tunnel"] else "")
    # --- api ---
    MASTER_ONLY = ("/api/jobs", "/api/vram", "/api/lan", "/api/security", "/api/internet", "/api/accounts", "/api/tailscale", "/api/shutdown")
    def api(self, method, path, q, c):
        u = c["user"]; master = u["tier"] == "master"
        if path.startswith(self.MASTER_ONLY) and not master: return self.send_json(403, {"error": "only a Master account can do that"})
        if path == "/api/status" and method == "GET":
            return self.send_json(200, {"engine": engine_status(), "lmstudio_online": lm_models() is not None, "job": job_view(), "lan": SERVER["host"] == "0.0.0.0",
                                        "internet": tunnel_active(), "searxng": mochi_tools.sx_view(), "local": c["local"], "time": time.time()})
        if path == "/api/models" and method == "GET": return self.send_json(200, models_for(u))
        if path == "/api/vram" and method == "GET": return self.send_json(200, vram_view())
        if path == "/api/jobs" and method == "POST": return self.jobs(self.jbody())
        if path == "/api/settings":  # each account has its own UI settings
            sp = os.path.join(user_dir(u["id"]), "settings.json")
            if method == "GET": return self.send_json(200, jload(sp, {}))
            if method == "PUT":
                raw = self.body()
                if len(raw) > 512 * 1024: return self.send_json(413, {"error": "settings too large"})
                s = json.loads(raw or b"{}")
                if not isinstance(s, dict): raise ValueError("settings must be an object")
                jsave(sp, s); return self.send_json(200, {"ok": True})
        if path == "/api/lan":
            if method == "GET": return self.send_json(200, lan_view())
            if method == "POST": return self.lan(self.jbody(), c)
        if path == "/api/lan/firewall" and method == "GET": return self.send_json(200, firewall_view())
        if path == "/api/security" and method == "POST":
            if not c["local"]: return self.send_json(403, {"error": "change this on the PC itself"})
            b = self.jbody()
            if "localhost_no_login" in b:
                o = owner()
                if not b["localhost_no_login"] and not (o and o.get("pw")): return self.send_json(400, {"error": "create a password first"})
                CFG["localhost_no_login"] = bool(b["localhost_no_login"]); save_cfg()
            return self.send_json(200, {"localhost_no_login": CFG["localhost_no_login"]})
        if path == "/api/internet":
            if method == "GET": return self.send_json(200, tunnel_view(c["local"]))
            if method == "POST":
                if not c["local"]: return self.send_json(403, {"error": "the internet link can only be changed on the PC itself"})
                b = self.jbody()
                if ("enabled" in b and b["enabled"]) or ("autostart" in b and b["autostart"]):
                    if not has_password(): return self.send_json(400, {"error": "create a password first - the internet link always needs a login"})
                if "provider" in b:
                    if b["provider"] not in ("tailscale", "cloudflare"): return self.send_json(400, {"error": "unknown provider"})
                    if b["provider"] != provider():
                        if TUNNEL["state"] in ("on", "starting"): tunnel_stop()
                        TUNNEL.update(provider="", state="off", error="", enable_url="")  # an old error belongs to the old link type
                        CFG["internet_provider"] = b["provider"]; save_cfg()
                if "autostart" in b: CFG["internet_autostart"] = bool(b["autostart"]); save_cfg()
                if "enabled" in b:
                    if b["enabled"]: tunnel_start()
                    else: tunnel_stop()
                return self.send_json(200, tunnel_view(True))
        if path == "/api/tailscale" and method == "POST":
            if not c["local"]: return self.send_json(403, {"error": "Tailscale can only be controlled on the PC itself"})
            a = str(self.jbody().get("action") or "")
            if a not in ("disconnect", "reconnect", "service_stop", "service_start"): return self.send_json(400, {"error": "unknown action"})
            if not os.path.isfile(TAILSCALE): return self.send_json(400, {"error": "Tailscale is not installed"})
            if not ts_action(a): return self.send_json(409, {"error": "another Tailscale action is still running"})
            return self.send_json(200, {"ok": True, "busy": a})
        if path.startswith("/api/accounts"): return self.accounts(method, path, c)
        if path == "/api/tools" and method == "GET": return self.send_json(200, {"tools": mochi_tools.list_for(u)})
        if path == "/api/tools/execute" and method == "POST": return self.tool_execute(self.jbody(), c)
        if path.startswith("/api/memory"): return self.memory_api(method, path, u)
        if path == "/api/shutdown":
            if not c["local"]: return self.send_json(403, {"error": "Mochi can only be shut down from the PC itself"})
            if method == "GET": return self.send_json(200, shutdown_preview())
            if method == "POST":
                b = self.jbody()
                unload = bool(b.get("unload_models", True))
                restore = bool(b.get("restore_lan", True))
                threading.Timer(0.25, perform_shutdown, args=(unload, restore)).start()
                return self.send_json(200, {"ok": True})
        if path.startswith("/api/chats") or path == "/api/search": return self.chats(method, path, q, u)
        return self.send_json(404, {"error": "not found"})
    def accounts(self, method, path, c):
        me = c["user"]
        if path == "/api/accounts" and method == "GET":
            return self.send_json(200, {"accounts": [user_view(x, me) for x in sorted(users().values(), key=lambda x: x["created"])],
                                        "defaults": ACC.get("limited_defaults") or LIMIT_DEFAULTS, "model_choices": model_choices(), "tiers": TIERS})
        if path == "/api/accounts/defaults" and method == "PUT":
            b = self.jbody()
            with LOCK: ACC["limited_defaults"] = clean_limits(b, ACC.get("limited_defaults") or LIMIT_DEFAULTS); save_acc()
            return self.send_json(200, {"ok": True, "defaults": ACC["limited_defaults"]})
        if path == "/api/accounts" and method == "POST":
            b = self.jbody(); name = str(b.get("username") or "").strip(); pw = str(b.get("password") or ""); tier = b.get("tier") or "user"
            if not UNAME_RE.match(name): return self.send_json(400, {"error": "username: 3-32 letters, digits, . _ or -"})
            if find_user(name): return self.send_json(409, {"error": "that username is taken"})
            if len(pw) < 8: return self.send_json(400, {"error": "password: at least 8 characters"})
            if tier not in TIERS: return self.send_json(400, {"error": "unknown tier"})
            uid = "u" + secrets.token_hex(6)
            rec = {"id": uid, "username": name, "tier": tier, "active": True, "created": int(time.time()), "pw": hash_pw(pw), "by": me["id"]}
            if tier == "limited": rec["limits"] = dict(ACC.get("limited_defaults") or LIMIT_DEFAULTS)
            with LOCK: users()[uid] = rec; save_acc()
            user_dir(uid); log(f"account created: '{name}' ({TIERS[tier]}) by '{me['username']}'")
            return self.send_json(201, {"ok": True, "account": user_view(rec, me)})
        m = re.match(r"^/api/accounts/(u[0-9a-f]{12})$", path)
        if not m: return self.send_json(404, {"error": "not found"})
        t = get_user(m.group(1))
        if not t: return self.send_json(404, {"error": "no such account"})
        last_master = t["tier"] == "master" and t["active"] and len(active_masters()) <= 1
        if method == "DELETE":
            if t["id"] == me["id"]: return self.send_json(400, {"error": "you can't delete your own account"})
            if last_master: return self.send_json(400, {"error": "you can't delete the last active Master"})
            with LOCK: users().pop(t["id"], None); save_acc(); USAGE.pop(t["id"], None); jsave(USAGE_PATH, USAGE)
            drop_session(uid=t["id"]); INDEXES.pop(t["id"], None)
            shutil.rmtree(os.path.join(USERS, t["id"]), ignore_errors=True)
            log(f"account deleted: '{t['username']}' by '{me['username']}'")
            return self.send_json(200, {"ok": True})
        if method != "PATCH": return self.send_json(405, {"error": "method"})
        b = self.jbody(); changes = []
        with LOCK:
            if "active" in b and bool(b["active"]) != t["active"]:
                if not b["active"]:
                    if t["id"] == me["id"]: return self.send_json(400, {"error": "you can't turn off your own account"})
                    if last_master: return self.send_json(400, {"error": "you can't turn off the last active Master"})
                t["active"] = bool(b["active"]); changes.append("active" if t["active"] else "inactive")
            if "tier" in b and b["tier"] != t["tier"]:
                if b["tier"] not in TIERS: return self.send_json(400, {"error": "unknown tier"})
                if t["id"] == me["id"]: return self.send_json(400, {"error": "you can't change your own tier"})
                if last_master: return self.send_json(400, {"error": "you can't demote the last active Master"})
                t["tier"] = b["tier"]; changes.append("tier " + t["tier"])
                if t["tier"] == "limited" and not t.get("limits"): t["limits"] = dict(ACC.get("limited_defaults") or LIMIT_DEFAULTS)
            if "username" in b and str(b["username"]).strip() != t["username"]:
                n = str(b["username"]).strip()
                if not UNAME_RE.match(n): return self.send_json(400, {"error": "username: 3-32 letters, digits, . _ or -"})
                if find_user(n): return self.send_json(409, {"error": "that username is taken"})
                t["username"] = n; changes.append("renamed")
            if "password" in b:
                pw = str(b["password"] or "")
                if len(pw) < 8: return self.send_json(400, {"error": "password: at least 8 characters"})
                t["pw"] = hash_pw(pw); changes.append("password reset")
            if "limits" in b and isinstance(b["limits"], dict): t["limits"] = clean_limits(b["limits"], limits_of(t)); changes.append("limits")
            save_acc()
        if "inactive" in changes: drop_session(uid=t["id"])  # turned off: signed out everywhere at once
        if "password reset" in changes: drop_session(uid=t["id"], keep=tok_hash(c["token"]) if c["token"] else None)
        log(f"account '{t['username']}' changed by '{me['username']}': {', '.join(changes) or 'nothing'}")
        return self.send_json(200, {"ok": True, "account": user_view(t, me)})
    def memory_api(self, method, path, u):
        if u["tier"] == "limited": return self.send_json(403, {"error": "memory is not available for limited accounts"})
        if path == "/api/memory" and method == "GET":
            return self.send_json(200, {"memories": mochi_tools.mem_list(u["id"])})
        if path == "/api/memory" and method == "DELETE":
            n = mochi_tools.mem_delete(u["id"], everything=True)
            return self.send_json(200, {"ok": True, "deleted": n})
        m = re.match(r"^/api/memory/(m[0-9a-f]{8})$", path)
        if m and method == "DELETE":
            n = mochi_tools.mem_delete(u["id"], mid=m.group(1))
            return self.send_json(200, {"ok": True, "deleted": n})
        return self.send_json(404, {"error": "not found"})
    def tool_execute(self, b, c):
        u = c["user"]
        if not u: return self.send_json(401, {"error": "login required"})
        if u["tier"] == "limited":
            return self.send_json(403, {"error": "tools are not permitted for limited accounts"})
        name = str(b.get("tool") or b.get("name") or "").strip()
        args = b.get("arguments") or {}
        if isinstance(args, str):
            try: args = json.loads(args)
            except Exception: args = {}
        if not isinstance(args, dict):
            return self.send_json(400, {"error": "arguments must be a JSON object"})
        ctx = {"local": c["local"], "tunnel": c["tunnel"], "confirmed": bool(b.get("confirmed")), "max_chars": b.get("max_chars")}
        res = mochi_tools.execute(name, args, u, ctx)
        status = res.pop("status", None)
        if status: return self.send_json(status, res)
        return self.send_json(200, res)
    def jobs(self, b):
        action = b.get("action"); key = b.get("key")
        if action == "engine_start":
            em = engine_model(key or "27b")
            if not em: return self.send_json(400, {"error": "unknown engine model"})
            cur = engine_running()
            if cur and cur["id"] == em["id"]: return self.send_json(409, {"error": f"the {em['short']} is already running"})
            label = f"Switching to the {em['short']} (stops the {cur['short']})" if cur else f"Starting the {em['short']} (unloads LM Studio models)"
            ok = start_job(action, label, lambda: run_script(em["start"], "-UnloadLMStudio", wait_engine=em["id"]), em["expect"] + (6 if cur else 0), target=em["id"])
        elif action == "engine_stop":
            cur = engine_running()
            ok = start_job(action, f"Stopping the {cur['short'] if cur else 'engine model'}", lambda: run_script("Stop-Qwen27B.ps1"), 4, target=cur["id"] if cur else None)
        elif action in ("lm_load", "lm_unload"):
            models = lm_models(0)
            if models is None: return self.send_json(503, {"error": "LM Studio is offline"})
            m = next((m for m in models if m.get("key") == key), None)
            if not m: return self.send_json(400, {"error": "unknown model"})
            if action == "lm_load":
                if engine_status()["online"] and not b.get("force"): return self.send_json(409, {"error": "an engine model (27B/9B) is running and uses most of the VRAM - stop it first", "code": "engine_running"})
                # generic context: 16K for small LLMs (< 5.5 GB file), 8K for bigger ones; embeddings use LM Studio's default
                ctx = (16384 if (m.get("size_bytes") or 0) < 5.5e9 else 8192) if m.get("type") in ("llm", "vlm") else None
                ok = start_job(action, f"Loading {m.get('display_name') or key}", lambda: lm_load(key, ctx), max(6, (m.get("size_bytes") or 4e9) / 6e8))
            else:
                ok = start_job(action, f"Unloading {m.get('display_name') or key}", lambda: lm_unload(key), 3)
        else: return self.send_json(400, {"error": "unknown action"})
        if not ok: return self.send_json(409, {"error": "another task is still running"})
        return self.send_json(202, {"ok": True, "job": job_view()})
    def lan(self, b, c):
        if not c["local"]: return self.send_json(403, {"error": "LAN mode can only be changed on the PC itself"})
        if "autostart" in b:
            if b["autostart"] and not has_password(): return self.send_json(400, {"error": "create a password first (LAN mode always needs a login)"})
            autostart_set(bool(b["autostart"]))
        if "enabled" in b:
            on = bool(b["enabled"])
            if on and not has_password(): return self.send_json(400, {"error": "create a password first (LAN mode always needs a login)"})
            CFG["lan"] = on; save_cfg()
            threading.Timer(0.4, rebind, args=("0.0.0.0" if on else "127.0.0.1",)).start()
        v = lan_view()
        if "enabled" in b: v["enabled"] = bool(b["enabled"]); v["switching"] = True
        return self.send_json(200, v)
    def chats(self, method, path, q, u):
        uid = u["id"]; IDX = index_for(uid)
        if path == "/api/search":
            return self.send_json(200, {"results": search_user_chats(uid, (q.get("q") or [""])[0], 50)})
        if path == "/api/chats":
            if method == "GET": return self.send_json(200, {"chats": sorted(IDX.values(), key=lambda m: (-int(m["pinned"]), -m["updated"]))})
        if path == "/api/chats/import" and method == "POST":
            b = self.jbody(); n = 0
            for ch in (b.get("chats") or [])[:500]:
                cid = str(ch.get("id") or "")
                if not ID_RE.match(cid) or cid in IDX: continue
                save_chat(uid, clean_chat(ch, cid)); n += 1
            return self.send_json(200, {"imported": n})
        m = re.match(r"^/api/chats/([A-Za-z0-9_-]{4,64})(/export)?$", path)
        if not m: return self.send_json(404, {"error": "not found"})
        cid, export = m.group(1), m.group(2)
        if export:
            c = jload(chat_path(uid, cid), None)
            if not c: return self.send_json(404, {"error": "no such chat"})
            fmt = (q.get("format") or ["md"])[0]
            name = re.sub(r"[^\w\- ]+", "", c.get("title") or "chat").strip()[:60] or "chat"
            data = (to_markdown(c) if fmt == "md" else json.dumps(c, ensure_ascii=False, indent=1)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8" if fmt == "md" else "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}.{'md' if fmt == 'md' else 'json'}")
            self.send_header("Content-Length", str(len(data))); self.sec_headers(); self.end_headers(); self.wfile.write(data); return
        if method == "GET":
            c = jload(chat_path(uid, cid), None)
            return self.send_json(200, c) if c else self.send_json(404, {"error": "no such chat"})
        if method == "PUT":
            c = clean_chat(self.jbody(), cid); rev = save_chat(uid, c)
            return self.send_json(200, {"ok": True, "rev": rev, "meta": IDX[cid]})
        if method == "PATCH":
            b = self.jbody(); c = jload(chat_path(uid, cid), None)
            if not c: return self.send_json(404, {"error": "no such chat"})
            if "title" in b: c["title"] = str(b["title"])[:120]
            if "pinned" in b: c["pinned"] = bool(b["pinned"])
            c["updated"] = int(time.time() * 1000); rev = save_chat(uid, c)
            return self.send_json(200, {"ok": True, "rev": rev, "meta": IDX[cid]})
        if method == "DELETE":
            with LOCK:
                try: os.remove(chat_path(uid, cid))
                except FileNotFoundError: pass
                IDX.pop(cid, None)
            return self.send_json(200, {"ok": True})
        return self.send_json(405, {"error": "method"})
    # --- proxy ---
    def proxy(self, method, path, query, c):
        parts = path.split("/", 3)
        if len(parts) < 4 or parts[2] not in UP: return self.send_json(404, {"error": "unknown backend"})
        rest = "/" + parts[3]; backend = parts[2]; u = c["user"]
        if not rest.startswith("/v1/") or ".." in rest or method not in ("GET", "POST"): return self.send_json(404, {"error": "path not allowed"})
        body = self.body() if method == "POST" else None
        if u["tier"] != "master":
            # Users and Limited Users: chat with models that are already running; nothing that loads, starts or changes models
            if not ((method == "GET" and rest == "/v1/models") or (method == "POST" and rest == "/v1/chat/completions")):
                return self.send_json(403, {"error": "not allowed for your account"})
            if method == "POST":
                try: req = json.loads(body or b"{}")
                except ValueError: return self.send_json(400, {"error": "invalid JSON"})
                if not isinstance(req, dict): return self.send_json(400, {"error": "invalid request"})
                mid = str(req.get("model") or "")
                if u["tier"] == "limited" and f"{backend}:{mid}" not in limits_of(u)["models"]:
                    return self.send_json(403, {"error": "your account can't use this model"})
                if not model_online(backend, mid): return self.send_json(409, {"error": "that model isn't running - ask the owner to start it"})
                if u["tier"] == "limited":
                    req.pop("tools", None); req.pop("tool_choice", None)
                    cap = limits_of(u)["max_tokens"]
                    req["max_tokens"] = min(int(req.get("max_tokens") or cap), cap); req.pop("max_completion_tokens", None)
                    if req.get("reasoning_budget"): req["reasoning_budget"] = min(int(req["reasoning_budget"]), cap)
                    if not take_message(u): return self.send_json(429, {"error": f"daily limit reached ({limits_of(u)['daily_cap']} messages) - try again tomorrow"})
                    body = json.dumps(req).encode()
        conn = http.client.HTTPConnection(UP[backend], timeout=900)
        try:
            conn.request(method, rest + ("?" + query if query else ""), body=body, headers={"Content-Type": "application/json", "Accept": self.headers.get("Accept", "*/*")})
            r = conn.getresponse()
        except Exception as e:
            conn.close(); return self.send_json(502, {"error": f"{backend} backend unreachable: {e}"})
        try:
            ctype = r.getheader("Content-Type", "application/json")
            if "text/event-stream" in ctype:
                self.send_response(r.status)
                self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "close"); self.sec_headers()
                self.end_headers(); self.close_connection = True
                while True:
                    chunk = r.read1(65536)
                    if not chunk: break
                    self.wfile.write(chunk); self.wfile.flush()
            else:
                data = r.read()
                self.send_response(r.status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store"); self.sec_headers(); self.end_headers(); self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        finally:
            conn.close()
    # --- static ---
    def static(self, path):
        if path in ("", "/"): path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/").replace("/", os.sep)))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full): return self.send_json(404, {"error": "not found"})
        with open(full, "rb") as f: data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(os.path.splitext(full)[1], "application/octet-stream")); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache"); self.sec_headers()
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(data)

class Srv(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
def serve(host):
    srv = Srv((host, PORT), H)
    SERVER.update(srv=srv, host=host)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True).start()
    log(f"listening on http://{host}:{PORT}/" + ("  (LAN mode: private networks only, login required)" if host == "0.0.0.0" else ""))
def rebind(host):
    with LOCK:
        old = SERVER["srv"]
        if old and SERVER["host"] == host: return
        if old: old.shutdown(); old.server_close()
        try: serve(host); SERVER["error"] = ""
        except OSError as e:
            SERVER["error"] = f"could not listen on {host}:{PORT}: {e}"; log(SERVER["error"])
            CFG["lan"] = False; save_cfg(); serve("127.0.0.1")

if __name__ == "__main__":
    if ARGS.log:
        os.makedirs(os.path.dirname(os.path.abspath(ARGS.log)), exist_ok=True)
        sys.stdout = sys.stderr = open(ARGS.log, "a", encoding="utf-8", buffering=1)
    migrate_accounts()
    _stale_tunnel()
    _stale_searxng()
    INITIAL_STATE["lan"] = bool(CFG.get("lan") and has_password())
    INITIAL_STATE["internet_autostart"] = bool(CFG.get("internet_autostart"))
    if ARGS.lan:
        if has_password(): CFG["lan"] = True; save_cfg()
        else: log("--lan ignored: no password set yet")
    host = "0.0.0.0" if CFG.get("lan") and has_password() else "127.0.0.1"
    log(f"Local AI Chat v2 (engine {UP['engine']}, LM Studio {UP['lmstudio']}, data {DATA})")
    try: serve(host)
    except OSError as e:
        log(f"bind {host} failed: {e}");
        if host != "127.0.0.1": serve("127.0.0.1")
        else: raise
    def _post_start():
        try: _stale_funnel()
        except Exception as e: log(f"funnel check failed: {e}")
        try:
            eng = engine_running(); INITIAL_STATE["engine"] = eng["id"] if eng else None
            INITIAL_STATE["lmstudio"] = [m.get("key") for m in (lm_models(0) or []) if m.get("loaded_instances")]
        except Exception: pass
    threading.Thread(target=_post_start, daemon=True).start()
    if CFG.get("internet_autostart"):
        if has_password(): log("internet link: auto-start"); tunnel_start()
        else: log("internet auto-start skipped: no password set yet")
    try:
        while not SHUTDOWN_EVT.wait(3600): pass
    except KeyboardInterrupt: pass
    finally: _cleanup_on_exit()
