"""Sandboxed runner for Mochi's run_python tool.

Executed with `python.exe -I -B mochi_sandbox.py`. Reads user code from stdin,
adds Mochi's optional library site-packages before locking down the interpreter
with an audit hook, then executes the code inside the user's Mochi files folder.
"""
import ctypes, os, site, sys

_src = sys.stdin.read()
sys.stdin = open(os.devnull)

_site = os.environ.get("MOCHI_SITE_PACKAGES", "")
if _site and os.path.isdir(_site):
    site.addsitedir(_site)

_n = lambda p: os.path.normcase(os.path.realpath(os.fsdecode(p)))
_ROOT = _n(os.getcwd())
_RO = [_n(p) for p in {
    sys.prefix, sys.base_prefix, sys.exec_prefix,
    os.path.dirname(_site) if _site else "",
    _site,
    os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts"),
} if p]
_W = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

def _in(p, roots):
    try: p = _n(p)
    except Exception: return False
    return any(p == r or p.startswith(r + os.sep) for r in roots)

_NO = {
    "subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile",
    "os.kill", "os.fork", "_winapi.CreateProcess",
    "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname",
    "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg",
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.call_function",
    "ctypes.addressof", "ctypes.string_at", "ctypes.wstring_at", "ctypes.set_errno",
    "ctypes.get_errno", "ctypes.PyObj_FromPtr",
}
_WINREG_RO = {
    "winreg.ConnectRegistry", "winreg.OpenKey", "winreg.OpenKey/result",
    "winreg.QueryValue", "winreg.QueryInfoKey", "winreg.EnumKey", "winreg.EnumValue",
}
_P1 = {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate", "os.utime",
       "shutil.rmtree", "os.chdir", "os.link", "os.symlink"}
_P2 = {"os.rename", "shutil.copyfile", "shutil.copymode", "shutil.copystat",
       "shutil.move", "shutil.copytree"}
_PL = {"os.listdir", "os.scandir", "glob.glob", "os.walk"}

def _deny(what):
    raise PermissionError("Mochi sandbox: " + what + " is not allowed (only the Mochi files folder, no programs, no network)")

def _hook(ev, a):
    if ev == "open":
        p = a[0] if a else None
        if p is None or isinstance(p, int): return
        mode = a[1] if len(a) > 1 else None
        fl = a[2] if len(a) > 2 and isinstance(a[2], int) else 0
        w = bool(fl & _W) or (isinstance(mode, str) and any(c in mode for c in "wax+"))
        if _in(p, [_ROOT]) or (not w and _in(p, _RO)): return
        _deny(("writing " if w else "reading ") + os.fsdecode(p))
    if ev in _NO or (ev.startswith("winreg.") and ev not in _WINREG_RO) or (ev.startswith("ctypes.") and ev not in ("ctypes.cdata", "ctypes.cdata/buffer")):
        _deny(ev)
    if ev in _P1 and a and a[0] is not None and not isinstance(a[0], int) and not _in(a[0], [_ROOT]):
        _deny(ev + " outside the files folder")
    if ev in _P2 and any(x is not None and not isinstance(x, int) and not _in(x, [_ROOT]) for x in a[:2]):
        _deny(ev + " outside the files folder")
    if ev in _PL and a and a[0] is not None and not isinstance(a[0], int) and not _in(a[0], [_ROOT] + _RO):
        _deny("listing " + os.fsdecode(a[0]))

sys.addaudithook(_hook)
del sys.modules["os"].system
__builtins__.__dict__.pop("breakpoint", None)

_g = {"__name__": "__main__", "__builtins__": __builtins__}
exec(compile(_src, "<mochi>", "exec"), _g)
