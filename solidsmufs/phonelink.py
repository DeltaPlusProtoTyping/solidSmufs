"""Photos from a phone, over the shop's network, for Ballooning mode.

The window asks for a link (start): a one-time code, good for MINUTES, and the address of a small page a phone on
the same network opens (by the QR code the window shows, or typed). That page takes pictures from the phone's camera
or its photos and sends them here, where they wait in the code's inbox until the window takes them (take) and adds
them to the PDF as any photo is added, so Undo and Save work as usual.

Only that page and its upload are served to the network, on a port of its own (a second server, apart from the
window's, which stays on 127.0.0.1 only): nothing else of the app, no file, no document. Without a live code every
request is turned away. The network server starts with the first code and stops once none is left.
Plain HTTP on the local network: the photos aren't encrypted on the way, so it's for a shop's own network.
"""

import html
import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MINUTES = 15
MOST_BYTES = 25 * 1024 * 1024  # one photo
MOST_PHOTOS = 40  # one code
TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp", "image/gif", "image/bmp", "image/tiff"}


def lan_address():
    """This PC's address on the local network (a private one), or None."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # (no packet is sent: it only picks the way out)
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    for a in found:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.is_private and not ip.is_loopback and not ip.is_link_local:
            return a
    return None


def qr_svg(text):
    """The QR code for text as SVG (segno; None without it: the window shows the address to type)."""
    try:
        import segno
    except ImportError:
        return None
    import io
    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=6, border=4, dark="#000", light="#fff", xmldecl=False, svgns=True)
    return out.getvalue().decode("utf-8")


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Send photos</title>
<style>body{font:17px/1.4 system-ui,sans-serif;margin:0;padding:20px;background:#f4f5f7;color:#111}
h1{font-size:20px;margin:0 0 4px}p{margin:6px 0 16px;color:#444}
label.b{display:block;text-align:center;padding:18px;border-radius:10px;background:#2858cf;color:#fff;font-weight:600;margin:10px 0}
label.b.alt{background:#fff;color:#2858cf;border:2px solid #2858cf}input{display:none}
#log div{padding:8px 10px;background:#fff;border-radius:6px;margin:6px 0}#log .bad{color:#c00}</style></head>
<body><h1>Send photos to SolidSmurfs</h1><p>For: <b>{label}</b></p>
<label class="b">Take a photo<input id="cam" type="file" accept="image/*" capture="environment"></label>
<label class="b alt">Choose photos<input id="pick" type="file" accept="image/*" multiple></label>
<div id="log"></div><p>This link works for {minutes} minutes from when it was made.</p>
<script>
const log=(t,bad)=>{const d=document.createElement('div');d.textContent=t;if(bad)d.className='bad';document.getElementById('log').prepend(d);};
async function send(files){for(const f of files){log('Sending '+(f.name||'photo')+'…');
try{const r=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':f.type||'image/jpeg','X-Name':encodeURIComponent(f.name||'')},body:f});
const j=await r.json();log(r.ok?'Sent: '+(f.name||'photo'):(j.error||'Not sent'),!r.ok);}catch(e){log('Not sent: '+e.message,true);}}}
for(const id of ['cam','pick'])document.getElementById(id).addEventListener('change',e=>{send([...e.target.files]);e.target.value='';});
</script></body></html>"""


class PhoneLink:
    def __init__(self, bind=None):
        import os
        # all of this PC's network addresses, for a phone (tests keep to this PC: bind, or SOLIDSMUFS_PHONE_BIND)
        self.bind = bind or os.environ.get("SOLIDSMUFS_PHONE_BIND") or "0.0.0.0"
        self.codes = {}  # code: {"label", "until", "inbox": [{"name", "type", "data"}], "count"}
        self.lock = threading.Lock()
        self.httpd = None
        self.timer = None

    # ------------------------------------------------------------------ the window's side
    def start(self, label):
        """A new code for the phone: {"code", "url", "until", "qr"}. Starts the network server if it isn't running."""
        host = lan_address()
        if not host:
            raise ValueError("This PC doesn't seem to be on a local network, so a phone can't reach it.")
        with self.lock:
            self._sweep()
            if self.httpd is None:
                link = self

                class Handler(_PhoneHandler):
                    ctx = link

                self.httpd = ThreadingHTTPServer((self.bind, 0), Handler)
                self.httpd.daemon_threads = True
                threading.Thread(target=self.httpd.serve_forever, daemon=True, name="solidsmufs-phone").start()
                self._tick()
            code = secrets.token_urlsafe(18)
            until = time.time() + MINUTES * 60
            self.codes[code] = {"label": str(label or "a photo")[:120], "until": until, "inbox": [], "count": 0}
            port = self.httpd.server_address[1]
        url = f"http://{host}:{port}/p/{code}"
        return {"code": code, "url": url, "until": until, "minutes": MINUTES, "qr": qr_svg(url)}

    def take(self, code):
        """The photos that came for a code since it was last asked, as {"photos": [{"name", "type", "data"}], "live"}."""
        with self.lock:
            c = self.codes.get(code)
            if not c:
                return {"photos": [], "live": False}
            out, c["inbox"] = c["inbox"], []
            return {"photos": out, "live": c["until"] > time.time()}

    def stop(self, code):
        with self.lock:
            self.codes.pop(code, None)
            self._sweep()

    def close(self):
        with self.lock:
            self.codes.clear()
            self._sweep()

    # ------------------------------------------------------------------ the phone's side
    def _live(self, code):
        c = self.codes.get(code)
        return c if c and c["until"] > time.time() else None

    def page(self, code):
        with self.lock:
            c = self._live(code)
            return PAGE.replace("{label}", html.escape(c["label"])).replace("{minutes}", str(MINUTES)) if c else None

    def receive(self, code, name, ctype, data):
        with self.lock:
            c = self._live(code)
            if not c:
                raise LookupError("This link has run out: make a new one on the PC.")
            if c["count"] >= MOST_PHOTOS:
                raise ValueError(f"That's {MOST_PHOTOS} photos on this link: make a new one on the PC.")
            c["count"] += 1
            c["inbox"].append({"name": name[:120], "type": ctype, "data": data})

    # ------------------------------------------------------------------ keeping it closed when it isn't used
    def _sweep(self):
        """Drop codes long run out (kept a minute after, for the window to take what came), and stop the network
        server when none are left. Called with the lock held."""
        now = time.time()
        for k in [k for k, c in self.codes.items() if c["until"] + 60 < now]:
            del self.codes[k]
        if not self.codes and self.httpd is not None:
            httpd, self.httpd = self.httpd, None
            threading.Thread(target=httpd.shutdown, daemon=True).start()
            httpd.server_close()

    def _tick(self):
        def run():
            with self.lock:
                self._sweep()
                going = self.httpd is not None
            if going:
                self._tick()
        self.timer = threading.Timer(30, run)
        self.timer.daemon = True
        self.timer.start()


class _PhoneHandler(BaseHTTPRequestHandler):
    ctx: PhoneLink = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _code(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        return parts[1] if len(parts) == 2 and parts[0] == "p" else None

    def do_GET(self):
        code = self._code()
        page = self.ctx.page(code) if code else None
        if page is None:
            return self._send(404, b"Not found", "text/plain")
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        code = self._code()
        n = int(self.headers.get("Content-Length") or 0)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if n <= 0 or n > MOST_BYTES:
            self.close_connection = True
            return self._json({"error": "A photo up to 25 MB."}, 413)
        data = self.rfile.read(n)  # (read through first, so the answer isn't cut off)
        if not code:
            return self._send(404, b"Not found", "text/plain")
        if ctype not in TYPES:
            return self._json({"error": "That isn't a photo."}, 415)
        from urllib.parse import unquote
        try:
            self.ctx.receive(code, unquote(self.headers.get("X-Name") or ""), ctype, data)
        except LookupError as e:
            return self._json({"error": str(e)}, 404)
        except ValueError as e:
            return self._json({"error": str(e)}, 429)
        self._json({"ok": True})
