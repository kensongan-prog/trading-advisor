#!/usr/bin/env python3
"""
server.py — local control server for the trading dashboard.

Serves dashboard.html at http://localhost:8787 with an injected control bar
(refresh buttons, watchlist + journal forms, job log) so day-to-day data
management needs no terminal. All actions shell out to the existing CLIs
(dashboard.py, wl.py, j.py) — no logic is duplicated here.

Refresh policy (hybrid, per operator decision 2026-06-10):
  - QUICK refresh (prices/macro/Polymarket) may auto-fire on page load when
    dashboard.html is older than 12h.
  - FULL refresh (LLM-scored sentiment + news glyph + discovery) is always a
    manual button press — free-tier LLM scoring can 429 and should be watched.

Usage:
  python3 server.py [--port 8787] [--open]
"""

import argparse
import json
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
DASHBOARD_HTML = PROJECT_ROOT / "dashboard.html"
DASHBOARD_PY = SCRIPT_DIR / "dashboard.py"
WL_PY = SKILLS_DIR / "watchlist" / "wl.py"
J_PY = SKILLS_DIR / "journal" / "j.py"

AUTO_REFRESH_AGE_H = 12  # quick-refresh auto-fires when dashboard.html is older

# Quick honors existing TTLs — fresh caches are skipped, stale/missing ones refetch.
# Matches the v2.0.0 doc'd behavior ("Rebuilds from caches; only fetches what's expired").
# Polymarket stays explicit because the operator clicking Quick is signaling "I want
# fresh now"; it'd also auto-refresh at >18h via dashboard.py's age check.
# Full keeps --force because the operator is explicitly asking to nuke and rebuild.
QUICK_FLAGS = ["--refresh-polymarket"]
FULL_FLAGS = ["--force", "--refresh-polymarket", "--refresh-sentiment",
              "--refresh-news", "--refresh-news-glyph", "--with-discovery"]


# ----------------------------------------------------------------- job runner

class Job:
    """One background job at a time; status + log tail polled by the page."""

    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.label = ""
        self.state = "idle"      # idle | running | done | error
        self.log = []            # lines
        self.finished_at = None

    def start(self, label, argv):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.label = label
            self.state = "running"
            self.log = [f"$ {' '.join(argv)}"]
            self.finished_at = None
            self.thread = threading.Thread(target=self._run, args=(argv,), daemon=True)
            self.thread.start()
            return True

    def _run(self, argv):
        try:
            proc = subprocess.Popen(
                argv, cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc.stdout:
                with self.lock:
                    self.log.append(line.rstrip("\n"))
                    if len(self.log) > 500:
                        self.log = self.log[-500:]
            rc = proc.wait()
            with self.lock:
                self.state = "done" if rc == 0 else "error"
                self.log.append(f"[exit {rc}]")
                self.finished_at = time.time()
        except Exception as e:
            with self.lock:
                self.state = "error"
                self.log.append(f"[server error] {e}")
                self.finished_at = time.time()

    def status(self):
        with self.lock:
            return {
                "state": self.state,
                "label": self.label,
                "log_tail": self.log[-15:],
                "finished_at": self.finished_at,
            }


JOB = Job()

WATCHER_PY = SCRIPT_DIR / "watcher.py"


class Watcher:
    """Manages the long-running watcher.py loop as a child process."""

    def __init__(self):
        self.proc = None
        self.log = []
        self.lock = threading.Lock()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, ignore_hours=False):
        if self.running():
            return False
        argv = [sys.executable, str(WATCHER_PY), "--interval", "60"]
        if ignore_hours:
            argv.append("--ignore-hours")
        self.log = [f"$ {' '.join(argv)}"]
        self.proc = subprocess.Popen(
            argv, cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._drain, daemon=True).start()
        return True

    def _drain(self):
        for line in self.proc.stdout:
            with self.lock:
                self.log.append(line.rstrip("\n"))
                if len(self.log) > 200:
                    self.log = self.log[-200:]

    def stop(self):
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            return True
        return False

    def status(self):
        with self.lock:
            return {"running": self.running(), "log_tail": self.log[-12:]}


WATCHER = Watcher()


def run_cli(argv, timeout=120):
    """Synchronous CLI call (watchlist/journal actions — fast)."""
    proc = subprocess.run(
        argv, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


# ------------------------------------------------------------ injected UI

CONTROL_BAR = """
<style>
#tactl{position:fixed;bottom:14px;right:14px;z-index:99999;font:13px/1.45 -apple-system,system-ui,sans-serif;color:#ddd}
#tactl .panel{background:#16181d;border:1px solid #333;border-radius:10px;box-shadow:0 4px 18px rgba(0,0,0,.5);width:330px;overflow:hidden}
#tactl header{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#1d2027;cursor:pointer;user-select:none}
#tactl header .age{margin-left:auto;font-size:11px;color:#8a8f98}
#tactl .body{padding:10px 12px;display:none}
#tactl.open .body{display:block}
#tactl button{background:#2b3140;border:1px solid #444;color:#eee;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px}
#tactl button:hover{background:#39415a}
#tactl button:disabled{opacity:.45;cursor:default}
#tactl .row{display:flex;gap:6px;margin:6px 0;flex-wrap:wrap}
#tactl input,#tactl select,#tactl textarea{background:#0f1115;border:1px solid #383d47;color:#ddd;border-radius:5px;padding:4px 6px;font-size:12px;flex:1;min-width:60px}
#tactl details{margin:8px 0;border-top:1px solid #2a2d34;padding-top:6px}
#tactl summary{cursor:pointer;color:#9ecbff;font-size:12px}
#tactl pre{background:#0b0d10;border:1px solid #2a2d34;border-radius:6px;padding:6px;max-height:160px;overflow:auto;font-size:10.5px;white-space:pre-wrap;margin:6px 0 0}
#tactl .stat{font-size:11px;color:#8a8f98;margin-top:4px}
#tactl .err{color:#ff7b7b}#tactl .ok{color:#7bd88f}
</style>
<div id="tactl"><div class="panel">
<header onclick="document.getElementById('tactl').classList.toggle('open')">
⚙️ <b>Control</b> <span id="tactl-state"></span><span class="age" id="tactl-age"></span>
</header>
<div class="body">
<div class="row">
<button id="btn-quick" onclick="taRefresh('quick')">⚡ Quick refresh</button>
<button id="btn-full" onclick="taRefresh('full')" title="Sentiment LLM scoring + news + discovery — slow, watched manually by design">🔄 Full refresh</button>
</div>
<div class="stat">Quick = prices/macro/Polymarket. Full = + LLM sentiment, news, discovery (minutes).</div>
<details><summary>🔔 Watcher (level alerts)</summary>
<div class="row"><button id="w-start" onclick="taWatcher('start')">▶ Start</button><button id="w-stop" onclick="taWatcher('stop')">■ Stop</button><button onclick="taWatcher('scan')">Scan now</button></div>
<div class="stat" id="w-state">checking…</div>
</details>
<details><summary>📐 Setup Queue (P1-ready)</summary>
<div class="row"><button onclick="taSetupQueue()">Load candidates</button></div>
<div id="sq-list" class="stat">click Load to list Phase-1-ready names</div>
</details>
<details><summary>Watchlist</summary>
<div class="row"><select id="wl-action"><option value="add">add</option><option value="remove">remove</option><option value="update">update thesis</option></select><input id="wl-ticker" placeholder="ticker"></div>
<div class="row"><input id="wl-text" placeholder="thesis (add/update) or reason (remove)"></div>
<div class="row"><button onclick="taWatchlist()">Apply</button></div>
</details>
<details><summary>Journal</summary>
<div class="row"><select id="j-action"><option value="update">update note</option><option value="live">go LIVE</option><option value="close">close</option></select><input id="j-id" placeholder="id, e.g. AUPH"></div>
<div class="row"><input id="j-notes" placeholder="notes"></div>
<div class="row" id="j-close-row" style="display:none"><select id="j-result"><option>win</option><option>loss</option><option>scratch</option><option>timeout</option></select><input id="j-r" placeholder="R (e.g. 2.05)"></div>
<div class="row" id="j-live-row" style="display:none"><select id="j-mode"><option value="--paper">paper</option><option value="--real">real</option></select><input id="j-fill" placeholder="fill price"></div>
<div class="row"><button onclick="taJournal()">Apply</button> <button onclick="taJournalList()">List entries</button></div>
</details>
<pre id="tactl-log" style="display:none"></pre>
<div class="stat" id="tactl-msg"></div>
</div></div></div>
<script>
(function(){
const $=id=>document.getElementById(id);
const builtAt = __BUILT_AT__; // epoch seconds of dashboard.html mtime
function fmtAge(){const h=(Date.now()/1000-builtAt)/3600;return h<1?Math.round(h*60)+'m old':h.toFixed(1)+'h old';}
$('tactl-age').textContent='data '+fmtAge();
let wasRunning=false;
async function poll(){
  try{
    const s=await (await fetch('/api/status')).json();
    if(s.watcher){
      const w=$('w-state');
      if(w) w.innerHTML = s.watcher.running
        ? '<span class="ok">● running</span> '+(s.watcher.log_tail.slice(-1)[0]||'')
        : '<span class="dim">○ stopped</span>';
    }
    const j=s.job;
    if(j.state==='running'){
      wasRunning=true;
      $('tactl-state').textContent='⏳ '+j.label;
      $('tactl-log').style.display='block';
      $('tactl-log').textContent=j.log_tail.join('\\n');
      $('tactl-log').scrollTop=1e9;
      $('btn-quick').disabled=$('btn-full').disabled=true;
    } else {
      $('btn-quick').disabled=$('btn-full').disabled=false;
      if(wasRunning){ // job just finished → reload to show fresh dashboard
        if(j.state==='done'){location.reload();return;}
        $('tactl-state').innerHTML='<span class="err">✗ '+j.label+' failed</span>';
        $('tactl-log').textContent=j.log_tail.join('\\n');
        wasRunning=false;
      }
    }
  }catch(e){}
  setTimeout(poll,2000);
}
poll();
window.taRefresh=async function(mode){
  document.getElementById('tactl').classList.add('open');
  await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
};
window.taWatcher=async function(action){
  const r=await (await fetch('/api/watcher',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})})).json();
  if(action==='scan'){ $('tactl-log').style.display='block'; $('tactl-log').textContent=r.output; }
};
window.taSetupQueue=async function(){
  const r=await (await fetch('/api/setup-queue')).json();
  const el=$('sq-list');
  if(!r.ok){ el.textContent='error: '+r.output; return; }
  if(!r.candidates.length){ el.innerHTML='<span class="dim">no P1-ready names right now (need trend intact + RSI 35-50).</span>'; return; }
  el.innerHTML=r.candidates.map(function(c){
    const tag=c.already_drafted?' <span style="color:var(--yellow)">[drafted]</span>':'';
    return '<div style="margin:4px 0">'+
      '<b>'+c.ticker+'</b> RSI '+c.rsi+' · entry $'+c.entry+' stop $'+c.stop+' tp1 $'+c.tp1+' · '+c.shares+' sh ($'+c.dollar_risk+' risk)'+tag+
      ' <button onclick="taCreateProspectus(\\''+c.ticker+'\\')">Draft</button></div>';
  }).join('');
};
window.taCreateProspectus=async function(ticker){
  const r=await (await fetch('/api/setup-queue/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker})})).json();
  $('tactl-log').style.display='block'; $('tactl-log').textContent=r.output;
  $('tactl-msg').innerHTML=r.ok?'<span class="ok">✓ prospectus drafted — rebuild queued</span>':'<span class="err">✗ '+r.output+'</span>';
};
window.taWatchlist=async function(){
  const r=await (await fetch('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:$('wl-action').value,ticker:$('wl-ticker').value.trim(),text:$('wl-text').value.trim()})})).json();
  showResult(r);
};
$('j-action').addEventListener('change',function(){
  $('j-close-row').style.display=this.value==='close'?'flex':'none';
  $('j-live-row').style.display=this.value==='live'?'flex':'none';
});
window.taJournal=async function(){
  const r=await (await fetch('/api/journal',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:$('j-action').value,id:$('j-id').value.trim(),notes:$('j-notes').value.trim(),
      result:$('j-result').value,r:$('j-r').value.trim(),mode:$('j-mode').value,fill:$('j-fill').value.trim()})})).json();
  showResult(r);
};
window.taJournalList=async function(){
  const r=await (await fetch('/api/journal/list')).json();
  $('tactl-log').style.display='block';$('tactl-log').textContent=r.output;
};
function showResult(r){
  $('tactl-log').style.display='block';$('tactl-log').textContent=r.output;
  $('tactl-msg').innerHTML=r.ok?'<span class="ok">✓ done — quick rebuild queued</span>':'<span class="err">✗ failed (rc='+r.rc+')</span>';
}
// hybrid auto-refresh: quick-only, once per browser session, when stale
const ageH=(Date.now()/1000-builtAt)/3600;
if(ageH>__AUTO_AGE__ && !sessionStorage.getItem('ta_auto_refreshed')){
  sessionStorage.setItem('ta_auto_refreshed','1');
  document.getElementById('tactl').classList.add('open');
  $('tactl-msg').textContent='data >'+__AUTO_AGE__+'h old — auto quick refresh started';
  taRefresh('quick');
}
})();
</script>
"""


def render_dashboard():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    bar = CONTROL_BAR.replace("__BUILT_AT__", str(int(DASHBOARD_HTML.stat().st_mtime)))
    bar = bar.replace("__AUTO_AGE__", str(AUTO_REFRESH_AGE_H))
    if "</body>" in html:
        idx = html.rindex("</body>")
        html = html[:idx] + bar + html[idx:]
    else:
        html += bar
    return html


# ------------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter console
        if "/api/status" not in (args[0] if args else ""):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        if self.path in ("/", "/dashboard.html"):
            if not DASHBOARD_HTML.is_file():
                self._send(200, "<h2>No dashboard.html yet — click Quick refresh.</h2>"
                           + CONTROL_BAR.replace("__BUILT_AT__", "0").replace("__AUTO_AGE__", "999999"),
                           "text/html")
                return
            self._send(200, render_dashboard(), "text/html")
        elif self.path == "/api/status":
            self._json({"job": JOB.status(),
                        "watcher": WATCHER.status(),
                        "dashboard_mtime": DASHBOARD_HTML.stat().st_mtime if DASHBOARD_HTML.is_file() else 0})
        elif self.path == "/api/journal/list":
            rc, out = run_cli([sys.executable, str(J_PY), "list"])
            self._json({"ok": rc == 0, "rc": rc, "output": out})
        elif self.path == "/api/setup-queue":
            try:
                import setup_queue
                self._json({"ok": True, "candidates": setup_queue.candidates()})
            except Exception as e:
                self._json({"ok": False, "output": f"{type(e).__name__}: {e}"})
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        body = self._body()
        if self.path == "/api/refresh":
            flags = FULL_FLAGS if body.get("mode") == "full" else QUICK_FLAGS
            label = "full refresh" if body.get("mode") == "full" else "quick refresh"
            started = JOB.start(label, [sys.executable, str(DASHBOARD_PY)] + flags)
            self._json({"ok": started, "output": "" if started else "a job is already running"})
        elif self.path == "/api/watchlist":
            self._json(self._watchlist(body))
        elif self.path == "/api/journal":
            self._json(self._journal(body))
        elif self.path == "/api/watcher":
            act = body.get("action")
            if act == "start":
                ok = WATCHER.start(ignore_hours=bool(body.get("ignore_hours")))
                self._json({"ok": ok, "output": "" if ok else "watcher already running"})
            elif act == "stop":
                self._json({"ok": WATCHER.stop()})
            elif act == "scan":
                argv = [sys.executable, str(WATCHER_PY), "--once", "--ignore-hours"]
                rc, out = run_cli(argv, timeout=90)
                self._json({"ok": rc == 0, "output": out or "(scan clean)"})
            else:
                self._json({"ok": False, "output": f"unknown action {act!r}"})
        elif self.path == "/api/setup-queue/create":
            t = body.get("ticker", "")
            if not t:
                self._json({"ok": False, "output": "ticker required"})
                return
            try:
                import setup_queue, portfolio
                heat = portfolio.heat()
                rc, out = setup_queue.create(t, heat_used=heat["used"], heat_max=heat["max"])
                if rc == 0:
                    JOB.start("rebuild after prospectus draft", [sys.executable, str(DASHBOARD_PY)])
                self._json({"ok": rc == 0, "output": out})
            except Exception as e:
                self._json({"ok": False, "output": f"{type(e).__name__}: {e}"})
        else:
            self._send(404, "not found", "text/plain")

    def _watchlist(self, b):
        action, ticker, text = b.get("action"), b.get("ticker", ""), b.get("text", "")
        if not ticker:
            return {"ok": False, "rc": -1, "output": "ticker required"}
        argv = [sys.executable, str(WL_PY)]
        if action == "add":
            argv += ["add", ticker, "--yes"] + (["--thesis", text] if text else [])
        elif action == "remove":
            if not text:
                return {"ok": False, "rc": -1, "output": "removal reason required (doctrine)"}
            argv += ["remove", ticker, "--reason", text, "--yes"]
        elif action == "update":
            if not text:
                return {"ok": False, "rc": -1, "output": "new thesis required"}
            argv += ["update", ticker, "--thesis", text, "--yes"]
        else:
            return {"ok": False, "rc": -1, "output": f"unknown action {action!r}"}
        rc, out = run_cli(argv, timeout=180)
        if rc == 0:  # rebuild so the dashboard reflects the edit (cache-friendly, no --force)
            JOB.start("rebuild after watchlist edit", [sys.executable, str(DASHBOARD_PY)])
        return {"ok": rc == 0, "rc": rc, "output": out}

    def _journal(self, b):
        action, jid = b.get("action"), b.get("id", "")
        if not jid:
            return {"ok": False, "rc": -1, "output": "journal id required"}
        argv = [sys.executable, str(J_PY)]
        if action == "update":
            if not b.get("notes"):
                return {"ok": False, "rc": -1, "output": "notes required"}
            argv += ["update", jid, "--notes", b["notes"], "--yes"]
        elif action == "live":
            argv += ["live", jid, b.get("mode") or "--paper", "--yes"]
            if b.get("fill"):
                argv += ["--fill", b["fill"]]
            if b.get("notes"):
                argv += ["--notes", b["notes"]]
        elif action == "close":
            argv += ["close", jid, "--result", b.get("result", "scratch"), "--yes"]
            if b.get("r"):
                argv += ["--r", b["r"]]
            if b.get("notes"):
                argv += ["--notes", b["notes"]]
        else:
            return {"ok": False, "rc": -1, "output": f"unknown action {action!r}"}
        rc, out = run_cli(argv)
        if rc == 0:
            JOB.start("rebuild after journal edit", [sys.executable, str(DASHBOARD_PY)])
        return {"ok": rc == 0, "rc": rc, "output": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--open", action="store_true", help="Open browser after starting")
    ap.add_argument("--lan", action="store_true",
                    help="Bind to 0.0.0.0 so phones/tablets on the same WiFi can view the dashboard. "
                         "Anyone on your network can reach it — only use on trusted networks.")
    args = ap.parse_args()
    bind = "0.0.0.0" if args.lan else "127.0.0.1"
    srv = ThreadingHTTPServer((bind, args.port), Handler)
    url = f"http://localhost:{args.port}/"
    print(f"Trading dashboard control server → {url}  (Ctrl-C to stop)")
    if args.lan:
        # Best-effort LAN-IP discovery so the user can type it into their phone browser.
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
            print(f"📱 Phone access: http://{lan_ip}:{args.port}/  (same WiFi only)")
        except Exception:
            print(f"📱 Phone access: http://<your-mac-LAN-IP>:{args.port}/  (same WiFi only)")
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
