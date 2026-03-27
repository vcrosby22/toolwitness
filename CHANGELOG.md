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
