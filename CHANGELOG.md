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
