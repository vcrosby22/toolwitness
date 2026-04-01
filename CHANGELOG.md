# Changelog

All notable changes to ToolWitness will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Docs: **Command quick reference** page (`docs/command-quick-reference.md`) in the site nav under **Commands**, linked from the README — short “what to run when” guide pointing to the full CLI Reference.

## [0.2.0] - 2026-03-29

### Added
- Project scaffold: pyproject.toml, README, CI, issue templates
- Core engine: ExecutionReceipt, Classification, VerificationResult types
- HMAC-SHA256 receipt generation and verification
- ExecutionMonitor with fail-open behavior
- JSON structural matching for response verification
- Schema conformance checking
- Classification engine with confidence scoring
- ToolWitnessDetector orchestrator with decorator API
- SQLite storage backend
- Configuration system (env > YAML > defaults)
- Layer 1 test suite with fabrication fixtures
- OpenAI adapter: `wrap(client)` with tool-call interception
- Anthropic adapter: `wrap(client)` hooking tool_use/tool_result blocks
- LangChain middleware: `ToolWitnessMiddleware` callback handler with log/raise/callback modes
- CrewAI adapter: `@monitored_tool` decorator wrapping any tool function
- MCP adapter: MCPMonitor intercepting tools/call JSON-RPC messages with request_id correlation
- MCP stdio proxy: `toolwitness proxy -- <upstream>` for transparent tool recording
- MCP verification server: `toolwitness serve` exposing `tw_verify_response`, `tw_recent_executions`, `tw_health`, `tw_session_stats`
- Click CLI with 14 commands: `check`, `stats`, `executions`, `watch`, `report`, `digest`, `init`, `dashboard`, `proxy`, `verify`, `serve`, `export`, `purge`, `doctor`
- Multi-turn chain verification: `verify_chain()` checks tool-input chains, detects chain breaks
- Multi-agent support: agent naming, parent sessions, handoff registration, cross-agent verification, dashboard agent tree
- CI gate: `toolwitness check --fail-if "failure_rate > 0.05"` exits 1 on threshold breach
- Alerting system: WebhookChannel, SlackChannel, CallbackChannel, LogChannel with configurable payloads
- Alert rules: AlertRule (per-verification), SessionRule (aggregate), AlertEngine with `from_config()`
- False-positive corpus: 46 test cases (14 MCP-specific) for legitimate response patterns, regression gate
- Self-contained HTML report with session timelines, failure cards, classification breakdown, remediation suggestions
- Local web dashboard: `toolwitness dashboard` on localhost:8321, live-updating SPA with JSON API
- Cursor rule generator: `toolwitness init --cursor-rule`
- Environment doctor: `toolwitness doctor` checks Python, DB, MCP config, dashboard, Cursor rule
- Example scripts for OpenAI, Anthropic, and LangChain integration
- CONTRIBUTING.md with development setup, testing, and contributor guidelines
- MkDocs Material documentation site deployed to GitHub Pages

### Fixed (v0.1.1 — structural matching bugs)
- **BUG-04:** Comma-formatted numbers (e.g. "29,931") were split into separate digits by `_extract_numbers()`. Updated regex to handle comma-thousands groups as single values.
- **BUG-02:** List summarization — when an agent mentions 2 of 5 list items, the 3 unmentioned items were treated as contradictions instead of omissions. Added list-item-aware grouping to `structural_match`.
- **BUG-03:** Entity substitution — "NYC" instead of "Miami" was classified as VERIFIED because the city name was treated as selective omission. Added `_detect_substitution()` with multi-word token-swap and proper-noun heuristics. Classifier now returns FABRICATED when substitution is detected.
- **BUG-01:** Unit conversion — 72°F converted to "about 22°C" was flagged as contradiction. Added `_conversion_close()` with 10 common imperial/metric conversion pairs and 1.2% tolerance.

### Fixed (v0.1.2 — structural matching hardening, 6 fixes)
- **Boolean isinstance ordering:** Python's `bool` subclasses `int`, so booleans hit the numeric branch. Reordered checks; added natural language mappings (`yes`/`available`/`enabled` for True; `not`/`unavailable`/`disabled` for False).
- **Month abbreviation normalization:** `_normalize_months()` expands 3-letter month abbreviations before comparison. Also strips commas for date formatting differences.
- **Negative number fallback:** `abs(value)` fallback when a negative tool value appears unsigned in the response (e.g. "overdrawn by $42.50" for `balance=-42.50`).
- **Context-aware magnitude scaling:** `_magnitude_close()` handles "1.5 million" for 1500000 or "8 KB" for 8192, with unit-label context checking to prevent "4 MB" from matching 4096 (which is 4 KB).
- **Implicit zero pattern matching:** "No errors" for `errors=0` — checks negation patterns near the key name when value is zero.
- **Two-pass numeric omission reclassification:** If all response numbers are claimed by matched tool values, unclaimed numeric tool values are reclassified from contradiction to omission.

### Fixed (v0.1.3 — pattern-based semantic heuristics, 3 fixes)
- **Status code semantic table:** Maps HTTP status codes (200, 404, 500, etc.) and exit codes (0, 1) to natural language equivalents. "The request was successful" now matches `status=200`.
- **Line-prefix counting:** Counts repeated `[FILE]`, `[DIR]` line prefixes and matches derived counts against response numbers. "3 files and 2 folders" now matches counted directory listing lines.
- **Empty output recognition:** When all output values are empty/zero/null and the response uses negation language ("no results", "nothing"), synthesizes a match instead of flagging as fabrication.
