"""Mochi tools - every tool the chat models can call, declared once.

server.py serves the schemas (GET /api/tools, filtered by account tier) and runs them (POST /api/tools/execute);
the browser no longer hardcodes any tool. To add a tool, write one function with the @tool decorator below.

Risk levels (the browser shows a confirmation according to these; the server enforces 'host'):
  safe     - reads nothing private, changes nothing that matters (math, time, memory)   -> always runs
  network  - talks to the internet (web search, fetch a page, weather)                   -> runs automatically unless
  files    - reads / writes the account's own Mochi files folder                            "Auto-run tools" is off
  host     - runs code on the PC (run_python)                                            -> ALWAYS asks first
Tiers: Master and User accounts get tools; Limited accounts never do. Some tools are Master only.
"""
import ast, base64, datetime, gzip, html.parser, http.client, ipaddress, json, math, operator, os, re, secrets, socket, ssl, subprocess, sys, threading, time, zlib
from urllib.parse import urlsplit, urlencode, urljoin, quote

HOOKS = {}  # set by server.py: log, user_dir, search_chats, system_status, kill_with_us
def configure(**kw): HOOKS.update(kw)
def log(msg):
    f = HOOKS.get("log")
    if f: f(msg)

TOOLS = {}
RISKS = ("safe", "network", "files", "host")
class ToolError(Exception): pass

def tool(name, label, desc, params=None, required=(), risk="safe", tiers=("master", "user"), group="Basics", max_chars=4000, available=None):
    assert risk in RISKS
    def deco(fn):
        TOOLS[name] = {"name": name, "label": label, "desc": desc, "params": params or {}, "required": list(required), "risk": risk,
                       "tiers": tuple(tiers), "group": group, "fn": fn, "max_chars": max_chars, "available": available}
        return fn
    return deco

def schema(t):
    return {"type": "function", "function": {"name": t["name"], "description": t["desc"],
            "parameters": {"type": "object", "properties": t["params"], "required": t["required"]}}}

def allowed(t, user): return bool(user) and user.get("tier") in t["tiers"]

def list_for(user):
    out = []
    for t in TOOLS.values():
        if not allowed(t, user): continue
        note = t["available"]() if t["available"] else ""
        out.append({"name": t["name"], "label": t["label"], "group": t["group"], "risk": t["risk"], "unavailable": note or "", "schema": schema(t)})
    return out

def execute(name, args, user, ctx):
    """ctx: {local, tunnel, confirmed, max_chars}. Returns {ok, result, images?} or {ok: False, error}."""
    t = TOOLS.get(name)
    if not t: return {"ok": False, "error": f"unknown tool '{name}'"}
    if not allowed(t, user): return {"ok": False, "error": f"your account can't use the tool '{name}'", "status": 403}
    if t["risk"] == "host" and not ctx.get("confirmed"):
        return {"ok": False, "error": f"'{name}' needs your confirmation every time", "status": 428}
    if t["available"]:
        why = t["available"]()
        if why: return {"ok": False, "error": why}
    if not isinstance(args, dict): return {"ok": False, "error": "arguments must be a JSON object"}
    try:
        res = t["fn"](args, user, ctx)
    except ToolError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # a tool bug must never take the chat down
        log(f"tool {name} crashed: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    images = []
    if isinstance(res, tuple): res, images = res
    text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, indent=1)
    cap = max(500, min(int(ctx.get("max_chars") or t["max_chars"]), t["max_chars"], 20000))
    if len(text) > cap: text = text[:cap].rstrip() + f"\n…[cut to {cap} characters]"
    out = {"ok": True, "result": text or "(empty result)"}
    if images: out["images"] = images
    return out

def _s(args, key, default="", limit=2000):
    v = args.get(key, default)
    if v is None: v = default
    return str(v).strip()[:limit]
def _i(args, key, default, lo, hi):
    try: v = int(args.get(key, default))
    except (TypeError, ValueError): v = default
    return max(lo, min(hi, v))

# ============================================================== basics
@tool("get_current_datetime", "Date & time", "Get the current local date, time, weekday and timezone of the PC Mochi runs on.", group="Basics")
def t_datetime(args, user, ctx):
    now = datetime.datetime.now().astimezone()
    off = now.strftime("%z")
    return {"local": now.strftime("%A, %d %B %Y, %H:%M:%S"), "iso": now.isoformat(timespec="seconds"),
            "timezone": now.tzname(), "utc_offset": f"{off[:3]}:{off[3:]}", "weekday": now.strftime("%A")}

SAFE_MATH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
SAFE_MATH_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x), "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "exp": math.exp, "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2, "ceil": math.ceil, "floor": math.floor,
    "factorial": math.factorial, "degrees": math.degrees, "radians": math.radians, "hypot": math.hypot, "gcd": math.gcd, "lcm": math.lcm,
    "comb": math.comb, "perm": math.perm, "pi": math.pi, "e": math.e, "tau": math.tau,
}
def eval_safe_math(node):
    if isinstance(node, ast.Expression): return eval_safe_math(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)) and not isinstance(node.value, bool): return node.value
        raise ValueError("only numbers are allowed")
    if isinstance(node, ast.Name):
        v = SAFE_MATH_FUNCS.get(node.id)
        if isinstance(v, (int, float)): return v
        raise ValueError(f"unknown symbol: {node.id}")
    if isinstance(node, ast.BinOp):
        op = type(node.op)
        if op not in SAFE_MATH_OPS: raise ValueError(f"operator {op.__name__} not permitted")
        left, right = eval_safe_math(node.left), eval_safe_math(node.right)
        if op == ast.Pow and (abs(right) > 500 or abs(left) > 1e10): raise ValueError("exponent too large")
        return SAFE_MATH_OPS[op](left, right)
    if isinstance(node, ast.UnaryOp):
        op = type(node.op)
        if op not in SAFE_MATH_OPS: raise ValueError(f"operator {op.__name__} not permitted")
        return SAFE_MATH_OPS[op](eval_safe_math(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_MATH_FUNCS or not callable(SAFE_MATH_FUNCS[node.func.id]):
            raise ValueError(f"function '{getattr(node.func, 'id', '?')}' not permitted")
        a = [eval_safe_math(x) for x in node.args]
        if node.func.id == "factorial" and a and a[0] > 2000: raise ValueError("factorial argument too large")
        return SAFE_MATH_FUNCS[node.func.id](*a)
    if isinstance(node, (ast.List, ast.Tuple)): return [eval_safe_math(x) for x in node.elts]
    raise ValueError(f"unsupported syntax: {type(node).__name__}")

@tool("calculate", "Calculator", "Evaluate a math expression exactly (Python syntax). Functions: sqrt, cbrt, sin, cos, tan, asin, acos, atan, atan2, "
      "log (natural), log10, log2, exp, factorial, comb, perm, gcd, lcm, hypot, floor, ceil, round, abs, min, max, sum, degrees, radians; "
      "constants pi, e, tau. Example: '(250 * 1.18) / 12' or 'sqrt(144) * pi'.",
      {"expression": {"type": "string", "description": "The expression, e.g. '2**10 + sqrt(2)'."}}, ["expression"], group="Basics")
def t_calculate(args, user, ctx):
    expr = _s(args, "expression", limit=600).replace("^", "**").replace("×", "*").replace("÷", "/")
    if not expr: raise ToolError("no expression provided")
    try: val = eval_safe_math(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError) as e: raise ToolError(f"math error: {e}")
    if isinstance(val, float) and val.is_integer() and abs(val) < 1e15: val = int(val)
    return str(val)

_UNITS = {  # dimension -> {unit: factor to the base unit}
    "length (m)": {"m": 1, "km": 1e3, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "µm": 1e-6, "nm": 1e-9, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
                   "yd": .9144, "yard": .9144, "ft": .3048, "foot": .3048, "feet": .3048, "in": .0254, "inch": .0254, "inches": .0254, "nmi": 1852,
                   "au": 1.495978707e11, "ly": 9.4607304725808e15, "lightyear": 9.4607304725808e15},
    "mass (kg)": {"kg": 1, "g": 1e-3, "mg": 1e-6, "ug": 1e-9, "t": 1e3, "tonne": 1e3, "ton": 907.18474, "lb": .45359237, "lbs": .45359237,
                  "pound": .45359237, "oz": .028349523125, "ounce": .028349523125, "st": 6.35029318, "stone": 6.35029318, "ct": 2e-4, "carat": 2e-4},
    "volume (l)": {"l": 1, "liter": 1, "litre": 1, "ml": 1e-3, "cl": 1e-2, "dl": .1, "m3": 1e3, "cm3": 1e-3, "cc": 1e-3, "gal": 3.785411784,
                   "gallon": 3.785411784, "ukgal": 4.54609, "qt": .946352946, "pt": .473176473, "cup": .2365882365, "floz": .0295735295625,
                   "tbsp": .01478676478125, "tsp": .00492892159375, "ft3": 28.316846592, "in3": .016387064},
    "area (m2)": {"m2": 1, "km2": 1e6, "cm2": 1e-4, "mm2": 1e-6, "ha": 1e4, "hectare": 1e4, "acre": 4046.8564224, "ft2": .09290304, "sqft": .09290304,
                  "in2": 6.4516e-4, "yd2": .83612736, "mi2": 2589988.110336},
    "speed (m/s)": {"m/s": 1, "km/h": 1 / 3.6, "kmh": 1 / 3.6, "kph": 1 / 3.6, "mph": .44704, "knot": 1852 / 3600, "kn": 1852 / 3600, "ft/s": .3048, "mach": 343},
    "time (s)": {"s": 1, "sec": 1, "second": 1, "seconds": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "min": 60, "minute": 60, "minutes": 60, "h": 3600,
                 "hr": 3600, "hour": 3600, "hours": 3600, "day": 86400, "days": 86400, "week": 604800, "weeks": 604800, "month": 2629746,
                 "year": 31556952, "years": 31556952},
    "data (bytes)": {"b": 1, "byte": 1, "bytes": 1, "bit": .125, "bits": .125, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "pb": 1e15,
                     "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4, "kbit": 125, "mbit": 125e3, "gbit": 125e6},
    "energy (J)": {"j": 1, "kj": 1e3, "mj": 1e6, "cal": 4.184, "kcal": 4184, "wh": 3600, "kwh": 3.6e6, "ev": 1.602176634e-19, "btu": 1055.05585262},
    "pressure (Pa)": {"pa": 1, "kpa": 1e3, "mpa": 1e6, "hpa": 100, "bar": 1e5, "mbar": 100, "atm": 101325, "psi": 6894.757293168, "mmhg": 133.322387415, "torr": 133.322368421},
    "power (W)": {"w": 1, "kw": 1e3, "mw": 1e6, "hp": 745.69987158227, "ps": 735.49875},
}
_TEMP = {"c": "C", "°c": "C", "celsius": "C", "f": "F", "°f": "F", "fahrenheit": "F", "k": "K", "kelvin": "K"}
def _unit(u):
    k = str(u or "").strip().lower().replace(" ", "").replace("²", "2").replace("³", "3").replace("^", "")
    if k in _TEMP: return "temperature", _TEMP[k]
    for dim, tab in _UNITS.items():
        if k in tab: return dim, tab[k]
        if k.endswith("s") and k[:-1] in tab: return dim, tab[k[:-1]]
    raise ToolError(f"unknown unit '{u}'")
@tool("unit_convert", "Unit converter", "Convert a value between units: length, mass, volume, area, speed, time, data size (KB=1000, KiB=1024), energy, "
      "pressure, power and temperature (C, F, K). Use calculate for anything else; use currency_convert for money.",
      {"value": {"type": "number"}, "from_unit": {"type": "string", "description": "e.g. 'km', 'lb', 'F', 'GiB'"}, "to_unit": {"type": "string"}},
      ["value", "from_unit", "to_unit"], group="Basics")
def t_unit(args, user, ctx):
    try: v = float(args.get("value"))
    except (TypeError, ValueError): raise ToolError("value must be a number")
    (d1, f1), (d2, f2) = _unit(args.get("from_unit")), _unit(args.get("to_unit"))
    if d1 != d2: raise ToolError(f"can't convert {d1.split(' (')[0]} to {d2.split(' (')[0]}")
    if d1 == "temperature":
        k = {"C": v + 273.15, "F": (v - 32) * 5 / 9 + 273.15, "K": v}[f1]
        r = {"C": k - 273.15, "F": (k - 273.15) * 9 / 5 + 32, "K": k}[f2]
    else: r = v * f1 / f2
    r = float(f"{r:.10g}")
    return f"{args.get('value')} {args.get('from_unit')} = {int(r) if r.is_integer() and abs(r) < 1e15 else r} {args.get('to_unit')}"

# ============================================================== memory (per account)
MEM_LOCK = threading.RLock()
MEM_MAX, MEM_LEN = 200, 500
def _mem_path(uid): return os.path.join(HOOKS["user_dir"](uid), "memory.json")
def mem_list(uid):
    try:
        with open(_mem_path(uid), encoding="utf-8") as f: d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError): return []
def _mem_save(uid, items):
    p = _mem_path(uid); tmp = p + "." + secrets.token_hex(3) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, p)
def mem_add(uid, text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()[:MEM_LEN]
    if not text: raise ToolError("nothing to remember")
    with MEM_LOCK:
        items = mem_list(uid)
        for m in items:
            if m["text"].lower() == text.lower(): return m, False
        m = {"id": "m" + secrets.token_hex(4), "text": text, "created": int(time.time())}
        items.append(m); _mem_save(uid, items[-MEM_MAX:]); return m, True
def mem_delete(uid, mid=None, everything=False):
    with MEM_LOCK:
        items = mem_list(uid); keep = [] if everything else [m for m in items if m["id"] != mid]
        _mem_save(uid, keep); return len(items) - len(keep)

@tool("remember", "Remember", "Save a lasting fact about the user or their preferences for future chats (e.g. 'Prefers metric units', "
      "'Their GPU is an RX 9070 XT'). Only save things the user would want remembered; keep each fact short.",
      {"fact": {"type": "string", "description": "One short fact, written in the third person."}}, ["fact"], group="Memory")
def t_remember(args, user, ctx):
    m, new = mem_add(user["id"], args.get("fact"))
    return f"Remembered (id {m['id']}): {m['text']}" if new else f"Already remembered (id {m['id']}): {m['text']}"

@tool("recall", "Recall", "Look through the facts saved with 'remember'. Give a query to filter, or leave it empty to list everything.",
      {"query": {"type": "string", "description": "Optional words to look for."}}, group="Memory")
def t_recall(args, user, ctx):
    q = _s(args, "query", limit=200).lower(); items = mem_list(user["id"])
    words = [w for w in re.split(r"\W+", q) if len(w) > 2]
    hits = [m for m in items if not words or any(w in m["text"].lower() for w in words)]
    if not items: return "No memories saved yet."
    if not hits: return f"No saved memory matches '{q}'. ({len(items)} memories in total.)"
    return "\n".join(f"- [{m['id']}] {m['text']}" for m in hits[-40:])

@tool("forget", "Forget", "Delete one saved memory by its id (see recall).", {"id": {"type": "string"}}, ["id"], group="Memory")
def t_forget(args, user, ctx):
    n = mem_delete(user["id"], _s(args, "id", limit=20))
    return "Forgotten." if n else "No memory with that id."

# ============================================================== chats & PC
@tool("search_chats", "Search past chats", "Search the user's earlier Mochi conversations (titles and messages) for a word or phrase.",
      {"query": {"type": "string"}}, ["query"], group="Memory", max_chars=3000)
def t_search_chats(args, user, ctx):
    q = _s(args, "query", limit=100)
    if not q: raise ToolError("no query")
    res = HOOKS["search_chats"](user["id"], q, 8)
    if not res: return f"No earlier chat mentions '{q}'."
    fmt = lambda ms: time.strftime("%Y-%m-%d", time.localtime((ms or 0) / 1000))
    return "\n".join(f"- {r.get('title') or 'Untitled'} ({fmt(r.get('updated'))}): {r.get('snippet', '')}" for r in res)

@tool("system_status", "PC status", "Show what is running on the PC: the loaded AI models, GPU memory use, LAN / internet link state and web search.",
      tiers=("master",), group="PC")
def t_status(args, user, ctx): return HOOKS["system_status"]()

# ============================================================== files (per account sandbox folder)
FILE_MAX_WRITE = 1_000_000
def files_root(uid):
    d = os.path.join(HOOKS["user_dir"](uid), "files"); os.makedirs(d, exist_ok=True); return os.path.realpath(d)
def _safe_path(uid, rel, must_exist=False):
    root = files_root(uid); rel = str(rel or ".").strip().replace("\\", "/").lstrip("/")
    if re.match(r"^[A-Za-z]:", rel) or rel.startswith("~"): raise ToolError("use a path inside the Mochi files folder, like 'notes/todo.md'")
    p = os.path.realpath(os.path.join(root, rel))
    if p != root and not p.startswith(root + os.sep): raise ToolError("that path is outside the Mochi files folder")
    if must_exist and not os.path.exists(p): raise ToolError(f"'{rel}' does not exist (use list_files)")
    return root, p
def _rel(root, p): return os.path.relpath(p, root).replace("\\", "/")

@tool("list_files", "List files", "List files and folders in the user's private Mochi files folder (the only folder Mochi's file tools and run_python can use).",
      {"path": {"type": "string", "description": "Sub-folder, default the top folder."}}, risk="files", group="Files", max_chars=4000)
def t_list(args, user, ctx):
    root, p = _safe_path(user["id"], args.get("path") or ".", True)
    if os.path.isfile(p): return f"{_rel(root, p)} is a file ({os.path.getsize(p)} bytes)."
    rows = []
    for e in sorted(os.scandir(p), key=lambda e: (not e.is_dir(), e.name.lower())):
        if e.name.startswith(".mochi"): continue
        st = e.stat()
        rows.append(f"{e.name}/" if e.is_dir() else f"{e.name}  ({st.st_size:,} bytes, {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))})")
        if len(rows) >= 300: rows.append("…"); break
    return (f"Folder '{_rel(root, p)}':\n" + "\n".join(rows)) if rows else f"Folder '{_rel(root, p)}' is empty."

@tool("read_file", "Read file", "Read a text file from the Mochi files folder.",
      {"path": {"type": "string"}, "start_line": {"type": "integer", "description": "First line to return (1-based), default 1."}},
      ["path"], risk="files", group="Files", max_chars=8000)
def t_read(args, user, ctx):
    root, p = _safe_path(user["id"], args.get("path"), True)
    if os.path.isdir(p): raise ToolError("that is a folder (use list_files)")
    with open(p, "rb") as f: raw = f.read(4_000_000)
    if b"\x00" in raw[:4096]: return f"{_rel(root, p)} is a binary file ({os.path.getsize(p):,} bytes); it can't be shown as text."
    lines = raw.decode("utf-8", "replace").splitlines()
    start = _i(args, "start_line", 1, 1, max(1, len(lines)))
    body = "\n".join(lines[start - 1:])
    return f"{_rel(root, p)} (lines {start}-{len(lines)} of {len(lines)}):\n{body}"

@tool("write_file", "Write file", "Create or overwrite a text file in the Mochi files folder (folders are created as needed). Set append=true to add to the end.",
      {"path": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}}, ["path", "content"], risk="files", group="Files")
def t_write(args, user, ctx):
    root, p = _safe_path(user["id"], args.get("path"))
    if p == root or os.path.isdir(p): raise ToolError("give a file name, not a folder")
    content = str(args.get("content") if args.get("content") is not None else "")
    if len(content.encode()) > FILE_MAX_WRITE: raise ToolError("content too large (max 1 MB)")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a" if args.get("append") else "w", encoding="utf-8", newline="\n") as f: f.write(content)
    return f"{'Appended to' if args.get('append') else 'Saved'} {_rel(root, p)} ({os.path.getsize(p):,} bytes)."

# ============================================================== run_python (limited sandbox, always asks)
PY_SITE = os.environ.get("MOCHI_PYTHON_SITE", r"C:\Dev\Tools\mochi-python\Lib\site-packages")
SANDBOX_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mochi_sandbox.py")
PY_TIMEOUT, PY_MEM_MB = 30, 2048

def _job_limits(p, mem_mb):
    """Own Windows job object for one run: no child processes, a memory cap, killed when the handle closes."""
    if os.name != "nt": return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    h = k32.CreateJobObjectW(None, None)
    class BASIC(ctypes.Structure):
        _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD), ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]
    class IOC(ctypes.Structure): _fields_ = [(n, ctypes.c_uint64) for n in ("r1", "r2", "r3", "r4", "r5", "r6")]
    class EXT(ctypes.Structure):
        _fields_ = [("basic", BASIC), ("io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t), ("jm", ctypes.c_size_t), ("ppm", ctypes.c_size_t), ("pjm", ctypes.c_size_t)]
    info = EXT()
    info.basic.LimitFlags = 0x2000 | 0x8 | 0x100  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS | PROCESS_MEMORY
    info.basic.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = mem_mb * 2 ** 20
    k32.SetInformationJobObject(wintypes.HANDLE(h), 9, ctypes.byref(info), ctypes.sizeof(info))
    k32.AssignProcessToJobObject(wintypes.HANDLE(h), wintypes.HANDLE(int(p._handle)))
    return lambda: k32.CloseHandle(wintypes.HANDLE(h))

IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}
@tool("run_python", "Run Python", "Run Python 3.13 code in Mochi's sandbox and get stdout/stderr. numpy, pandas, matplotlib and sympy are installed. "
      "The working folder is the user's Mochi files folder (read/write files there with relative paths). No internet, no other folders, "
      "no programs, 30 s limit. Save charts with plt.savefig('chart.png') - saved images are shown to the user. Print the results you need.",
      {"code": {"type": "string", "description": "Python code to run."}}, ["code"], risk="host", tiers=("master",), group="Code", max_chars=6000)
def t_python(args, user, ctx):
    code = str(args.get("code") or "")
    if not code.strip(): raise ToolError("no code provided")
    if len(code) > 65536: raise ToolError("code too long (max 64 KB)")
    root = files_root(user["id"])
    cache = os.path.join(root, ".mochi-cache")
    for sub in ("tmp", "mpl"): os.makedirs(os.path.join(cache, sub), exist_ok=True)
    py = sys.executable
    sysroot = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env = {"SYSTEMROOT": sysroot, "WINDIR": sysroot, "PATH": os.pathsep.join([os.path.dirname(py), os.path.join(sysroot, "System32")]),
           "MOCHI_SITE_PACKAGES": PY_SITE,
           "TEMP": os.path.join(cache, "tmp"), "TMP": os.path.join(cache, "tmp"), "HOME": cache, "USERPROFILE": cache,
           "MPLBACKEND": "Agg", "MPLCONFIGDIR": os.path.join(cache, "mpl"), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    before = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if not d.startswith(".mochi")]
        for f in fn: before[os.path.join(dp, f)] = os.path.getmtime(os.path.join(dp, f))
    flags = 0x08000000 if os.name == "nt" else 0
    p = subprocess.Popen([py, "-I", "-B", SANDBOX_SCRIPT], cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    close = None
    try: close = _job_limits(p, PY_MEM_MB)
    except Exception as e: log(f"run_python: job limits not applied ({e})")
    t0 = time.time()
    try:
        out, err = p.communicate(code.encode("utf-8"), timeout=PY_TIMEOUT); timed_out = False
    except subprocess.TimeoutExpired:
        p.kill(); out, err = p.communicate(); timed_out = True
    finally:
        if close: close()
    out = out.decode("utf-8", "replace"); err = err.decode("utf-8", "replace")
    err = re.sub(r'  File "<string>", line \d+, in <module>\n', "", err)
    err = re.sub(r'  File "[^"]*mochi_sandbox\.py", line \d+, in <module>\n', "", err)
    text = out + (("\n" if out else "") + "STDERR:\n" + err if err.strip() else "")
    if timed_out: text += f"\n[stopped: {PY_TIMEOUT} s limit]"
    elif p.returncode not in (0, None) and not err.strip(): text += f"\n[exit code {p.returncode}{' - probably over the ' + str(PY_MEM_MB) + ' MB memory limit' if p.returncode in (1816, 3221225495) else ''}]"
    images, made = [], []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if not d.startswith(".mochi")]
        for f in fn:
            fp = os.path.join(dp, f); m = os.path.getmtime(fp)
            if before.get(fp) != m and m >= t0 - 1:
                made.append(_rel(root, fp)); ext = os.path.splitext(f)[1].lower()
                if ext in IMG_EXT and len(images) < 4 and os.path.getsize(fp) < 3_000_000:
                    with open(fp, "rb") as fh: images.append(f"data:{IMG_EXT[ext]};base64," + base64.b64encode(fh.read()).decode())
    if made: text += ("\n" if text else "") + "[files written: " + ", ".join(made[:20]) + "]" + (" (images are shown to the user)" if images else "")
    return (text.strip() or "(no output - use print() to show results)"), images

# ============================================================== web: safe fetching (no private / local addresses)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36 Mochi/1.0"
def _public_addr(host, port):
    try: infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror: raise ToolError(f"can't find the website '{host}'")
    addrs = []
    for fam, _, _, _, sa in infos:
        ip = ipaddress.ip_address(sa[0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped: ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast: raise ToolError(f"'{host}' points to a private or local address - blocked for safety")
        addrs.append(str(ip))
    if not addrs: raise ToolError(f"can't find the website '{host}'")
    return addrs[0]
_SSL_CTX = None
def _ssl_ctx():
    global _SSL_CTX
    if _SSL_CTX is None:
        ctx = ssl.create_default_context()
        ca = os.path.join(os.environ.get("MOCHI_SEARXNG", r"C:\Dev\Tools\searxng"), "venv", "Lib", "site-packages", "certifi", "cacert.pem")
        if os.path.isfile(ca):
            try: ctx.load_verify_locations(cafile=ca)
            except Exception: pass
        _SSL_CTX = ctx
    return _SSL_CTX

class _HTTP(http.client.HTTPConnection):
    def __init__(self, host, port, addr, timeout): super().__init__(host, port, timeout=timeout); self._addr = addr
    def connect(self): self.sock = socket.create_connection((self._addr, self.port), self.timeout)
class _HTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, addr, timeout): super().__init__(host, port, timeout=timeout, context=_ssl_ctx()); self._addr = addr
    def connect(self):
        s = socket.create_connection((self._addr, self.port), self.timeout)
        self.sock = self._context.wrap_socket(s, server_hostname=self.host)
def safe_get(url, accept="text/html,application/xhtml+xml,application/json;q=0.9,text/plain;q=0.8,*/*;q=0.5", max_bytes=3_000_000, timeout=15):
    """GET over http(s) to public internet addresses only (each redirect re-checked, DNS answer pinned). -> (status, ctype, bytes, final_url)"""
    for _ in range(6):
        u = urlsplit(url)
        if u.scheme not in ("http", "https"): raise ToolError("only http:// and https:// links can be opened")
        if u.username or u.password: raise ToolError("links with a user name / password are not allowed")
        host = u.hostname
        if not host: raise ToolError("that is not a valid link")
        port = u.port or (443 if u.scheme == "https" else 80)
        if port not in (80, 443, 8080, 8443): raise ToolError("only standard web ports are allowed")
        addr = _public_addr(host, port)
        c = (_HTTPS if u.scheme == "https" else _HTTP)(host, port, addr, timeout)
        try:
            c.request("GET", (u.path or "/") + ("?" + u.query if u.query else ""), headers={"User-Agent": UA, "Accept": accept,
                      "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"})
            r = c.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                url = urljoin(url, r.getheader("Location")); continue
            data = r.read(max_bytes + 1)
            enc = (r.getheader("Content-Encoding") or "").lower()
            if enc == "gzip": data = gzip.decompress(data)
            elif enc == "deflate": data = zlib.decompress(data, -zlib.MAX_WBITS) if not data.startswith(b"x") else zlib.decompress(data)
            return r.status, r.getheader("Content-Type") or "", data[:max_bytes * 3], url
        except (socket.timeout, TimeoutError): raise ToolError("the website took too long to answer")
        except ssl.SSLError as e: raise ToolError(f"secure connection failed: {e.reason or e}")
        except (OSError, http.client.HTTPException) as e: raise ToolError(f"couldn't load the page: {e}")
        finally: c.close()
    raise ToolError("too many redirects")
def get_json(url, timeout=12):
    st, ct, data, _ = safe_get(url, accept="application/json", timeout=timeout)
    if st != 200: raise ToolError(f"the service answered HTTP {st}")
    try: return json.loads(data.decode("utf-8", "replace"))
    except ValueError: raise ToolError("the service sent an unreadable answer")

class _Text(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "iframe", "template", "button", "select", "canvas", "dialog"}
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "blockquote", "pre", "table", "ul", "ol", "dd", "dt", "figcaption", "main", "header", "hr"}
    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.skip = 0; self.title = ""; self.in_title = False; self.desc = ""
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1; return
        if tag == "title": self.in_title = True
        elif tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description") and not self.desc: self.desc = (a.get("content") or "")[:400]
        elif re.fullmatch(r"h[1-6]", tag): self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li": self.out.append("\n• ")
        elif tag in self.BLOCK: self.out.append("\n")
    def handle_endtag(self, tag):
        if tag in self.SKIP: self.skip = max(0, self.skip - 1); return
        if tag == "title": self.in_title = False
        elif tag in self.BLOCK or re.fullmatch(r"h[1-6]", tag): self.out.append("\n")
    def handle_data(self, d):
        if self.in_title: self.title += d
        elif not self.skip: self.out.append(d)
    def text(self):
        lines = [re.sub(r"[ \t\r\f\v\u00a0]+", " ", l).strip() for l in "".join(self.out).split("\n")]
        out, blank = [], 0
        for l in lines:
            if not l or l in ("•", "#"): blank += 1; continue
            if blank and out: out.append("")
            out.append(l); blank = 0
        return "\n".join(out)

@tool("fetch_url", "Open web page", "Open a web page (or a JSON / text URL) and return its readable text. Use after web_search to read a result in full.",
      {"url": {"type": "string"}, "max_chars": {"type": "integer", "description": "Optional cap on returned characters (default 6000)."}},
      ["url"], risk="network", group="Web", max_chars=12000)
def t_fetch(args, user, ctx):
    url = _s(args, "url", limit=2000)
    if not re.match(r"^https?://", url, re.I): url = "https://" + url
    st, ct, data, final = safe_get(url)
    if st >= 400: raise ToolError(f"the page answered HTTP {st}")
    cap = _i(args, "max_chars", 6000, 500, 12000)
    m = re.search(r"charset=([\w-]+)", ct, re.I) or re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', data[:4000], re.I)
    cs = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try: txt = data.decode(cs, "replace")
    except LookupError: txt = data.decode("utf-8", "replace")
    ctl = ct.lower()
    if "html" in ctl or (not ctl and "<html" in txt[:2000].lower()):
        p = _Text(); p.feed(txt); body = p.text(); title = re.sub(r"\s+", " ", p.title).strip()
        head = f"Title: {title or '(none)'}\nURL: {final}\n" + (f"Description: {p.desc}\n" if p.desc else "")
    elif "json" in ctl or "text" in ctl or "xml" in ctl:
        body, head = txt, f"URL: {final}\nType: {ct.split(';')[0]}\n"
    else: raise ToolError(f"this link is a {ct.split(';')[0] or 'binary file'}, not a web page")
    if len(body) > cap: body = body[:cap].rstrip() + f"\n…[page cut at {cap} characters of {len(body)}]"
    return head + "\n" + (body or "(the page has no readable text - it may need JavaScript)")

# ---------------- web search through Mochi's own SearXNG (127.0.0.1 only, runs only while Mochi runs)
SX_DIR = os.environ.get("MOCHI_SEARXNG", r"C:\Dev\Tools\searxng")
SX_PY, SX_RUN = os.path.join(SX_DIR, "venv", "Scripts", "python.exe"), os.path.join(SX_DIR, "run_searxng.py")
SX_PORT = int(os.environ.get("MOCHI_SEARXNG_PORT", "8888"))
SX_IDLE = 30 * 60
SX = {"proc": None, "state": "off", "error": "", "last": 0, "started": 0, "lock": threading.Lock()}
def sx_installed(): return os.path.isfile(SX_PY) and os.path.isfile(SX_RUN)
def _sx_get(path, timeout=20):
    c = http.client.HTTPConnection("127.0.0.1", SX_PORT, timeout=timeout)
    try: c.request("GET", path, headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"}); r = c.getresponse(); return r.status, r.read()
    finally: c.close()
def _sx_alive():
    try: return _sx_get("/healthz", 2)[0] == 200
    except OSError: return False
def sx_view():
    p = SX["proc"]
    if SX["state"] == "on" and p and p.poll() is not None: SX.update(state="error", error=f"SearXNG stopped (exit {p.returncode}); see logs\\searxng.log", proc=None)
    return {"installed": sx_installed(), "state": SX["state"] if sx_installed() else "missing", "error": SX["error"], "port": SX_PORT,
            "since": SX["started"], "idle_stop_min": SX_IDLE // 60}
def sx_start(wait=True):
    if not sx_installed(): raise ToolError(f"web search isn't installed (expected SearXNG in {SX_DIR})")
    with SX["lock"]:
        p = SX["proc"]
        if not (p and p.poll() is None):
            if _sx_alive(): SX.update(state="on", error=""); SX["last"] = time.time(); return  # one we started earlier and lost track of
            logf = open(os.path.join(HOOKS.get("logs_dir") or SX_DIR, "searxng.log"), "ab")
            logf.write(time.strftime("\n--- %Y-%m-%d %H:%M:%S start\n").encode())
            p = subprocess.Popen([SX_PY, SX_RUN], cwd=SX_DIR, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 env={**os.environ, "MOCHI_SEARXNG_PORT": str(SX_PORT)}, creationflags=0x08000000 if os.name == "nt" else 0)
            logf.close()
            if HOOKS.get("kill_with_us"): HOOKS["kill_with_us"](p)  # SearXNG dies with Mochi, even if Mochi is killed
            pid_file = HOOKS.get("sx_pid_file")
            if pid_file:
                with open(pid_file, "w") as f: f.write(str(p.pid))
            SX.update(proc=p, state="starting", error="", started=time.time()); log(f"web search: starting SearXNG (pid {p.pid})")
        SX["last"] = time.time()
    if not wait: return
    t0 = time.time()
    while time.time() - t0 < 40:
        if _sx_alive(): SX["state"] = "on"; return
        if SX["proc"] and SX["proc"].poll() is not None:
            SX.update(state="error", error=f"SearXNG exited ({SX['proc'].returncode}); see logs\\searxng.log", proc=None); raise ToolError(SX["error"])
        time.sleep(0.4)
    raise ToolError("web search is still starting - try again in a few seconds")
def sx_warm():
    if sx_installed() and SX["state"] not in ("on", "starting"):
        threading.Thread(target=lambda: _quiet(sx_start), daemon=True).start()
def _quiet(fn):
    try: fn()
    except Exception as e: log(f"web search: {e}")
def sx_stop():
    with SX["lock"]:
        p = SX["proc"]; SX.update(proc=None, state="off", error="")
        if p and p.poll() is None:
            p.terminate()
            try: p.wait(5)
            except subprocess.TimeoutExpired: p.kill()
            log("web search: SearXNG stopped")
        pid_file = HOOKS.get("sx_pid_file")
        if pid_file:
            try: os.remove(pid_file)
            except OSError: pass
def _sx_reaper():
    while True:
        time.sleep(60)
        if SX["proc"] and time.time() - SX["last"] > SX_IDLE: log("web search: idle, stopping SearXNG"); sx_stop()
threading.Thread(target=_sx_reaper, daemon=True).start()

@tool("web_search", "Web search", "Search the web (private SearXNG: Google, DuckDuckGo, Bing, Brave, Wikipedia…). Returns titles, links and snippets; "
      "open a result with fetch_url when you need details. Use it for current events, prices, docs or anything after your training data.",
      {"query": {"type": "string"}, "category": {"type": "string", "enum": ["general", "news", "science", "it"], "description": "Default general."},
       "time_range": {"type": "string", "enum": ["", "day", "week", "month", "year"], "description": "Only recent results (optional)."},
       "count": {"type": "integer", "description": "Results to return, 1-10 (default 6)."}},
      ["query"], risk="network", group="Web", max_chars=5000, available=lambda: "" if sx_installed() else "SearXNG isn't installed")
def t_search(args, user, ctx):
    q = _s(args, "query", limit=300)
    if not q: raise ToolError("no query")
    sx_start()
    SX["last"] = time.time()
    params = {"q": q, "format": "json", "categories": _s(args, "category") if _s(args, "category") in ("general", "news", "science", "it") else "general",
              "safesearch": 0, "language": "auto"}
    if _s(args, "time_range") in ("day", "week", "month", "year"): params["time_range"] = _s(args, "time_range")
    try: st, raw = _sx_get("/search?" + urlencode(params), 25)
    except OSError as e: raise ToolError(f"web search failed: {e}")
    if st != 200: raise ToolError(f"web search answered HTTP {st}")
    d = json.loads(raw.decode("utf-8", "replace"))
    n = _i(args, "count", 6, 1, 10); out = []
    if d.get("answers"): out.append("Quick answer: " + "; ".join(str(a.get("answer", a) if isinstance(a, dict) else a)[:300] for a in d["answers"][:2]))
    for b in (d.get("infoboxes") or [])[:1]:
        if b.get("content"): out.append(f"Infobox ({b.get('infobox', '')}): {b['content'][:400]}")
    seen = set(); i = 0
    for r in d.get("results") or []:
        url = r.get("url") or ""
        if not url or url in seen: continue
        seen.add(url); i += 1
        date = (r.get("publishedDate") or "")[:10]
        snip = re.sub(r"\s+", " ", r.get("content") or "").strip()[:280]
        out.append(f"{i}. {r.get('title') or url}{' (' + date + ')' if date else ''}\n   {url}\n   {snip}")
        if i >= n: break
    if i == 0:
        bad = ", ".join(e[0] for e in (d.get("unresponsive_engines") or [])[:5])
        return f"No results for '{q}'." + (f" (search engines not answering: {bad})" if bad else "")
    return f"Web results for '{q}':\n" + "\n".join(out)

# ---------------- free public APIs (no keys)
WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
       55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
       67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
       82: "violent showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}
@tool("get_weather", "Weather", "Current weather and a daily forecast for a place (Open-Meteo). Temperatures in °C, wind in km/h.",
      {"location": {"type": "string", "description": "City or place, e.g. 'Pune' or 'Paris, France'."},
       "days": {"type": "integer", "description": "Forecast days 1-7 (default 3)."}}, ["location"], risk="network", group="Web")
def t_weather(args, user, ctx):
    loc = _s(args, "location", limit=120)
    if not loc: raise ToolError("no location")
    name = loc.split(",")[0].strip()
    g = get_json("https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": name, "count": 5, "language": "en", "format": "json"}))
    res = g.get("results") or []
    if not res: raise ToolError(f"couldn't find a place called '{loc}'")
    hint = loc.split(",", 1)[1].strip().lower() if "," in loc else ""
    pl = next((r for r in res if hint and hint in (str(r.get("country", "")) + " " + str(r.get("admin1", "")) + " " + str(r.get("country_code", ""))).lower()), res[0])
    days = _i(args, "days", 3, 1, 7)
    f = get_json("https://api.open-meteo.com/v1/forecast?" + urlencode({"latitude": pl["latitude"], "longitude": pl["longitude"], "timezone": "auto",
                 "forecast_days": days, "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
                 "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,sunrise,sunset,uv_index_max"}))
    c = f.get("current") or {}; dl = f.get("daily") or {}
    where = ", ".join(x for x in (pl.get("name"), pl.get("admin1"), pl.get("country")) if x)
    lines = [f"Weather for {where} (local time {str(c.get('time', '')).replace('T', ' ')}, {f.get('timezone', '')}):",
             f"Now: {c.get('temperature_2m')}°C (feels {c.get('apparent_temperature')}°C), {WMO.get(c.get('weather_code'), 'code ' + str(c.get('weather_code')))}, "
             f"humidity {c.get('relative_humidity_2m')}%, wind {c.get('wind_speed_10m')} km/h, precipitation {c.get('precipitation')} mm"]
    for i, day in enumerate(dl.get("time") or []):
        g_ = lambda k: (dl.get(k) or [None] * 10)[i]
        lines.append(f"{day}: {g_('temperature_2m_min')}–{g_('temperature_2m_max')}°C, {WMO.get(g_('weather_code'), '?')}, rain chance {g_('precipitation_probability_max')}% "
                     f"({g_('precipitation_sum')} mm), UV {g_('uv_index_max')}, sunrise {str(g_('sunrise'))[-5:]}, sunset {str(g_('sunset'))[-5:]}")
    return "\n".join(lines)

@tool("wikipedia", "Wikipedia", "Look up a topic on Wikipedia and get the summary of the best-matching article.",
      {"query": {"type": "string"}, "lang": {"type": "string", "description": "Wikipedia language code, default 'en'."}}, ["query"], risk="network", group="Web")
def t_wiki(args, user, ctx):
    q = _s(args, "query", limit=200); lang = _s(args, "lang", "en", 10).lower() or "en"
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z]+)?", lang): lang = "en"
    if not q: raise ToolError("no query")
    s = get_json(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page?" + urlencode({"q": q, "limit": 3}))
    pages = s.get("pages") or []
    if not pages: return f"No Wikipedia article found for '{q}'."
    p = pages[0]
    d = get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + quote(p["key"], safe=""))
    others = ", ".join(x.get("title", "") for x in pages[1:])
    return (f"{d.get('title')}{' - ' + d['description'] if d.get('description') else ''}\n{(d.get('content_urls') or {}).get('desktop', {}).get('page', '')}\n\n"
            f"{d.get('extract') or '(no summary)'}" + (f"\n\nOther matches: {others}" if others else ""))

@tool("currency_convert", "Currency converter", "Convert money between currencies at today's reference rates (European Central Bank, via Frankfurter). "
      "Use ISO codes like USD, EUR, INR, GBP, JPY.",
      {"amount": {"type": "number"}, "from_currency": {"type": "string"}, "to_currency": {"type": "string"}}, ["amount", "from_currency", "to_currency"],
      risk="network", group="Web")
def t_fx(args, user, ctx):
    try: amt = float(args.get("amount"))
    except (TypeError, ValueError): raise ToolError("amount must be a number")
    a, b = _s(args, "from_currency", limit=5).upper(), _s(args, "to_currency", limit=5).upper()
    if not re.fullmatch(r"[A-Z]{3}", a) or not re.fullmatch(r"[A-Z]{3}", b): raise ToolError("use 3-letter currency codes like USD or INR")
    if a == b: return f"{amt:g} {a} = {amt:g} {b}"
    try: d = get_json("https://api.frankfurter.app/latest?" + urlencode({"amount": amt, "from": a, "to": b}))
    except ToolError as e: raise ToolError(f"{e} (Frankfurter supports about 30 major currencies)")
    r = (d.get("rates") or {}).get(b)
    if r is None: raise ToolError(f"no rate for {a} → {b}")
    return f"{amt:,.2f} {a} = {r:,.2f} {b} (ECB reference rate for {d.get('date')}; 1 {a} = {r / amt if amt else 0:.4f} {b})"
