#!/usr/bin/env python3
"""
server.py — local control server for the trading dashboard.

Serves dashboard.html at http://localhost:8789 with an injected control bar
(refresh buttons, watchlist + journal forms, job log) so day-to-day data
management needs no terminal. All actions shell out to the existing CLIs
(dashboard.py, wl.py, j.py) — no logic is duplicated here.

Refresh policy:
  - QUICK refresh runs --refresh-stale: checks the Data Health panel state and
    refreshes exactly what is stale/transient/missing, honoring TTLs. Fires
    automatically on page load when dashboard.html is older than 12h.
  - FULL refresh (LLM-scored sentiment + news + discovery) is always a manual
    button press — free-tier LLM scoring can 429 and should be watched.

Usage:
  python3 server.py [--port 8789] [--open]
"""

import argparse
import json
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class DualStackHTTPServer(ThreadingHTTPServer):
    """IPv6 server that also accepts IPv4 (v4-mapped) on one socket.

    The default ThreadingHTTPServer is IPv4-only, so binding 0.0.0.0 leaves the
    server unreachable over IPv6 — `localhost` → ::1 on macOS, or a Tailscale
    MagicDNS / IPv6 address — which gets connection-refused and makes the
    dashboard look down. Binding `::` with IPV6_V6ONLY=0 serves 127.0.0.1, LAN
    IPv4, Tailscale IPv4, ::1, IPv6, and MagicDNS from a single socket.
    """
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
DASHBOARD_HTML = PROJECT_ROOT / "dashboard.html"
DASHBOARD_PY = SCRIPT_DIR / "dashboard.py"
WL_PY = SKILLS_DIR / "watchlist" / "wl.py"
J_PY = SKILLS_DIR / "journal" / "j.py"
LAST_JOB_LOG = PROJECT_ROOT / ".claude" / "cache" / "dashboard" / "last_job.log"  # persisted job output for post-mortem

AUTO_REFRESH_AGE_H = 12  # quick-refresh auto-fires when dashboard.html is older


def dashboard_readiness(now=None):
    now = time.time() if now is None else now
    if not DASHBOARD_HTML.is_file():
        return {"state": "blocked", "ready": False, "blocking": ["dashboard_html"], "stale": []}
    age_hours = max(0.0, (now - DASHBOARD_HTML.stat().st_mtime) / 3600.0)
    html = DASHBOARD_HTML.read_text(encoding="utf-8", errors="ignore")
    match = re.search(
        r'id="ta-health-data"[^>]*data-stale="(\d+)"[^>]*data-transient="(\d+)"[^>]*data-permanent="(\d+)"[^>]*data-server="(\d+)"[^>]*data-agent="(\d+)"',
        html,
    )
    counts = {"stale": 0, "transient": 0, "permanent": 0, "server": 0, "agent": 0}
    if match:
        counts = dict(zip(counts, (int(value) for value in match.groups())))
    stale = []
    if age_hours > AUTO_REFRESH_AGE_H:
        stale.append("dashboard_html")
    if sum(counts.values()):
        stale.append("data_sources")
    state = "degraded" if stale else "ready"
    return {"state": state, "ready": state == "ready", "blocking": [], "stale": stale,
            "dashboard_age_hours": round(age_hours, 1), "source_counts": counts}

# Quick = stale-driven: inspects the Data Health panel state at build time and
# refreshes exactly what is flagged (stale/transient/missing), skipping fresh
# sources. Polymarket, screener, KLSE CLIs, sentiment — all handled automatically
# based on what is actually stale. No hardcoded layer list needed.
QUICK_FLAGS = ["--refresh-stale"]
FULL_FLAGS = ["--force", "--refresh-polymarket", "--refresh-sentiment",
              "--refresh-news", "--refresh-news-glyph", "--with-discovery"]

# Import health module for /api/refresh-source validation.
try:
    import sys as _sys
    _sys.path.insert(0, str(SCRIPT_DIR))
    import health as _health_mod
except Exception:
    _health_mod = None


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
                self._persist_log()
        except Exception as e:
            with self.lock:
                self.state = "error"
                self.log.append(f"[server error] {e}")
                self.finished_at = time.time()
                self._persist_log()

    def _persist_log(self):
        """Write the full job output to a known file so failures stay
        diagnosable after a restart (the in-memory log is otherwise lost).
        Caller holds self.lock."""
        try:
            LAST_JOB_LOG.parent.mkdir(parents=True, exist_ok=True)
            LAST_JOB_LOG.write_text(
                f"# {self.label} — state={self.state}\n" + "\n".join(self.log))
        except Exception:
            pass

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
#ta-banner{display:none;position:fixed;top:0;left:0;right:0;z-index:99998;background:linear-gradient(90deg,#1e3a5f,#2b3140);color:#fff;font:13px/1.5 -apple-system,system-ui,sans-serif;padding:10px 16px;border-bottom:2px solid #4a90e2;box-shadow:0 3px 12px rgba(0,0,0,.45);align-items:center;gap:12px;justify-content:center}
#ta-banner.show{display:flex}
#ta-banner .ta-spin{width:15px;height:15px;border:2px solid rgba(255,255,255,.25);border-top-color:#7ab8f5;border-radius:50%;animation:taspin .8s linear infinite;flex:0 0 auto}
@keyframes taspin{to{transform:rotate(360deg)}}
#ta-banner .ta-elapsed{font-variant-numeric:tabular-nums;color:#9ecbff;font-weight:700}
#ta-banner .ta-phase{color:#cfe0f5;opacity:.85}
#ta-toast{position:fixed;bottom:80px;right:14px;z-index:99997;background:#1d2027;border:1px solid #444;border-radius:8px;padding:10px 14px;color:#ddd;font:12px/1.5 -apple-system,system-ui,sans-serif;max-width:320px;box-shadow:0 4px 14px rgba(0,0,0,.5);display:none}
</style>
<div id="ta-banner"><span class="ta-spin"></span><span><b id="ta-banner-title">Refreshing…</b> <span class="ta-phase" id="ta-phase">starting</span></span><span class="ta-elapsed" id="ta-elapsed">0:00</span></div>
<div id="ta-toast"></div>
<div id="tactl"><div class="panel">
<header onclick="document.getElementById('tactl').classList.toggle('open')">
⚙️ <b>Control</b> <span id="tactl-state"></span><span class="age" id="tactl-age"></span>
</header>
<div class="body">
<div class="row">
<button id="btn-quick" onclick="taRefresh('quick')" title="Refresh only stale/transient sources — leaves fresh caches untouched">⚡ Quick refresh</button>
<button id="btn-full" onclick="taRefresh('full')" title="Force-rebuild everything: LLM sentiment, news, discovery — slow, watch manually">🔄 Full refresh</button>
</div>
<div class="stat">Quick = refresh exactly what Data Health flags stale. Full = force-rebuild all layers (minutes).</div>
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
<div class="row"><select id="wl-section"><option value="auto">auto-classify</option><option value="us">us</option><option value="klse">klse</option><option value="crypto">crypto</option><option value="options">options</option></select><label style="font-weight:normal;font-size:12px"><input type="checkbox" id="wl-force"> force-add (skip resolve)</label></div>
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
$('tactl-age').textContent='data '+fmtAge(); // first paint; poll() keeps it live every 2s
let wasRunning=false;
// ── Progress banner: shown the instant a refresh is clicked, with a live
// elapsed timer (the unmistakable "working, not frozen" signal) + the current
// build phase pulled from the job log. ───────────────────────────────────────
let taTimer=null, taStartMs=0;
function taFmtElapsed(s){const m=Math.floor(s/60),ss=s%60;return m+':'+(ss<10?'0':'')+ss;}
function taBannerStart(title){
  const b=$('ta-banner'); if(!b) return;
  taStartMs=Date.now();
  $('ta-banner-title').textContent=title||'Refreshing…';
  $('ta-phase').textContent='starting — this can take a minute or two';
  $('ta-elapsed').textContent='0:00';
  b.classList.add('show');
  if(taTimer) clearInterval(taTimer);
  taTimer=setInterval(function(){ $('ta-elapsed').textContent=taFmtElapsed(Math.floor((Date.now()-taStartMs)/1000)); },1000);
}
function taBannerStop(){
  const b=$('ta-banner'); if(b) b.classList.remove('show');
  if(taTimer){ clearInterval(taTimer); taTimer=null; }
}
async function poll(){
  try{
    const s=await (await fetch('/api/status')).json();
    // Live age update every poll cycle
    $('tactl-age').textContent='data '+fmtAge();
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
      // Ensure the banner is up even when a job was started by another path
      // (auto-quick on load, a watchlist/journal-edit rebuild).
      if(!$('ta-banner').classList.contains('show')) taBannerStart(j.label||'Refreshing…');
      // Surface the latest progress line (e.g. "[5/8] Fetching US ticker data…").
      const lines=(j.log_tail||[]).filter(function(l){return l && l.trim();});
      const last=lines.length?lines[lines.length-1].replace(/^\\$\\s.*/,'working…').trim():'';
      if(last) $('ta-phase').textContent=last.slice(0,90);
    } else {
      $('btn-quick').disabled=$('btn-full').disabled=false;
      taBannerStop();
      if(wasRunning){
        if(j.state==='done'){
          // Snapshot scroll/expanded/sort/filter, then reload — the fresh page's
          // taRestoreUiState() puts your view back so an update never loses your place.
          taCaptureUiState();location.reload();return;
        }
        $('tactl-state').innerHTML='<span class="err">✗ '+j.label+' failed</span>';
        $('tactl-log').textContent=j.log_tail.join('\\n');
        $('tactl-log').style.display='block';
        showToast('<span class="err">✗ '+(j.label||'Refresh')+' failed — see the log below, or .claude/cache/dashboard/last_job.log</span>', 15000);
        taNotify('✗ Dashboard refresh failed', (j.label||'refresh')+' — see .claude/cache/dashboard/last_job.log');
        sessionStorage.removeItem('ta_pre_refresh');  // no reload on failure; don't leave stale pre-state
        wasRunning=false;
      }
    }
  }catch(e){}
  setTimeout(poll,2000);
}
poll();
// Capture pre-refresh health state so the post-reload toast can diff it
function captureHealthState(){
  const hd=$('ta-health-data');
  if(!hd) return;
  sessionStorage.setItem('ta_pre_refresh',JSON.stringify({
    stale:+hd.dataset.stale, transient:+hd.dataset.transient,
    permanent:+hd.dataset.permanent, server:+hd.dataset.server, agent:+hd.dataset.agent
  }));
}
// Snapshot ephemeral view state just before a reload; the rebuilt page's
// taRestoreUiState() (baked by dashboard.py) reads it back. Keyed by ticker so
// expanded rows survive re-sorting and watchlist add/remove.
function taCaptureUiState(){
  try{
    var tables=document.querySelectorAll('table'), sorts=[];
    tables.forEach(function(t,ti){
      var th=t.querySelector('th.sort-asc, th.sort-desc');
      if(th){ var ths=Array.prototype.slice.call(t.querySelectorAll('th'));
        sorts.push({t:ti,c:ths.indexOf(th),a:th.classList.contains('sort-asc')}); }
    });
    var expanded=[];
    document.querySelectorAll('tr.exp-details.open').forEach(function(body){
      var row=document.querySelector('tr.exp-row[data-row-id="'+body.id.replace(/-body$/,'')+'"]');
      if(row && row.dataset.filter) expanded.push(row.dataset.filter.split(' ')[0]);
    });
    var fi=document.getElementById('wl-filter-input');
    sessionStorage.setItem('ta_ui_state',JSON.stringify({
      y:window.scrollY, sorts:sorts, expanded:expanded, filter:fi?fi.value:''
    }));
  }catch(e){}
}
// Ask for OS-notification permission on the user's click (browsers require a
// gesture). Best-effort; declined/unsupported just falls back to the in-page toast.
function taAskNotify(){ try{ if('Notification' in window && Notification.permission==='default') Notification.requestPermission(); }catch(e){} }
window.taRefresh=async function(mode){
  taAskNotify();
  captureHealthState();
  taBannerStart(mode==='full'?'Full refresh — rebuilding everything…':'Refreshing stale data…');
  document.getElementById('tactl').classList.add('open');
  $('btn-quick').disabled=$('btn-full').disabled=true; // disable immediately; re-enabled by poll
  try{
    const r=await (await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})})).json();
    if(!r.ok){
      // A job is already running — keep the banner (work IS in progress) but say so.
      $('tactl-msg').innerHTML='<span class="err">⏳ a refresh is already running — this one was skipped</span>';
      $('tactl-log').style.display='block';
    }
  }catch(e){ taBannerStop(); $('btn-quick').disabled=$('btn-full').disabled=false;
    $('tactl-msg').innerHTML='<span class="err">✗ could not reach server — is it still running?</span>'; }
};
// Per-source refresh button handler (injected by dashboard.py render_health_panel)
window.taRefreshSource=async function(source){
  taAskNotify();
  captureHealthState();
  taBannerStart('Refreshing '+source+'…');
  document.getElementById('tactl').classList.add('open');
  $('btn-quick').disabled=$('btn-full').disabled=true;
  try{
    const r=await (await fetch('/api/refresh-source',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source})})).json();
    if(!r.ok){
      taBannerStop();
      $('tactl-msg').innerHTML='<span class="err">'+r.output+'</span>';
      $('btn-quick').disabled=$('btn-full').disabled=false;
    }
  }catch(e){ taBannerStop(); $('btn-quick').disabled=$('btn-full').disabled=false;
    $('tactl-msg').innerHTML='<span class="err">✗ could not reach server — is it still running?</span>'; }
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
    body:JSON.stringify({action:$('wl-action').value,ticker:$('wl-ticker').value.trim(),text:$('wl-text').value.trim(),section:$('wl-section').value,allow_unresolved:$('wl-force').checked})})).json();
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
// Best-effort OS notification (so a multi-minute refresh can ping you even when
// the tab is in the background). Silently no-ops if unsupported/denied, or in a
// non-secure context (e.g. http over Tailscale) — the in-page toast still shows.
function taNotify(title, body){
  try{
    if(!('Notification' in window) || Notification.permission!=='granted') return;
    const n=new Notification(title,{body:body||'', tag:'ta-refresh', renotify:true});
    setTimeout(function(){ try{n.close();}catch(_){} }, 8000);
  }catch(e){}
}
function showToast(html, ms){
  const toast=$('ta-toast'); if(!toast) return;
  toast.innerHTML=html+' <span style="color:#555;cursor:pointer;float:right" onclick="this.parentElement.remove()">✕</span>';
  toast.style.display='block';
  setTimeout(function(){toast.style.display='none';}, ms||9000);
}
// Post-refresh outcome toast + OS notification: diff pre vs post health counts.
function showRefreshToast(before, after){
  const tot_b=before.server+before.agent, tot_a=after.server+after.agent;
  let msg, cls='ok', note;
  if(tot_b===0){
    msg='✓ Everything was already fresh — nothing to refresh.'; note='Nothing was stale.';
  } else if(tot_a < tot_b){
    const fixed=tot_b-tot_a;
    msg='✓ Refresh done — '+fixed+' source(s) cleared'; note=fixed+' source(s) cleared';
    if(after.agent>0){ msg+=' · '+after.agent+' still need agent refresh'; note+='; '+after.agent+' need an agent session'; }
    if(after.server>0){ msg+=' · '+after.server+' still stale (TTL or rate-limited)'; note+='; '+after.server+' still stale'; }
  } else {
    cls='err';
    msg='⚠ Refresh finished but '+tot_a+' source(s) still flagged — see Control log for details';
    note=tot_a+' source(s) still flagged'+(after.agent>0?' ('+after.agent+' agent-only)':'');
  }
  showToast('<span class="'+cls+'">'+msg+'</span>');
  taNotify(cls==='ok'?'✓ Dashboard refresh complete':'⚠ Refresh finished with issues', note);
}
// On page load: check if we just reloaded after a refresh and show toast
(function checkPostRefreshToast(){
  const pre=sessionStorage.getItem('ta_pre_refresh');
  const hd=$('ta-health-data');
  if(!pre || !hd) return;
  sessionStorage.removeItem('ta_pre_refresh');
  try{
    const before=JSON.parse(pre);
    const after={stale:+hd.dataset.stale, transient:+hd.dataset.transient,
                 permanent:+hd.dataset.permanent, server:+hd.dataset.server, agent:+hd.dataset.agent};
    showRefreshToast(before, after);
  }catch(e){}
})();
// hybrid auto-refresh: quick-only, once per browser session, when stale
const ageH=(Date.now()/1000-builtAt)/3600;
if(ageH>__AUTO_AGE__ && !sessionStorage.getItem('ta_auto_refreshed')){
  sessionStorage.setItem('ta_auto_refreshed','1');
  captureHealthState();
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
                        "dashboard_mtime": DASHBOARD_HTML.stat().st_mtime if DASHBOARD_HTML.is_file() else 0,
                        "readiness": dashboard_readiness()})
        elif self.path == "/api/journal/list":
            rc, out = run_cli([sys.executable, str(J_PY), "list"])
            self._json({"ok": rc == 0, "rc": rc, "output": out})
        elif self.path == "/api/setup-queue":
            try:
                import setup_queue
                self._json({"ok": True, "candidates": setup_queue.candidates()})
            except Exception as e:
                self._json({"ok": False, "output": f"{type(e).__name__}: {e}"})
        elif self.path == "/api/panel/health":
            self._json(self._panel_health())
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        body = self._body()
        if self.path == "/api/refresh":
            flags = FULL_FLAGS if body.get("mode") == "full" else QUICK_FLAGS
            label = "full refresh" if body.get("mode") == "full" else "quick refresh"
            started = JOB.start(label, [sys.executable, str(DASHBOARD_PY)] + flags)
            self._json({"ok": started, "output": "" if started else "a job is already running"})
        elif self.path == "/api/refresh-source":
            source = body.get("source", "").strip()
            if not source:
                self._json({"ok": False, "output": "source required"})
                return
            if _health_mod is None:
                self._json({"ok": False, "output": "health module unavailable"})
                return
            ok, result = _health_mod.validate_refresh_source(source)
            if not ok:
                self._json({"ok": False, "output": result})
                return
            # Refresh ONLY this source (true per-source granularity) via its
            # REFRESH_VIA path, not the whole stale batch.
            label = f"refresh {source}"
            started = JOB.start(label, [sys.executable, str(DASHBOARD_PY), "--refresh-source", source])
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

    def _panel_health(self):
        """Re-render the Data Health panel fragment from current cache states — no data
        fetch and no full rebuild (health only reads cache freshness). Lets the client
        swap the panel in place to reflect out-of-band cache changes instantly."""
        if _health_mod is None:
            return {"ok": False, "output": "health module unavailable"}
        try:
            import dashboard
            wl = dashboard.parse_watchlist()
            recs = _health_mod.collect_health(wl)
            frag = dashboard.render_health_panel_html(
                _health_mod, _health_mod.summarize(recs), _health_mod.group_by_source(recs))
            return {"ok": True, "html": frag}
        except Exception as e:
            return {"ok": False, "output": f"{type(e).__name__}: {e}"}

    def _watchlist(self, b):
        action, ticker, text = b.get("action"), b.get("ticker", ""), b.get("text", "")
        if not ticker:
            return {"ok": False, "rc": -1, "output": "ticker required"}
        argv = [sys.executable, str(WL_PY)]
        if action == "add":
            argv += ["add", ticker, "--yes"] + (["--thesis", text] if text else [])
            section = b.get("section")
            if section and section != "auto":
                argv += ["--section", section]
            if b.get("allow_unresolved"):
                argv += ["--allow-unresolved"]
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
    ap.add_argument("--port", type=int, default=8789)
    ap.add_argument("--open", action="store_true", help="Open browser after starting")
    ap.add_argument("--lan", action="store_true",
                    help="Bind to 0.0.0.0 so phones/tablets on the same WiFi can view the dashboard. "
                         "Anyone on your network can reach it — only use on trusted networks.")
    args = ap.parse_args()
    if args.lan:
        # Dual-stack on all interfaces: IPv4 (127.0.0.1 / LAN / Tailscale-v4) AND
        # IPv6 (::1 / IPv6 / Tailscale MagicDNS) all reach the same socket.
        srv = DualStackHTTPServer(("::", args.port), Handler)
    else:
        # Loopback-only stays IPv4 — local dev hits 127.0.0.1.
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}/"
    print(f"Trading dashboard control server → {url}  (Ctrl-C to stop)")
    if args.lan:
        # Best-effort LAN-IP discovery so the user can type it into their phone browser.
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
