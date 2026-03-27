"""Self-contained HTML report generator.

Produces a single-file HTML report with:
- Session summary (KPI cards)
- Classification breakdown (donut chart via CSS)
- Session timeline with color-coded nodes
- Failure detail cards with actual vs claimed
- Remediation suggestion cards
- Per-tool failure rates
"""

from __future__ import annotations

import json
import time
from typing import Any

from toolwitness.reporting.remediation import render_remediation_html

COLORS = {
    "verified": "#16a34a",
    "embellished": "#ca8a04",
    "fabricated": "#dc2626",
    "skipped": "#ef4444",
    "unmonitored": "#6b7280",
}

ICONS = {
    "verified": "&#10003;",
    "embellished": "&#9888;",
    "fabricated": "&#10007;",
    "skipped": "&#8856;",
    "unmonitored": "?",
}


def generate_html_report(
    verifications: list[dict[str, Any]],
    tool_stats: dict[str, Any],
    sessions: list[dict[str, Any]] | None = None,
    executions: list[dict[str, Any]] | None = None,
) -> str:
    total = len(verifications)
    if total == 0:
        return _empty_report()

    counts = _classification_counts(verifications)
    failures = counts.get("fabricated", 0) + counts.get("skipped", 0)
    rate = failures / total

    by_session = _group_by_session(verifications)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ToolWitness Report</title>
{_css()}
</head><body>
<header>
    <h1>ToolWitness Report</h1>
    <p class="subtitle">Generated {time.strftime("%Y-%m-%d %H:%M")}</p>
</header>
<nav>
    <a href="#summary">Summary</a>
    <a href="#timeline">Sessions</a>
    <a href="#failures">Failures</a>
    <a href="#tools">Tool Stats</a>
    <a href="/about">About</a>
</nav>

<section id="summary">
{_kpi_cards(total, failures, rate, counts)}
{_classification_bars(counts, total)}
</section>

<section id="timeline">
    <h2>Session Timelines</h2>
{_session_timelines(by_session)}
</section>

<section id="failures">
    <h2>Failure Details</h2>
{_failure_cards(verifications)}
</section>

<section id="tools">
    <h2>Per-Tool Failure Rates</h2>
{_tool_stats_table(tool_stats)}
</section>

<footer>
    <p>ToolWitness &mdash; Stop trusting your agent, get a witness.</p>
</footer>
{_js()}
</body></html>"""


def _classification_counts(
    verifications: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in verifications:
        cls = v.get("classification", "unmonitored")
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def _group_by_session(
    verifications: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for v in verifications:
        sid = v.get("session_id", "unknown")[:12]
        groups.setdefault(sid, []).append(v)
    return groups


def _kpi_cards(
    total: int, failures: int, rate: float, counts: dict[str, int],
) -> str:
    rate_color = "#16a34a" if rate < 0.05 else "#ca8a04" if rate < 0.15 else "#dc2626"
    verified = counts.get("verified", 0)
    return f"""
    <div class="kpis">
        <div class="kpi">
            <div class="kpi-val">{total}</div>
            <div class="kpi-lbl">Verifications</div>
        </div>
        <div class="kpi">
            <div class="kpi-val" style="color:{rate_color}">{rate:.1%}</div>
            <div class="kpi-lbl">Failure Rate</div>
        </div>
        <div class="kpi">
            <div class="kpi-val" style="color:#16a34a">{verified}</div>
            <div class="kpi-lbl">Verified</div>
        </div>
        <div class="kpi">
            <div class="kpi-val" style="color:#dc2626">{failures}</div>
            <div class="kpi-lbl">Failures</div>
        </div>
    </div>"""


def _classification_bars(counts: dict[str, int], total: int) -> str:
    bars = ""
    for cls in ("verified", "embellished", "fabricated", "skipped", "unmonitored"):
        n = counts.get(cls, 0)
        pct = (n / total * 100) if total else 0
        color = COLORS.get(cls, "#6b7280")
        bars += f"""
        <div class="bar-row">
            <span class="bar-label">{cls.title()}</span>
            <div class="bar-track">
                <div class="bar-fill" style="width:{pct}%;background:{color}"></div>
            </div>
            <span class="bar-count">{n} ({pct:.0f}%)</span>
        </div>"""
    return f'<div class="classification-chart">{bars}</div>'


def _session_timelines(
    by_session: dict[str, list[dict[str, Any]]],
) -> str:
    html = ""
    for sid, items in list(by_session.items())[:20]:
        n = len(items)
        n_fail = sum(
            1 for v in items
            if v["classification"] in ("fabricated", "skipped")
        )
        nodes = ""
        for v in items:
            cls = v["classification"]
            color = COLORS.get(cls, "#6b7280")
            icon = ICONS.get(cls, "?")
            tool = v.get("tool_name", "?")
            conf = v.get("confidence", 0)
            nodes += (
                f'<div class="timeline-node" style="border-color:{color}" '
                f'title="{tool}: {cls.upper()} ({conf:.2f})">'
                f'<span class="node-icon" style="color:{color}">{icon}</span>'
                f'<span class="node-tool">{tool}</span>'
                f'</div>'
                f'<div class="timeline-arrow">&rarr;</div>'
            )
        if nodes.endswith('<div class="timeline-arrow">&rarr;</div>'):
            nodes = nodes[: -len('<div class="timeline-arrow">&rarr;</div>')]

        status = "all verified" if n_fail == 0 else f"{n_fail} failure{'s' if n_fail > 1 else ''}"
        status_color = "#16a34a" if n_fail == 0 else "#dc2626"
        html += f"""
        <div class="session-block">
            <div class="session-header">
                <span class="session-id">Session {sid}</span>
                <span style="color:{status_color}">{n} calls &mdash; {status}</span>
            </div>
            <div class="timeline">{nodes}</div>
        </div>"""
    return html


def _failure_cards(verifications: list[dict[str, Any]]) -> str:
    failures = [
        v for v in verifications
        if v["classification"] in ("fabricated", "skipped", "embellished")
    ]
    if not failures:
        return '<p class="empty">No failures detected.</p>'

    cards = ""
    for v in failures[:30]:
        cls = v["classification"]
        color = COLORS.get(cls, "#6b7280")
        icon = ICONS.get(cls, "?")
        tool = v.get("tool_name", "unknown")
        conf = v.get("confidence", 0)
        sid = v.get("session_id", "")[:8]

        evidence_html = ""
        evidence = v.get("evidence")
        if evidence:
            if isinstance(evidence, str):
                import contextlib
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    evidence = json.loads(evidence)
            if isinstance(evidence, dict):
                mismatched = evidence.get("mismatched", [])
                extra = evidence.get("extra_claims", [])
                matched = evidence.get("matched", [])

                if matched:
                    evidence_html += '<div class="evidence-section">'
                    evidence_html += (
                        '<span class="ev-label"'
                        ' style="color:#16a34a">Matched:</span> '
                    )
                    for m in matched[:5]:
                        evidence_html += (
                            f'<span class="ev-chip ev-match">'
                            f'{m.get("key", "?")}</span> '
                        )
                    evidence_html += '</div>'

                if mismatched:
                    evidence_html += '<div class="evidence-section">'
                    evidence_html += (
                        '<span class="ev-label"'
                        ' style="color:#dc2626">Mismatched:</span> '
                    )
                    for m in mismatched[:5]:
                        evidence_html += (
                            f'<span class="ev-chip ev-mismatch">'
                            f'{m.get("key", "?")}: expected {m.get("expected", "?")}'
                            f'</span> '
                        )
                    evidence_html += '</div>'

                if extra:
                    evidence_html += '<div class="evidence-section">'
                    evidence_html += (
                        '<span class="ev-label"'
                        ' style="color:#ca8a04">Extra claims:</span> '
                    )
                    for e in extra[:5]:
                        evidence_html += (
                            f'<span class="ev-chip ev-extra">{e}</span> '
                        )
                    evidence_html += '</div>'

        remediation_html = render_remediation_html(cls)

        cards += f"""
        <div class="failure-card">
            <div class="failure-header">
                <span class="failure-icon" style="color:{color}">{icon}</span>
                <span class="failure-tool">{tool}</span>
                <span class="failure-badge" style="background:{color}">{cls.upper()}</span>
                <span class="failure-conf">confidence: {conf:.2f}</span>
                <span class="failure-session">session: {sid}</span>
            </div>
            {evidence_html}
            {remediation_html}
        </div>"""

    return cards


def _tool_stats_table(tool_stats: dict[str, Any]) -> str:
    if not tool_stats:
        return '<p class="empty">No tool data available.</p>'

    rows = ""
    for tool_name, data in sorted(
        tool_stats.items(),
        key=lambda x: x[1].get("failure_rate", 0),
        reverse=True,
    ):
        rate = data.get("failure_rate", 0)
        total = data.get("total", 0)
        rate_color = "#16a34a" if rate < 0.05 else "#ca8a04" if rate < 0.15 else "#dc2626"

        bar_pct = min(rate * 100 * 5, 100)
        rows += f"""
        <tr>
            <td><code>{tool_name}</code></td>
            <td>{total}</td>
            <td style="color:{rate_color};font-weight:600">{rate:.1%}</td>
            <td>
                <div class="mini-bar">
                    <div class="mini-fill" style="width:{bar_pct}%;background:{rate_color}"></div>
                </div>
            </td>
            <td>{data.get('verified', 0)}</td>
            <td>{data.get('fabricated', 0)}</td>
            <td>{data.get('skipped', 0)}</td>
        </tr>"""

    return f"""
    <table>
        <thead><tr>
            <th>Tool</th><th>Total</th><th>Fail %</th><th></th>
            <th>Verified</th><th>Fabricated</th><th>Skipped</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def _empty_report() -> str:
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>ToolWitness Report</title></head>
<body style="font-family:system-ui;background:#0f172a;color:#e2e8f0;
padding:2rem;text-align:center">
<h1>ToolWitness Report</h1>
<p>No verification data found. Run your agent with ToolWitness first.</p>
</body></html>"""


def _css() -> str:
    return """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: #0f172a; color: #e2e8f0; line-height: 1.5; }
header { padding: 2rem 2rem 1rem; max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.75rem; }
h2 { font-size: 1.25rem; margin-bottom: 1rem; color: #f1f5f9; }
.subtitle { color: #64748b; font-size: 0.85rem; }
nav { position: sticky; top: 0; z-index: 10; background: #1e293b;
  border-bottom: 1px solid #334155; padding: 0.5rem 2rem;
  display: flex; gap: 1.5rem; max-width: 1100px; margin: 0 auto; }
nav a { color: #94a3b8; text-decoration: none; font-size: 0.85rem;
  font-weight: 500; }
nav a:hover { color: #f1f5f9; }
section { max-width: 1100px; margin: 0 auto; padding: 1.5rem 2rem; }
footer { max-width: 1100px; margin: 2rem auto; padding: 1.5rem 2rem;
  border-top: 1px solid #334155; color: #475569; font-size: 0.8rem;
  text-align: center; }

.kpis { display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 1rem; margin-bottom: 1.5rem; }
.kpi { background: #1e293b; padding: 1.25rem; border-radius: 10px;
  border: 1px solid #334155; text-align: center; }
.kpi-val { font-size: 1.75rem; font-weight: 700; }
.kpi-lbl { font-size: 0.75rem; color: #64748b; text-transform: uppercase;
  letter-spacing: 0.05em; margin-top: 0.25rem; }

.classification-chart { background: #1e293b; padding: 1.25rem;
  border-radius: 10px; border: 1px solid #334155; }
.bar-row { display: flex; align-items: center; gap: 0.75rem;
  margin-bottom: 0.5rem; }
.bar-label { width: 100px; font-size: 0.8rem; color: #94a3b8;
  text-align: right; }
.bar-track { flex: 1; height: 20px; background: #0f172a;
  border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.bar-count { width: 90px; font-size: 0.8rem; color: #94a3b8; }

.session-block { background: #1e293b; padding: 1rem 1.25rem;
  border-radius: 10px; border: 1px solid #334155; margin-bottom: 0.75rem; }
.session-header { display: flex; justify-content: space-between;
  margin-bottom: 0.75rem; font-size: 0.85rem; }
.session-id { font-weight: 600; }
.timeline { display: flex; align-items: center; gap: 0.25rem;
  overflow-x: auto; padding-bottom: 0.25rem; }
.timeline-node { padding: 0.4rem 0.6rem; border: 2px solid;
  border-radius: 8px; background: #0f172a; display: flex;
  flex-direction: column; align-items: center; min-width: 70px;
  cursor: default; }
.node-icon { font-size: 1rem; }
.node-tool { font-size: 0.65rem; color: #94a3b8; margin-top: 0.15rem;
  max-width: 80px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.timeline-arrow { color: #475569; font-size: 0.9rem; }

.failure-card { background: #1e293b; padding: 1.25rem;
  border-radius: 10px; border: 1px solid #334155; margin-bottom: 1rem; }
.failure-header { display: flex; align-items: center; gap: 0.75rem;
  flex-wrap: wrap; margin-bottom: 0.75rem; }
.failure-icon { font-size: 1.25rem; }
.failure-tool { font-weight: 600; font-family: monospace; }
.failure-badge { padding: 0.15rem 0.5rem; border-radius: 4px;
  font-size: 0.7rem; font-weight: 700; color: white; }
.failure-conf, .failure-session { font-size: 0.8rem; color: #64748b; }
.evidence-section { margin-bottom: 0.5rem; font-size: 0.85rem; }
.ev-label { font-weight: 600; }
.ev-chip { display: inline-block; padding: 0.15rem 0.5rem;
  border-radius: 4px; font-size: 0.75rem; margin: 0.1rem; }
.ev-match { background: #052e16; color: #4ade80; }
.ev-mismatch { background: #450a0a; color: #fca5a5; }
.ev-extra { background: #422006; color: #fcd34d; }

table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.6rem 0.75rem;
  border-bottom: 1px solid #1e293b; }
th { color: #64748b; font-size: 0.75rem; text-transform: uppercase;
  letter-spacing: 0.05em; background: #1e293b; position: sticky; top: 42px; }
td code { color: #93c5fd; }
.mini-bar { width: 60px; height: 6px; background: #0f172a;
  border-radius: 3px; overflow: hidden; }
.mini-fill { height: 100%; border-radius: 3px; }
.empty { color: #64748b; padding: 2rem; text-align: center; }

@media (max-width: 700px) {
  .kpis { grid-template-columns: repeat(2, 1fr); }
  nav { flex-wrap: wrap; gap: 0.75rem; }
}
</style>"""


def _js() -> str:
    return """<script>
document.querySelectorAll('nav a').forEach(a => {
    a.addEventListener('click', e => {
        e.preventDefault();
        const target = document.querySelector(a.getAttribute('href'));
        if (target) target.scrollIntoView({ behavior: 'smooth' });
    });
});
</script>"""
