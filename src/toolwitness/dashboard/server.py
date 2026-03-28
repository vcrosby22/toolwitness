"""Local dashboard HTTP server — stdlib only, no Flask/FastAPI dependency.

``toolwitness dashboard`` starts on localhost:8321, reads from SQLite,
serves a single-page app with live data via JSON API endpoints.

Pages: overview, failure detail, tool analytics, session timeline.
Same pattern as TensorBoard / mkdocs serve.
"""

from __future__ import annotations

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from toolwitness.reporting.about_page import generate_about_page
from toolwitness.reporting.html_report import generate_html_report
from toolwitness.storage.sqlite import SQLiteStorage

logger = logging.getLogger("toolwitness")


def _parse_since(query: dict[str, list[str]]) -> float | None:
    """Extract a ``since`` timestamp from query parameters."""
    raw = query.get("since", [None])[0]
    if not raw:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the ToolWitness dashboard."""

    storage_path: str = ""

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug(format, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        routes: dict[str, Any] = {
            "/": self._page_overview,
            "/about": self._page_about,
            "/api/verifications": self._api_verifications,
            "/api/executions": self._api_executions,
            "/api/stats": self._api_stats,
            "/api/sessions": self._api_sessions,
            "/api/handoffs": self._api_handoffs,
            "/api/health": self._api_health,
            "/api/issue-url": self._api_issue_url,
            "/report": self._page_report,
        }

        handler = routes.get(path)
        if handler:
            handler(query)
        else:
            self._send_404()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len else b""

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        if path == "/api/false-positive":
            self._api_mark_false_positive(data)
        else:
            self._send_404()

    def _open_storage(self) -> SQLiteStorage | None:
        db_path = Path(self.storage_path)
        if not db_path.exists():
            return None
        return SQLiteStorage(db_path)

    def _page_overview(self, query: dict[str, list[str]]) -> None:
        self._send_html(_dashboard_page())

    def _page_about(self, query: dict[str, list[str]]) -> None:
        self._send_html(generate_about_page())

    def _page_report(self, query: dict[str, list[str]]) -> None:
        storage = self._open_storage()
        if not storage:
            self._send_html("<h1>No database found</h1>")
            return

        verifications = storage.query_verifications(limit=500)
        tool_stats = storage.get_tool_stats()
        sessions = storage.query_sessions(limit=50)
        storage.close()

        html = generate_html_report(verifications, tool_stats, sessions)
        self._send_html(html)

    def _api_verifications(self, query: dict[str, list[str]]) -> None:
        storage = self._open_storage()
        if not storage:
            self._send_json({"error": "no database"}, status=404)
            return

        limit = int(query.get("limit", ["50"])[0])
        classification = query.get("classification", [None])[0]
        since = _parse_since(query)
        results = storage.query_verifications(
            classification=classification, limit=limit, since=since,
        )
        storage.close()
        self._send_json({"verifications": results, "total": len(results)})

    def _api_executions(self, query: dict[str, list[str]]) -> None:
        storage = self._open_storage()
        if not storage:
            self._send_json({"error": "no database"}, status=404)
            return

        limit = int(query.get("limit", ["50"])[0])
        session_id = query.get("session_id", [None])[0]
        tool_name = query.get("tool", [None])[0]
        since = _parse_since(query)
        results = storage.query_executions(
            session_id=session_id, tool_name=tool_name, limit=limit,
            since=since,
        )
        storage.close()
        self._send_json({"executions": results, "total": len(results)})

    def _api_stats(self, query: dict[str, list[str]]) -> None:
        storage = self._open_storage()
        if not storage:
            self._send_json({"error": "no database"}, status=404)
            return

        since = _parse_since(query)
        tool_stats = storage.get_tool_stats(since=since)
        storage.close()
        self._send_json({"tools": tool_stats})

    def _api_sessions(self, query: dict[str, list[str]]) -> None:
        storage = self._open_storage()
        if not storage:
            self._send_json({"error": "no database"}, status=404)
            return

        since = _parse_since(query)
        sessions = storage.query_sessions(limit=50, since=since)
        storage.close()
        self._send_json({"sessions": sessions})

    def _api_handoffs(self, query: dict[str, list[str]]) -> None:
        storage = self._open_storage()
        if not storage:
            self._send_json({"error": "no database"}, status=404)
            return

        session_id = query.get("session_id", [None])[0]
        handoffs = storage.query_handoffs(
            session_id=session_id, limit=100,
        )
        storage.close()
        self._send_json({"handoffs": handoffs})

    def _api_health(self, query: dict[str, list[str]]) -> None:
        storage = self._open_storage()
        ok = storage is not None
        if storage:
            storage.close()
        self._send_json({
            "status": "ok" if ok else "no_database",
            "timestamp": time.time(),
        })

    def _api_issue_url(self, query: dict[str, list[str]]) -> None:
        vid = query.get("id", [""])[0]
        tool = query.get("tool", ["unknown"])[0]
        classification = query.get("classification", ["unknown"])[0]
        confidence = query.get("confidence", ["0"])[0]

        from urllib.parse import quote
        title = quote(f"[ToolWitness] {classification.upper()} detected: {tool}")
        body = quote(
            f"## ToolWitness Detection\n\n"
            f"- **Tool:** `{tool}`\n"
            f"- **Classification:** {classification.upper()}\n"
            f"- **Confidence:** {confidence}\n"
            f"- **Verification ID:** {vid}\n\n"
            f"## Evidence\n\n"
            f"_See dashboard or HTML report for full evidence details._\n\n"
            f"## Suggested Fix\n\n"
            f"_See remediation card in dashboard for fix suggestions._\n"
        )
        url = f"https://github.com/vcrosby22/toolwitness/issues/new?title={title}&body={body}"
        self._send_json({"url": url})

    def _api_mark_false_positive(self, data: dict[str, Any]) -> None:
        vid = data.get("verification_id")
        reason = data.get("reason", "")

        if not vid:
            self._send_json({"error": "verification_id required"}, status=400)
            return

        storage = self._open_storage()
        if not storage:
            self._send_json({"error": "no database"}, status=404)
            return

        ok = storage.mark_false_positive(int(vid), reason)
        storage.close()

        if ok:
            self._send_json({"status": "ok", "verification_id": vid})
        else:
            self._send_json({"error": "verification not found"}, status=404)

    def _send_html(self, content: str) -> None:
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self, data: Any, status: int = 200,
    ) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_404(self) -> None:
        body = b"Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_dashboard(
    storage_path: str,
    host: str = "127.0.0.1",
    port: int = 8321,
) -> None:
    """Start the local dashboard server."""
    DashboardHandler.storage_path = storage_path

    server = HTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{port}"
    print(f"ToolWitness dashboard running at {url}")
    print(f"  Overview:  {url}/")
    print(f"  About:     {url}/about")
    print(f"  Report:    {url}/report")
    print(f"  API:       {url}/api/verifications")
    print(f"  Health:    {url}/api/health")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


def _dashboard_page() -> str:
    """Single-page dashboard that fetches data from the JSON API."""
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ToolWitness Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: #0f172a; color: #e2e8f0; }
header { padding: 1.25rem 2rem; border-bottom: 1px solid #1e293b;
  display: flex; justify-content: space-between; align-items: center; }
h1 { font-size: 1.25rem; }
h2 { font-size: 1.1rem; margin-bottom: 0.75rem; }
.status { font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 99px; }
.status-ok { background: #052e16; color: #4ade80; }
.status-err { background: #450a0a; color: #fca5a5; }
main { max-width: 1200px; margin: 0 auto; padding: 1.5rem 2rem; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 1rem; margin-bottom: 1.5rem; }
.kpi { background: #1e293b; padding: 1.25rem; border-radius: 10px;
  border: 1px solid #334155; text-align: center; }
.kpi-val { font-size: 2rem; font-weight: 700; }
.kpi-lbl { font-size: 0.7rem; color: #64748b; text-transform: uppercase;
  letter-spacing: 0.05em; margin-top: 0.25rem; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;
  margin-bottom: 1.5rem; }
.card { background: #1e293b; padding: 1.25rem; border-radius: 10px;
  border: 1px solid #334155; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.5rem 0.6rem;
  border-bottom: 1px solid #334155; font-size: 0.85rem; }
th { color: #64748b; font-size: 0.7rem; text-transform: uppercase; }
.badge { padding: 0.1rem 0.4rem; border-radius: 3px;
  font-size: 0.7rem; font-weight: 700; color: white; }
.bar-row { display: flex; align-items: center; gap: 0.5rem;
  margin-bottom: 0.4rem; font-size: 0.8rem; }
.bar-label { width: 85px; color: #94a3b8; text-align: right; }
.bar-track { flex: 1; height: 16px; background: #0f172a;
  border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.bar-count { width: 70px; color: #94a3b8; font-size: 0.75rem; }
.empty { color: #475569; text-align: center; padding: 2rem; }
a.report-link { color: #93c5fd; text-decoration: none; font-size: 0.85rem; }
a.report-link:hover { text-decoration: underline; }
.act-btn { background: #334155; border: 1px solid #475569; color: #e2e8f0;
  padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.7rem;
  cursor: pointer; margin-right: 0.25rem; }
.act-btn:hover { background: #475569; }
.refresh { cursor: pointer; background: #334155; border: none;
  color: #e2e8f0; padding: 0.3rem 0.75rem; border-radius: 6px;
  font-size: 0.8rem; }
.refresh:hover { background: #475569; }
@media (max-width: 700px) {
  .kpis { grid-template-columns: repeat(2, 1fr); }
  .grid { grid-template-columns: 1fr; }
}
</style></head><body>
<header>
    <h1>ToolWitness Dashboard</h1>
    <div style="display:flex;gap:0.75rem;align-items:center">
        <select id="timeRange" class="refresh" onchange="loadAll()"
            style="appearance:auto;padding:0.25rem 0.4rem">
            <option value="3600">Last 1 hour</option>
            <option value="86400" selected>Last 24 hours</option>
            <option value="604800">Last 7 days</option>
            <option value="2592000">Last 30 days</option>
            <option value="0">All time</option>
        </select>
        <a href="/report" class="report-link">Full Report</a>
        <a href="/about" class="report-link">About</a>
        <button class="refresh" onclick="loadAll()">Refresh</button>
        <span id="status" class="status status-ok">connected</span>
    </div>
</header>
<main>
    <div class="kpis">
        <div class="kpi"><div class="kpi-val" id="kpi-total">—</div>
            <div class="kpi-lbl">Verifications</div></div>
        <div class="kpi"><div class="kpi-val" id="kpi-rate">—</div>
            <div class="kpi-lbl">Failure Rate</div></div>
        <div class="kpi"><div class="kpi-val" id="kpi-verified" style="color:#16a34a">—</div>
            <div class="kpi-lbl">Verified</div></div>
        <div class="kpi"><div class="kpi-val" id="kpi-failures" style="color:#dc2626">—</div>
            <div class="kpi-lbl">Failures</div></div>
    </div>
    <div class="grid">
        <div class="card">
            <h2>Classification Breakdown</h2>
            <div id="breakdown"></div>
        </div>
        <div class="card">
            <h2>Per-Tool Failure Rates</h2>
            <div id="tool-stats"></div>
        </div>
    </div>
    <div class="card" style="margin-bottom:1.5rem">
        <h2>Agent Sessions</h2>
        <div id="sessions"></div>
    </div>
    <div class="card" style="margin-bottom:1.5rem">
        <h2>Recent Verifications</h2>
        <div id="recent"></div>
    </div>
    <div class="card" style="margin-bottom:1.5rem">
        <h2>Tool Executions (Proxy)</h2>
        <div id="executions"></div>
    </div>
</main>
<script>
const COLORS = {
    verified: '#16a34a', embellished: '#ca8a04',
    fabricated: '#dc2626', skipped: '#ef4444', unmonitored: '#6b7280'
};

async function fetchJSON(url) {
    const r = await fetch(url);
    return r.json();
}

function getSinceParam() {
    const secs = parseInt(document.getElementById('timeRange').value);
    if (!secs) return '';
    return '&since=' + (Date.now()/1000 - secs);
}

async function loadAll() {
    try {
        const sp = getSinceParam();
        const [vData, sData, sessData, hoData, exData] = await Promise.all([
            fetchJSON('/api/verifications?limit=200' + sp),
            fetchJSON('/api/stats' + sp.replace('&','?')),
            fetchJSON('/api/sessions' + sp.replace('&','?')),
            fetchJSON('/api/handoffs'),
            fetchJSON('/api/executions?limit=50' + sp),
        ]);
        renderKPIs(vData.verifications);
        renderBreakdown(vData.verifications);
        renderSessions(sessData.sessions, hoData.handoffs);
        renderRecent(vData.verifications);
        renderToolStats(sData.tools);
        renderExecutions(exData.executions);
        document.getElementById('status').className = 'status status-ok';
        document.getElementById('status').textContent = 'connected';
    } catch (e) {
        document.getElementById('status').className = 'status status-err';
        document.getElementById('status').textContent = 'error';
    }
}

function renderKPIs(verifs) {
    const total = verifs.length;
    const counts = {};
    verifs.forEach(v => { counts[v.classification] = (counts[v.classification] || 0) + 1; });
    const failures = (counts.fabricated || 0) + (counts.skipped || 0);
    const rate = total ? failures / total : 0;
    document.getElementById('kpi-total').textContent = total;
    document.getElementById('kpi-rate').textContent = (rate * 100).toFixed(1) + '%';
    document.getElementById('kpi-rate').style.color =
        rate < 0.05 ? '#16a34a' : rate < 0.15 ? '#ca8a04' : '#dc2626';
    document.getElementById('kpi-verified').textContent = counts.verified || 0;
    document.getElementById('kpi-failures').textContent = failures;
}

function renderBreakdown(verifs) {
    const counts = {};
    verifs.forEach(v => { counts[v.classification] = (counts[v.classification] || 0) + 1; });
    const total = verifs.length || 1;
    let html = '';
    ['verified','embellished','fabricated','skipped','unmonitored'].forEach(cls => {
        const n = counts[cls] || 0;
        const pct = (n / total * 100);
        html += '<div class="bar-row">' +
            '<span class="bar-label">' + cls.charAt(0).toUpperCase() + cls.slice(1) + '</span>' +
            '<div class="bar-track"><div class="bar-fill" style="width:' +
            pct + '%;background:' + COLORS[cls] + '"></div></div>' +
            '<span class="bar-count">' + n + ' (' + pct.toFixed(0) + '%)</span></div>';
    });
    document.getElementById('breakdown').innerHTML = html;
}

const SOURCE_BADGES = {
    mcp_proxy: {bg:'#1e3a5f', color:'#60a5fa', label:'MCP Proxy'},
    sdk:       {bg:'#052e16', color:'#4ade80', label:'SDK'},
    demo:      {bg:'#1e293b', color:'#64748b', label:'Demo'},
    test:      {bg:'#3b1f1f', color:'#fca5a5', label:'Test'},
};

function sourceBadge(s) {
    let src = s.source || 'sdk';
    if (src === 'sdk') {
        try { const m = JSON.parse(s.metadata || '{}');
            if (m.adapter === 'mcp') src = 'mcp_proxy';
        } catch(e) {}
    }
    const b = SOURCE_BADGES[src] || SOURCE_BADGES.sdk;
    return '<span style="background:'+b.bg+';color:'+b.color+
        ';padding:0.1rem 0.4rem;border-radius:3px;font-size:0.65rem;'+
        'font-weight:600">'+b.label+'</span>';
}

function renderSessions(sessions, handoffs) {
    const el = document.getElementById('sessions');
    if (!sessions || !sessions.length) {
        el.innerHTML = '<p class="empty">No sessions in this time range.</p>';
        return;
    }
    const byId = {};
    sessions.forEach(s => { byId[s.session_id] = s; });
    const roots = sessions.filter(s => !s.parent_session_id);
    const children = {};
    sessions.forEach(s => {
        if (s.parent_session_id) {
            if (!children[s.parent_session_id])
                children[s.parent_session_id] = [];
            children[s.parent_session_id].push(s);
        }
    });
    let html = '<table><thead><tr><th></th><th>Source</th><th>Agent</th>' +
        '<th>Session</th><th>Started</th></tr></thead><tbody>';
    function addRow(s, depth) {
        const indent = depth * 20;
        const name = s.agent_name || '<span style="color:#475569">—</span>';
        const arrow = depth > 0 ? '└ ' : '';
        const ts = new Date(s.started_at * 1000)
            .toLocaleTimeString();
        html += '<tr><td style="padding-left:' + indent + 'px">' +
            arrow + '</td><td>' + sourceBadge(s) + '</td>' +
            '<td><strong>' + name + '</strong></td>' +
            '<td><code>' + s.session_id.substring(0, 10) +
            '</code></td><td>' + ts + '</td></tr>';
        (children[s.session_id] || []).forEach(
            c => addRow(c, depth + 1));
    }
    roots.forEach(r => addRow(r, 0));
    if (!roots.length) sessions.forEach(s => addRow(s, 0));
    html += '</tbody></table>';
    if (handoffs && handoffs.length) {
        html += '<div style="margin-top:0.75rem;font-size:0.8rem;' +
            'color:#94a3b8"><strong>Handoffs:</strong> ';
        handoffs.forEach(h => {
            const src = (byId[h.source_session_id] || {}).agent_name
                || h.source_session_id.substring(0, 8);
            const tgt = (byId[h.target_session_id] || {}).agent_name
                || h.target_session_id.substring(0, 8);
            const lbl = h.data_summary
                ? ' (' + h.data_summary + ')' : '';
            html += '<span style="margin-right:1rem">' +
                src + ' → ' + tgt + lbl + '</span>';
        });
        html += '</div>';
    }
    el.innerHTML = html;
}

function renderRecent(verifs) {
    if (!verifs.length) {
        document.getElementById('recent').innerHTML = '<p class="empty">No data yet.</p>';
        return;
    }
    let html = '<table><thead><tr><th>Tool</th><th>Classification</th>' +
        '<th>Confidence</th><th>Session</th><th>Actions</th></tr></thead><tbody>';
    verifs.slice(0, 50).forEach(v => {
        const color = COLORS[v.classification] || '#6b7280';
        const isFail = ['fabricated','skipped','embellished'].includes(v.classification);
        let actions = '';
        if (isFail) {
            const fpBtn = '<button class="act-btn" onclick="markFP(' +
                (v.id||0) + ')" title="Mark false positive">FP</button>';
            const isBtn = '<button class="act-btn" onclick="createIssue(' +
                (v.id||0) + ',\\'' + (v.tool_name||'') + '\\',\\'' +
                v.classification + '\\',' + (v.confidence||0).toFixed(2) +
                ')" title="Create GitHub issue">Issue</button>';
            actions = fpBtn + isBtn;
        }
        html += '<tr><td><code>' + (v.tool_name || '') + '</code></td>' +
            '<td><span class="badge" style="background:' + color + '">' +
            v.classification.toUpperCase() + '</span></td>' +
            '<td>' + (v.confidence || 0).toFixed(2) + '</td>' +
            '<td>' + (v.session_id || '').substring(0, 8) + '</td>' +
            '<td>' + actions + '</td></tr>';
    });
    html += '</tbody></table>';
    document.getElementById('recent').innerHTML = html;
}

async function markFP(vid) {
    if (!confirm('Mark verification #' + vid + ' as false positive?')) return;
    const reason = prompt('Reason (optional):') || '';
    try {
        const r = await fetch('/api/false-positive', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({verification_id: vid, reason: reason})
        });
        const d = await r.json();
        if (d.status === 'ok') { alert('Marked as false positive.'); loadAll(); }
        else alert('Error: ' + (d.error || 'unknown'));
    } catch(e) { alert('Failed: ' + e.message); }
}

async function createIssue(vid, tool, cls, conf) {
    try {
        const r = await fetch('/api/issue-url?id=' + vid + '&tool=' + tool +
            '&classification=' + cls + '&confidence=' + conf);
        const d = await r.json();
        if (d.url) window.open(d.url, '_blank');
    } catch(e) { alert('Failed: ' + e.message); }
}

function renderToolStats(tools) {
    const el = document.getElementById('tool-stats');
    if (!tools || !Object.keys(tools).length) {
        el.innerHTML = '<p class="empty">No tool data.</p>';
        return;
    }
    let html = '<table><thead><tr><th>Tool</th><th>Total</th>' +
        '<th>Fail %</th></tr></thead><tbody>';
    const sorted = Object.entries(tools).sort((a, b) =>
        (b[1].failure_rate || 0) - (a[1].failure_rate || 0));
    sorted.forEach(([name, data]) => {
        const rate = data.failure_rate || 0;
        const color = rate < 0.05 ? '#16a34a' : rate < 0.15 ? '#ca8a04' : '#dc2626';
        html += '<tr><td><code>' + name + '</code></td>' +
            '<td>' + (data.total || 0) + '</td>' +
            '<td style="color:' + color + ';font-weight:600">' +
            (rate * 100).toFixed(1) + '%</td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

function renderExecutions(execs) {
    const el = document.getElementById('executions');
    if (!execs || !execs.length) {
        el.innerHTML = '<p class="empty">No proxy executions yet. ' +
            'Set up <code>toolwitness proxy</code> in your MCP config to see tool calls here.</p>';
        return;
    }
    let html = '<table><thead><tr><th>Time</th><th>Tool</th>' +
        '<th>Receipt</th><th>Session</th><th>Status</th></tr></thead><tbody>';
    execs.slice(0, 30).forEach(e => {
        const ts = new Date((e.timestamp || 0) * 1000).toLocaleTimeString();
        const hasError = e.error && e.error !== 'null' && e.error !== '';
        const statusHtml = hasError
            ? '<span class="badge" style="background:#dc2626">ERROR</span>'
            : '<span class="badge" style="background:#16a34a">OK</span>';
        const rid = (e.receipt_id || '—').substring(0, 12);
        const sid = (e.session_id || '').substring(0, 10);
        html += '<tr><td>' + ts + '</td>' +
            '<td><code>' + (e.tool_name || '') + '</code></td>' +
            '<td><code style="font-size:0.7rem">' + rid + '</code></td>' +
            '<td><code style="font-size:0.7rem">' + sid + '</code></td>' +
            '<td>' + statusHtml + '</td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

loadAll();
setInterval(loadAll, 5000);
</script>
</body></html>"""
