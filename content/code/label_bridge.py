#!/usr/bin/env python3
"""
label_bridge.py — tiny localhost print bridge for menuview's label maker.

The label maker runs entirely in the browser (JupyterLite/Pyodide on GitHub
Pages), where there is no way to reach a printer without going through the
browser's print dialog. This script runs on the machine that actually owns
the printer and exposes three endpoints the widget can call:

    GET  /health          -> {"ok": true, "platform": ...}   (availability probe)
    GET  /printers        -> {"printers": [...], "default": "..."}
    POST /print           -> spools the posted PNG to a printer queue

Nothing here knows anything about labels, TSPL, or thermal printers. It hands
a PNG to the operating system's own print queue, so all the printer settings
(label size, darkness, speed, media type) live where they normally live — in
the printer's system preferences — and are configured once through the normal
OS printer UI. That is the whole point: "saved settings" are the queue's.

Sizing
    Canvas-generated PNGs carry no physical-resolution metadata, so a print
    system has no way to know that an 812x406 image is meant to be 4in x 2in
    rather than 11in x 5.6in at 72dpi. Before spooling, _stamp_png_dpi()
    injects a pHYs chunk declaring the real DPI, which makes the image
    physically self-describing and lets `print-scaling=none` do a true 1:1
    dot mapping with no resampling anywhere in the chain.

Usage
    python3 label_bridge.py                      # localhost only
    python3 label_bridge.py --host 0.0.0.0       # also reachable from iPad
    python3 label_bridge.py --token s3cret       # require ?token= / X-Token
    python3 label_bridge.py --printer RW403B     # pin a default queue

No third-party dependencies — standard library only, so it runs under any
Python 3.8+ with nothing to install.
"""

import argparse
import binascii
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

IS_WINDOWS = platform.system() == "Windows"
IS_PYODIDE = sys.platform == "emscripten"
MAX_BODY = 32 * 1024 * 1024   # 32 MB ceiling; a 4x6 @ 203dpi PNG is ~50 KB

# Fallback for non-preflight responses only; the preflight echoes whatever
# the browser actually asked for (see Handler._cors).
ALLOWED_HEADERS = ("content-type, x-copies, x-printer, x-dpi, x-token, "
                   "x-width-in, x-height-in")

# Set from argv in main(); read by the handler.
CONFIG = {"printer": None, "token": None, "sumatra": None, "verbose": False}


# ── PNG physical-resolution stamping ────────────────────────────────────────

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _iter_png_chunks(data):
    """Yield (type_bytes, data_bytes) for each chunk in a PNG."""
    pos = len(PNG_SIG)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        start = pos + 8
        yield ctype, data[start:start + length]
        pos = start + length + 4          # + 4 for the trailing CRC


def _png_chunk(ctype, payload):
    """Build a complete PNG chunk (length + type + data + CRC32)."""
    return (struct.pack(">I", len(payload)) + ctype + payload +
            struct.pack(">I", binascii.crc32(ctype + payload) & 0xFFFFFFFF))


def _stamp_png_dpi(data, dpi):
    """Return `data` with a pHYs chunk declaring `dpi`, replacing any existing
    one. Returns the input unchanged if it isn't a PNG or dpi is unusable."""
    if not data.startswith(PNG_SIG) or not dpi or dpi <= 0:
        return data
    ppm = int(round(float(dpi) / 0.0254))          # pixels per metre
    phys = _png_chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))   # unit 1 = metre

    out = bytearray(PNG_SIG)
    inserted = False
    try:
        for ctype, payload in _iter_png_chunks(data):
            if ctype == b"pHYs":
                continue                            # drop any existing one
            out += _png_chunk(ctype, payload)
            if ctype == b"IHDR":                    # pHYs must precede IDAT
                out += phys
                inserted = True
    except Exception:
        return data                                 # malformed — spool as-is
    return bytes(out) if inserted else data


# ── printer discovery ───────────────────────────────────────────────────────

def list_printers():
    """Return (names, default_name). Best-effort; never raises."""
    if IS_WINDOWS:
        return _list_printers_windows()
    return _list_printers_cups()


def _list_printers_cups():
    names, default = [], None
    try:
        out = subprocess.run(["lpstat", "-a"], capture_output=True, text=True,
                             timeout=10).stdout
        names = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
    except Exception:
        pass
    try:
        out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True,
                             timeout=10).stdout
        m = re.search(r":\s*(\S+)", out)
        if m:
            default = m.group(1)
    except Exception:
        pass
    return names, default


def _list_printers_windows():
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
          "Get-CimInstance Win32_Printer | "
          "Select-Object Name,Default | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20).stdout
        parsed = json.loads(out or "[]")
        if isinstance(parsed, dict):
            parsed = [parsed]
        names = [p["Name"] for p in parsed if p.get("Name")]
        default = next((p["Name"] for p in parsed if p.get("Default")), None)
        return names, default
    except Exception:
        return [], None


# ── spooling ────────────────────────────────────────────────────────────────

def spool(png_bytes, printer, copies, dpi, width_in=None, height_in=None):
    """Send `png_bytes` to `printer`. Returns (ok, message)."""
    png_bytes = _stamp_png_dpi(png_bytes, dpi)
    fd, path = tempfile.mkstemp(suffix=".png", prefix="menuview_label_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(png_bytes)
        if IS_WINDOWS:
            return _spool_windows(path, printer, copies)
        return _spool_cups(path, printer, copies, width_in, height_in)
    finally:
        # SumatraPDF returns before it has finished reading the file, so the
        # Windows path deletes on the next request instead (see _spool_windows).
        if not IS_WINDOWS:
            try:
                os.unlink(path)
            except OSError:
                pass


def _spool_cups(path, printer, copies, width_in, height_in):
    cmd = ["lp"]
    if printer:
        cmd += ["-d", printer]
    cmd += ["-n", str(max(1, int(copies)))]
    # print-scaling=none keeps the 1:1 dot mapping the pHYs chunk just
    # declared; without it CUPS "helpfully" fits the image to the media.
    #
    # That alone is not enough: it says "don't resize the image to fit the
    # page" but says nothing about what the page *is*. Left unset, CUPS uses
    # the queue's configured default media (often Letter, or whatever media
    # size was set when the queue was added) and places the label-sized
    # image at one corner of it. On a continuous-roll/label printer this is
    # the classic cause of a "successful" job that comes out blank or
    # mis-cut: the image is real, but it isn't positioned on the physical
    # label. Declaring a custom media size matching the actual label
    # dimensions makes the CUPS page *be* the label, so native-size content
    # lands exactly on it.
    if width_in and height_in:
        cmd += ["-o", f"media=Custom.{width_in}x{height_in}in"]
    cmd += ["-o", "print-scaling=none", "-o", "fit-to-page=false", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, "`lp` not found — is CUPS installed?"
    except subprocess.TimeoutExpired:
        return False, "lp timed out"
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "lp failed").strip()
    return True, (r.stdout or "queued").strip()


_WIN_TEMPFILES = []


def _spool_windows(path, printer, copies):
    exe = CONFIG.get("sumatra") or shutil.which("SumatraPDF.exe")
    if not exe:
        return False, ("SumatraPDF not found. Install it and pass "
                       "--sumatra <path to SumatraPDF.exe>.")
    ok, msg = True, "queued"
    for _ in range(max(1, int(copies))):
        cmd = [exe, "-print-to", printer or "", "-print-settings", "noscale",
               "-silent", "-exit-when-done", path]
        if not printer:
            cmd = [exe, "-print-to-default", "-print-settings", "noscale",
                   "-silent", "-exit-when-done", path]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                ok, msg = False, (r.stderr or "SumatraPDF failed").strip()
        except Exception as e:
            ok, msg = False, str(e)
    # Reap the previous request's temp file now that Sumatra has let go of it.
    while _WIN_TEMPFILES:
        try:
            os.unlink(_WIN_TEMPFILES.pop())
        except OSError:
            pass
    _WIN_TEMPFILES.append(path)
    return ok, msg


# ── HTTP ────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "menuview-label-bridge/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if CONFIG.get("verbose"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers ------------------------------------------------------------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        # Echo whatever the preflight asked for, rather than maintaining a
        # static allow-list. A static list breaks silently the moment the
        # widget starts sending a new x-* header: the browser rejects the
        # preflight client-side, the fetch fails as an opaque network error
        # ("bridge unreachable"), and *nothing appears in the bridge's log*
        # because the POST is never sent. Echoing keeps the two sides from
        # drifting apart. Safe here: this service only ever spools a PNG,
        # holds no credentials, and sends no cookies.
        want = self.headers.get("Access-Control-Request-Headers")
        self.send_header("Access-Control-Allow-Headers", want or ALLOWED_HEADERS)
        # Chrome's Private Network Access check: an https:// page reaching
        # 127.0.0.1 is blocked outright unless the preflight says this.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def _reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        want = CONFIG.get("token")
        if not want:
            return True
        got = self.headers.get("x-token")
        if not got:
            got = (parse_qs(urlparse(self.path).query).get("token") or [None])[0]
        return got == want

    # -- verbs --------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        route = urlparse(self.path).path.rstrip("/") or "/"
        if not self._authorized():
            return self._reply(403, {"ok": False, "error": "bad token"})
        if route == "/health":
            return self._reply(200, {"ok": True, "platform": platform.system()})
        if route == "/printers":
            names, default = list_printers()
            return self._reply(200, {"ok": True, "printers": names,
                                     "default": CONFIG.get("printer") or default})
        return self._reply(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        route = urlparse(self.path).path.rstrip("/") or "/"
        if not self._authorized():
            return self._reply(403, {"ok": False, "error": "bad token"})
        if route != "/print":
            return self._reply(404, {"ok": False, "error": "not found"})

        try:
            length = int(self.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return self._reply(400, {"ok": False, "error": "empty body"})
        if length > MAX_BODY:
            return self._reply(413, {"ok": False, "error": "body too large"})

        data = self.rfile.read(length)
        if not data.startswith(PNG_SIG):
            return self._reply(400, {"ok": False, "error": "body is not a PNG"})

        printer = self.headers.get("x-printer") or CONFIG.get("printer")
        try:
            copies = max(1, min(99, int(self.headers.get("x-copies") or 1)))
        except ValueError:
            copies = 1
        try:
            dpi = int(self.headers.get("x-dpi") or 0)
        except ValueError:
            dpi = 0
        try:
            width_in = float(self.headers.get("x-width-in") or 0) or None
            height_in = float(self.headers.get("x-height-in") or 0) or None
        except ValueError:
            width_in = height_in = None

        ok, msg = spool(data, printer, copies, dpi, width_in, height_in)
        return self._reply(200 if ok else 500,
                           {"ok": ok, "message": msg, "printer": printer,
                            "copies": copies})


def _in_ipython():
    """True when imported/executed inside an IPython or Jupyter kernel."""
    try:
        from IPython import get_ipython
        return get_ipython() is not None
    except Exception:
        return False


def is_running(host="127.0.0.1", port=8765, timeout=0.6):
    """True if a bridge is already answering on host:port."""
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://{host}:{port}/health", timeout=timeout) as r:
            return json.loads(r.read()).get("ok") is True
    except Exception:
        return False


def ensure_running(host="127.0.0.1", port=8765, printer=None, token=None,
                   python=None, log=None, quiet=True):
    """Start the bridge if it isn't already up. Idempotent and non-blocking.

    This is what the label maker calls on construction, so opening a label
    in JupyterLab Desktop just works with no terminal step. Returns True if
    a bridge is (now) reachable.

    Do NOT use `%run label_bridge.py` -- that runs serve_forever() inside
    the kernel and blocks it permanently. This spawns a separate, detached
    OS process and returns immediately.

    Under JupyterLite/Pyodide the kernel is a WebAssembly sandbox with no
    subprocess and no sockets, so nothing can be started from the page at
    all; use `install_autostart()` once on the host machine instead, which
    makes the OS start the bridge at login.
    """
    if IS_PYODIDE:
        return False
    if is_running(host, port):
        return True

    log = log or os.path.join(_state_dir(), "label_bridge.log")
    cmd = [python or sys.executable, os.path.abspath(__file__),
           "--host", str(host), "--port", str(port)]
    if printer:
        cmd += ["--printer", printer]
    if token:
        cmd += ["--token", token]

    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        logf = open(log, "ab", buffering=0)
        kwargs = {"stdout": logf, "stderr": logf, "stdin": subprocess.DEVNULL}
        if IS_WINDOWS:
            kwargs["creationflags"] = 0x00000008 | 0x08000000  # DETACHED|NO_WINDOW
        else:
            # New session so the bridge outlives a kernel restart rather than
            # being killed along with the process group that spawned it.
            kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **kwargs)
    except Exception as e:
        if not quiet:
            print(f"could not start bridge: {e}", file=sys.stderr)
        return False

    # Poll briefly rather than sleeping a fixed amount: binding a loopback
    # socket is near-instant, so this normally returns on the first check.
    import time as _t
    for _ in range(20):
        if is_running(host, port, timeout=0.3):
            if not quiet:
                print(f"bridge started on http://{host}:{port}")
            return True
        _t.sleep(0.1)
    return False


# ── autostart: make the OS keep the bridge running ──────────────────────────
# Needed for JupyterLite, where the page can never start a local process.
# Installed once; afterwards the bridge is simply always up, across reboots.

SERVICE_ID = "com.menuview.labelbridge"


def _state_dir():
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "menuview")
    return os.path.join(os.path.expanduser("~"), ".menuview")


def _svc_paths():
    home = os.path.expanduser("~")
    if platform.system() == "Darwin":
        return os.path.join(home, "Library", "LaunchAgents", SERVICE_ID + ".plist")
    if IS_WINDOWS:
        return os.path.join(os.environ.get("APPDATA", home), "Microsoft", "Windows",
                            "Start Menu", "Programs", "Startup", "menuview-label-bridge.vbs")
    return os.path.join(home, ".config", "systemd", "user",
                        "menuview-label-bridge.service")


def _svc_args(host, port, printer, token):
    args = [sys.executable, os.path.abspath(__file__),
            "--host", str(host), "--port", str(port)]
    if printer:
        args += ["--printer", printer]
    if token:
        args += ["--token", token]
    return args


def install_autostart(host="127.0.0.1", port=8765, printer=None, token=None):
    """Register the bridge to start at login. One-time; survives reboots."""
    if IS_PYODIDE:
        raise RuntimeError("Run this on the host machine, not in JupyterLite.")
    path = _svc_paths()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(_state_dir(), exist_ok=True)
    args = _svc_args(host, port, printer, token)
    log = os.path.join(_state_dir(), "label_bridge.log")
    system = platform.system()

    if system == "Darwin":
        items = "".join(f"      <string>{a}</string>\n" for a in args)
        plist = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n  <dict>\n'
            f'    <key>Label</key><string>{SERVICE_ID}</string>\n'
            f'    <key>ProgramArguments</key>\n    <array>\n{items}    </array>\n'
            '    <key>RunAtLoad</key><true/>\n'
            '    <key>KeepAlive</key><true/>\n'
            f'    <key>StandardOutPath</key><string>{log}</string>\n'
            f'    <key>StandardErrorPath</key><string>{log}</string>\n'
            '  </dict>\n</plist>\n')
        with open(path, "w") as f:
            f.write(plist)
        subprocess.run(["launchctl", "unload", path],
                       capture_output=True, text=True)
        r = subprocess.run(["launchctl", "load", "-w", path],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False, (r.stderr or "launchctl load failed").strip()
        return True, f"installed LaunchAgent: {path}"

    if IS_WINDOWS:
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        quoted = " ".join(f'""{a}""' for a in ([pyw] + args[1:]))
        with open(path, "w") as f:
            f.write('Set s = CreateObject("Wscript.Shell")\n'
                    f's.Run "{quoted}", 0, False\n')
        # launchd/systemd both start the service as part of install; do the
        # same here so Windows doesn't uniquely require a logout first.
        ensure_running(host, port, printer, token)
        return True, f"installed startup script: {path}"

    unit = ("[Unit]\nDescription=menuview label print bridge\n\n"
            "[Service]\nType=simple\n"
            f"ExecStart={' '.join(args)}\n"
            "Restart=always\nRestartSec=3\n\n"
            "[Install]\nWantedBy=default.target\n")
    with open(path, "w") as f:
        f.write(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"],
                   capture_output=True, text=True)
    r = subprocess.run(["systemctl", "--user", "enable", "--now",
                        "menuview-label-bridge"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, (r.stderr or "systemctl failed").strip()
    # Without lingering, a user unit stops when the last session ends.
    subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")],
                   capture_output=True, text=True)
    return True, f"installed systemd user unit: {path}"


def uninstall_autostart():
    path = _svc_paths()
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["launchctl", "unload", "-w", path],
                       capture_output=True, text=True)
    elif not IS_WINDOWS:
        subprocess.run(["systemctl", "--user", "disable", "--now",
                        "menuview-label-bridge"], capture_output=True, text=True)
    try:
        os.unlink(path)
    except OSError:
        pass
    return True, f"removed {path}"


def autostart_status():
    path = _svc_paths()
    return {"installed": os.path.exists(path), "path": path,
            "running": is_running(), "log": os.path.join(_state_dir(),
                                                         "label_bridge.log")}


def main():
    if IS_PYODIDE:
        sys.exit("This bridge needs OS access and cannot run under "
                 "JupyterLite/Pyodide. Run it from a terminal instead.")
    if _in_ipython():
        sys.exit(
            "Refusing to start: this looks like an IPython/Jupyter kernel.\n"
            "serve_forever() would block the kernel permanently.\n"
            "  Nothing to do -- the label maker starts the bridge itself.\n"
            "  To make it permanent:  python3 label_bridge.py install")

    ap = argparse.ArgumentParser(description="menuview label print bridge")
    ap.add_argument("command", nargs="?", default="serve",
                    choices=["serve", "install", "uninstall", "status"],
                    help="serve (default), or manage login-time autostart")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (use 0.0.0.0 to allow iPad/LAN)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--printer", default=None,
                    help="default queue name (else the system default)")
    ap.add_argument("--token", default=None,
                    help="require this token; strongly advised with --host 0.0.0.0")
    ap.add_argument("--sumatra", default=None,
                    help="Windows only: path to SumatraPDF.exe")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    CONFIG.update(printer=args.printer, token=args.token,
                  sumatra=args.sumatra, verbose=args.verbose)

    if args.command == "status":
        st = autostart_status()
        print(f"autostart installed: {st['installed']}  ({st['path']})")
        print(f"bridge running:      {st['running']}")
        print(f"log:                 {st['log']}")
        return
    if args.command == "install":
        ok, msg = install_autostart(args.host, args.port, args.printer, args.token)
        print(("OK: " if ok else "FAILED: ") + msg)
        if ok:
            print("The bridge will now start automatically at login.")
        return sys.exit(0 if ok else 1)
    if args.command == "uninstall":
        ok, msg = uninstall_autostart()
        print(("OK: " if ok else "FAILED: ") + msg)
        return sys.exit(0 if ok else 1)

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.token:
        print("WARNING: bound to a non-loopback address without --token. "
              "Anyone on this network can print to you.", file=sys.stderr)

    names, default = list_printers()
    print(f"menuview label bridge on http://{args.host}:{args.port}")
    print(f"  printers: {', '.join(names) if names else '(none found)'}")
    print(f"  default:  {CONFIG.get('printer') or default or '(system default)'}")

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
