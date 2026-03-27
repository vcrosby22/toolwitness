# Changelog

All notable changes to ToolWitness will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Click CLI: `check`, `stats`, `watch`, `report`, `init`, `export` commands
- Example scripts for OpenAI, Anthropic, and LangChain integration
- Structured YAML backlog with searchable HTML report generator
- Storage persistence wiring: detector and all adapters auto-persist executions and verifications to SQLite when storage is provided
- End-to-end integration tests covering full flow through SQLite
- Alerting system: WebhookChannel, SlackChannel, CallbackChannel, LogChannel with configurable payloads (summary vs full)
- Alert rules: AlertRule (per-verification conditions), SessionRule (aggregate failure rate), AlertEngine orchestrator with `from_config()`
- MCP adapter: MCPMonitor intercepting tools/call JSON-RPC messages with request_id correlation
- CrewAI adapter: `@monitored_tool` decorator wrapping any tool function
- Multi-turn chain verification: `verify_chain()` checks tool-input chains, detects chain breaks
- CI gate: `toolwitness check --fail-if "failure_rate > 0.05"` exits 1 on threshold breach
- False-positive corpus: 15 test cases for legitimate response patterns, regression gate
- Self-contained HTML report: session timelines, failure detail cards with evidence, classification breakdown, per-tool stats, remediation suggestions
- Remediation suggestion cards: static fix tables per classification (SKIPPED, FABRICATED, EMBELLISHED) with code examples
- Local web dashboard: `toolwitness dashboard` on localhost:8321, live-updating SPA with JSON API
- `toolwitness dashboard` CLI command with `--host` and `--port` options
- CONTRIBUTING.md with development setup, testing, and contributor guidelines
- README expanded: per-adapter quick-start examples (OpenAI, Anthropic, LangChain, MCP, CrewAI), alerting config, CI gate, dashboard docs
