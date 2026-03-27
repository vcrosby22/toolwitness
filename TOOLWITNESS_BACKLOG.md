# ToolWitness Backlog

**Canonical source:** [`backlog/backlog.yaml`](backlog/backlog.yaml)

Generate the searchable HTML report:

```bash
python scripts/backlog_report.py          # → backlog/report.html
python scripts/backlog_report.py --open   # generate and open in browser
```

## Hierarchy

- **Epic** — high-level feature area (e.g. "Advanced Verification")
- **Story** — deliverable piece of value within an epic
- **Task** — implementation step within a story
- **Bug** — defect linked to an epic or story

Items have `parent` (hierarchy) and `related` (cross-references) fields.
Priority scale: P0 (critical) → P3 (low).

## Quick reference — known detection limitations (bugs)

| ID | Title | Parent | Fix via |
|----|-------|--------|---------|
| BUG-01 | Unit conversion classified as FABRICATED | EP-05 | ST-30 (semantic verification) |
| BUG-02 | List summarization classified as FABRICATED | EP-05 | ST-30, ST-34 |
| BUG-03 | Entity substitution not detected (wrong city) | EP-05 | ST-31 (NER detection) |
