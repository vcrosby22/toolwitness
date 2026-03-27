#!/usr/bin/env python3
"""Generate a searchable HTML backlog report from backlog/backlog.yaml.

Usage:
    python scripts/backlog_report.py                    # → backlog/report.html
    python scripts/backlog_report.py -o custom.html     # → custom.html
    python scripts/backlog_report.py --open             # generate and open in browser
"""

from __future__ import annotations

import argparse
import html
import webbrowser
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as err:
    raise SystemExit("PyYAML required: pip install pyyaml") from err


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "backlog" / "backlog.yaml"
DEFAULT_OUTPUT = ROOT / "backlog" / "report.html"

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
PRIORITY_COLORS = {"P0": "#dc2626", "P1": "#ea580c", "P2": "#ca8a04", "P3": "#65a30d"}
STATUS_COLORS = {
    "done": "#16a34a",
    "in_progress": "#2563eb",
    "open": "#6b7280",
    "blocked": "#dc2626",
    "deferred": "#9ca3af",
}
TYPE_ICONS = {"epic": "🏔", "story": "📖", "task": "⚙️", "bug": "🐛"}
TYPE_ORDER = {"epic": 0, "story": 1, "task": 2, "bug": 3}


def load_backlog(path: Path) -> list[dict[str, Any]]:
    with open(path) as f:
        items = yaml.safe_load(f)
    if not isinstance(items, list):
        raise ValueError(f"Expected a list in {path}, got {type(items).__name__}")
    return items


def build_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in items}


def build_tree(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Organize items into a tree (epics → stories → tasks/bugs)."""
    index = build_index(items)
    roots: list[dict[str, Any]] = []
    children_map: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        parent = item.get("parent")
        if parent and parent in index:
            children_map.setdefault(parent, []).append(item)
        else:
            roots.append(item)

    def attach_children(node: dict[str, Any]) -> dict[str, Any]:
        node["_children"] = sorted(
            [attach_children(c) for c in children_map.get(node["id"], [])],
            key=lambda x: (TYPE_ORDER.get(x.get("type", ""), 99), x.get("id", "")),
        )
        return node

    return [attach_children(r) for r in sorted(
        roots, key=lambda x: (TYPE_ORDER.get(x.get("type", ""), 99), x.get("id", ""))
    )]


def esc(text: Any) -> str:
    return html.escape(str(text)) if text else ""


def priority_badge(p: str) -> str:
    color = PRIORITY_COLORS.get(p, "#6b7280")
    return f'<span class="badge" style="background:{color}">{esc(p)}</span>'


def status_badge(s: str) -> str:
    color = STATUS_COLORS.get(s, "#6b7280")
    return f'<span class="badge" style="background:{color}">{esc(s)}</span>'


def type_badge(t: str) -> str:
    icon = TYPE_ICONS.get(t, "❓")
    return f'<span class="type-badge type-{esc(t)}">{icon} {esc(t)}</span>'


def tags_html(tags: list[str] | None) -> str:
    if not tags:
        return ""
    return " ".join(f'<span class="tag">{esc(t)}</span>' for t in tags)


def related_html(related: list[str] | None, index: dict[str, dict[str, Any]]) -> str:
    if not related:
        return ""
    links = []
    for rid in related:
        links.append(
            f'<a href="#{esc(rid)}" class="related-link">{esc(rid)}</a>'
        )
    return '<span class="related">Related: ' + ", ".join(links) + "</span>"


def render_item(item: dict[str, Any], index: dict[str, dict[str, Any]], depth: int = 0) -> str:
    item_id = item.get("id", "")
    item_type = item.get("type", "unknown")
    title = item.get("title", "Untitled")
    desc = item.get("description", "")
    priority = item.get("priority", "")
    status = item.get("status", "")
    milestone = item.get("milestone", "")
    tags = item.get("tags", [])
    related = item.get("related", [])
    children = item.get("_children", [])
    discovered = item.get("discovered", "")
    evidence = item.get("evidence", "")
    fixture = item.get("fixture", "")

    search_text = " ".join(
        str(v) for v in [item_id, title, desc, priority, status, milestone, item_type]
        + (tags or []) + (related or [])
    ).lower()

    parts = [f'<div class="item depth-{depth} type-{esc(item_type)}" '
             f'id="{esc(item_id)}" data-search="{esc(search_text)}" '
             f'data-priority="{esc(priority)}" data-status="{esc(status)}" '
             f'data-type="{esc(item_type)}" data-milestone="{esc(milestone)}">']
    parts.append('<div class="item-header">')
    parts.append(f'<span class="item-id">{esc(item_id)}</span>')
    parts.append(type_badge(item_type))
    parts.append(f'<span class="item-title">{esc(title)}</span>')
    if priority:
        parts.append(priority_badge(priority))
    if status:
        parts.append(status_badge(status))
    if milestone:
        parts.append(f'<span class="milestone">{esc(milestone)}</span>')
    parts.append("</div>")

    if desc:
        parts.append(f'<div class="item-desc">{esc(desc.strip())}</div>')

    if discovered or evidence or fixture:
        parts.append('<div class="bug-detail">')
        if discovered:
            parts.append(
                f'<div class="detail-row">'
                f"<strong>Discovered:</strong> {esc(discovered)}</div>"
            )
        if fixture:
            parts.append(
                f'<div class="detail-row">'
                f"<strong>Fixture:</strong> "
                f"<code>{esc(fixture)}</code></div>"
            )
        if evidence:
            parts.append(
                f'<div class="detail-row">'
                f"<strong>Evidence:</strong> "
                f"{esc(evidence.strip())}</div>"
            )
        parts.append("</div>")

    meta_parts = []
    if tags:
        meta_parts.append(tags_html(tags))
    if related:
        meta_parts.append(related_html(related, index))
    if meta_parts:
        parts.append(f'<div class="item-meta">{" ".join(meta_parts)}</div>')

    if children:
        parts.append('<div class="children">')
        for child in children:
            parts.append(render_item(child, index, depth + 1))
        parts.append("</div>")

    parts.append("</div>")
    return "\n".join(parts)


def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts


def generate_html(items: list[dict[str, Any]]) -> str:
    index = build_index(items)
    tree = build_tree(items)

    type_counts = count_by(items, "type")
    status_counts = count_by(items, "status")
    bug_count = type_counts.get("bug", 0)
    open_count = sum(1 for i in items if i.get("status") in ("open", "in_progress"))
    done_count = status_counts.get("done", 0)

    items_html = "\n".join(render_item(node, index) for node in tree)

    all_milestones = sorted(set(i.get("milestone", "") for i in items if i.get("milestone")))
    milestone_options = "\n".join(
        f'<option value="{esc(m)}">{esc(m)}</option>' for m in all_milestones
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ToolWitness Backlog</title>
<style>
  :root {{
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --text-muted: #94a3b8; --accent: #3b82f6;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
    padding: 2rem; max-width: 1200px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.25rem; }}
  .subtitle {{ color: var(--text-muted); margin-bottom: 1.5rem; font-size: 0.9rem; }}
  .stats {{
    display: flex; gap: 1.5rem; margin-bottom: 1.5rem; flex-wrap: wrap;
  }}
  .stat {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 0.75rem 1.25rem; min-width: 120px;
  }}
  .stat-value {{ font-size: 1.5rem; font-weight: 700; }}
  .stat-label {{ font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; }}
  .controls {{
    display: flex; gap: 0.75rem; margin-bottom: 1.5rem; flex-wrap: wrap; align-items: center;
  }}
  .controls input, .controls select {{
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: 0.5rem 0.75rem; border-radius: 6px;
    font-size: 0.85rem;
  }}
  .controls input {{ flex: 1; min-width: 200px; }}
  .controls select {{ min-width: 130px; }}
  .item {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 0.5rem;
    transition: border-color 0.2s;
  }}
  .item:hover {{ border-color: var(--accent); }}
  .item.hidden {{ display: none; }}
  .item-header {{
    display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
  }}
  .item-id {{
    font-family: 'SF Mono', Menlo, monospace; font-size: 0.8rem;
    color: var(--accent); font-weight: 600; min-width: 60px;
  }}
  .item-title {{ font-weight: 600; flex: 1; min-width: 200px; }}
  .badge {{
    font-size: 0.7rem; font-weight: 600; padding: 0.15rem 0.5rem;
    border-radius: 99px; color: white; text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  .type-badge {{
    font-size: 0.75rem; padding: 0.1rem 0.4rem; border-radius: 4px;
    background: var(--border);
  }}
  .milestone {{
    font-size: 0.75rem; color: var(--text-muted);
    border: 1px solid var(--border); padding: 0.1rem 0.4rem;
    border-radius: 4px;
  }}
  .item-desc {{
    color: var(--text-muted); font-size: 0.85rem; margin-top: 0.5rem;
    max-width: 80ch;
  }}
  .bug-detail {{
    margin-top: 0.5rem; padding: 0.5rem 0.75rem; background: #1a1a2e;
    border-left: 3px solid #dc2626; border-radius: 4px; font-size: 0.8rem;
  }}
  .bug-detail .detail-row {{ margin-bottom: 0.25rem; }}
  .bug-detail code {{
    background: var(--border); padding: 0.1rem 0.3rem; border-radius: 3px;
    font-size: 0.8rem;
  }}
  .item-meta {{
    margin-top: 0.5rem; display: flex; gap: 0.5rem; flex-wrap: wrap;
    align-items: center;
  }}
  .tag {{
    font-size: 0.7rem; background: var(--border); padding: 0.1rem 0.4rem;
    border-radius: 3px; color: var(--text-muted);
  }}
  .related {{ font-size: 0.75rem; color: var(--text-muted); }}
  .related-link {{ color: var(--accent); text-decoration: none; }}
  .related-link:hover {{ text-decoration: underline; }}
  .children {{ margin-left: 1.5rem; margin-top: 0.5rem; }}
  .depth-1 {{ border-left: 3px solid #334155; }}
  .depth-2 {{ border-left: 3px solid #475569; }}
  .type-bug {{ border-left: 3px solid #dc2626 !important; }}
  .legend {{
    display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap;
    font-size: 0.8rem; color: var(--text-muted);
  }}
  .legend span {{ display: flex; align-items: center; gap: 0.25rem; }}
  footer {{
    margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border);
    color: var(--text-muted); font-size: 0.75rem;
  }}
  @media (max-width: 768px) {{
    body {{ padding: 1rem; }}
    .children {{ margin-left: 0.75rem; }}
    .stats {{ gap: 0.75rem; }}
  }}
</style>
</head>
<body>

<h1>ToolWitness Backlog</h1>
<p class="subtitle">Product backlog — searchable, filterable, with hierarchy and relationships</p>

<div class="stats">
  <div class="stat">
    <div class="stat-value">{len(items)}</div>
    <div class="stat-label">Total Items</div></div>
  <div class="stat">
    <div class="stat-value">{open_count}</div>
    <div class="stat-label">Open / Active</div></div>
  <div class="stat">
    <div class="stat-value">{done_count}</div>
    <div class="stat-label">Done</div></div>
  <div class="stat">
    <div class="stat-value">{bug_count}</div>
    <div class="stat-label">Bugs</div></div>
  <div class="stat">
    <div class="stat-value">{type_counts.get('epic', 0)}</div>
    <div class="stat-label">Epics</div></div>
  <div class="stat">
    <div class="stat-value">{type_counts.get('story', 0)}</div>
    <div class="stat-label">Stories</div></div>
</div>

<div class="controls">
  <input type="text" id="search" placeholder="Search by ID, title, tag, milestone..." autofocus>
  <select id="filterType">
    <option value="">All Types</option>
    <option value="epic">🏔 Epic</option>
    <option value="story">📖 Story</option>
    <option value="task">⚙️ Task</option>
    <option value="bug">🐛 Bug</option>
  </select>
  <select id="filterStatus">
    <option value="">All Statuses</option>
    <option value="open">Open</option>
    <option value="in_progress">In Progress</option>
    <option value="done">Done</option>
    <option value="blocked">Blocked</option>
    <option value="deferred">Deferred</option>
  </select>
  <select id="filterPriority">
    <option value="">All Priorities</option>
    <option value="P0">P0 — Critical</option>
    <option value="P1">P1 — High</option>
    <option value="P2">P2 — Medium</option>
    <option value="P3">P3 — Low</option>
  </select>
  <select id="filterMilestone">
    <option value="">All Milestones</option>
    {milestone_options}
  </select>
</div>

<div class="legend">
  <span>🏔 Epic</span> <span>📖 Story</span> <span>⚙️ Task</span> <span>🐛 Bug</span>
  <span>|</span>
  <span>{priority_badge("P0")} Critical</span>
  <span>{priority_badge("P1")} High</span>
  <span>{priority_badge("P2")} Medium</span>
  <span>{priority_badge("P3")} Low</span>
</div>

<div id="backlog">
{items_html}
</div>

<footer>
  Generated by <code>scripts/backlog_report.py</code> from <code>backlog/backlog.yaml</code>
</footer>

<script>
const search = document.getElementById('search');
const filterType = document.getElementById('filterType');
const filterStatus = document.getElementById('filterStatus');
const filterPriority = document.getElementById('filterPriority');
const filterMilestone = document.getElementById('filterMilestone');
const items = document.querySelectorAll('.item');

function applyFilters() {{
  const q = search.value.toLowerCase();
  const type = filterType.value;
  const status = filterStatus.value;
  const priority = filterPriority.value;
  const milestone = filterMilestone.value;

  items.forEach(item => {{
    const s = item.dataset.search || '';
    const matchSearch = !q || s.includes(q);
    const matchType = !type || item.dataset.type === type;
    const matchStatus = !status || item.dataset.status === status;
    const matchPriority = !priority || item.dataset.priority === priority;
    const matchMilestone = !milestone || item.dataset.milestone === milestone;

    if (matchSearch && matchType && matchStatus && matchPriority && matchMilestone) {{
      item.classList.remove('hidden');
    }} else {{
      item.classList.add('hidden');
    }}
  }});
}}

search.addEventListener('input', applyFilters);
filterType.addEventListener('change', applyFilters);
filterStatus.addEventListener('change', applyFilters);
filterPriority.addEventListener('change', applyFilters);
filterMilestone.addEventListener('change', applyFilters);

document.querySelectorAll('.related-link').forEach(link => {{
  link.addEventListener('click', e => {{
    e.preventDefault();
    const target = document.querySelector(link.getAttribute('href'));
    if (target) {{
      items.forEach(i => i.classList.remove('hidden'));
      search.value = '';
      filterType.value = '';
      filterStatus.value = '';
      filterPriority.value = '';
      filterMilestone.value = '';
      target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      target.style.borderColor = '#f59e0b';
      setTimeout(() => target.style.borderColor = '', 2000);
    }}
  }});
}});
</script>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate ToolWitness backlog HTML report")
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT, help="Input YAML file")
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Output HTML file",
    )
    parser.add_argument("--open", action="store_true", help="Open in browser after generating")
    args = parser.parse_args()

    items = load_backlog(args.input)
    html_content = generate_html(items)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_content)
    print(f"Generated: {args.output} ({len(items)} items)")

    if args.open:
        webbrowser.open(f"file://{args.output.resolve()}")


if __name__ == "__main__":
    main()
