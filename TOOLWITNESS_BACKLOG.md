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

**Want to contribute?** See an item you'd like to work on? Open an issue referencing the item ID and we'll coordinate. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Quick reference — resolved detection bugs

All detection bugs have been fixed through structural matching improvements (v0.1.1–v0.1.3). Semantic verification (ST-30) and NER detection (ST-31) remain open as optional stronger layers, not as required fixes.

| ID | Title | Fixed in | Resolution |
|----|-------|----------|------------|
| BUG-01 | Unit conversion classified as FABRICATED | v0.1.1 | `_conversion_close()` with 10 conversion pairs and 1.2% tolerance |
| BUG-02 | List summarization classified as FABRICATED | v0.1.1 | List-item-aware grouping in `structural_match` |
| BUG-03 | Entity substitution not detected (wrong city) | v0.1.1 | `_detect_substitution()` with token-swap and proper-noun heuristics |
| BUG-04 | Comma-formatted numbers split into digits | v0.1.1 | Regex fix in `_extract_numbers()` |
