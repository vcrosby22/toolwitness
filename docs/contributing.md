# Contributing

Thank you for your interest in contributing! ToolWitness is an open-source project and we welcome contributions of all kinds.

## Development setup

```bash
git clone https://github.com/vcrosby22/toolwitness.git
cd toolwitness
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/ -v             # Full test suite
pytest tests/ -v --tb=short  # Compact output
```

## Linting

We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check src/ tests/          # Check for issues
ruff check src/ tests/ --fix    # Auto-fix what's possible
```

## Code style

- Type hints on all public functions
- Docstrings on all public classes and modules
- No unused imports (ruff enforces this)
- Imports sorted per ruff/isort conventions

## Project structure

```
src/toolwitness/
├── core/           # Types, receipt generation, monitor, classifier, detector
├── verification/   # Structural matching, schema checking, chain verification
├── adapters/       # OpenAI, Anthropic, LangChain, MCP, CrewAI
├── alerting/       # Webhook/Slack channels, alert rules and engine
├── storage/        # SQLite backend (abstract base + implementation)
├── reporting/      # HTML report generator, remediation cards, about page
├── dashboard/      # Local web dashboard server
├── proxy/          # Transparent stdio proxy for MCP servers
├── cli/            # Click-based command-line interface
└── config.py       # Configuration system (env > YAML > defaults)
```

## Adding a new framework adapter

1. Create `src/toolwitness/adapters/your_framework.py`
2. Follow the pattern of existing adapters (e.g., `openai.py`):
    - Accept optional `storage` and `session_id` parameters
    - Wire into `ExecutionMonitor` for receipts
    - Implement `verify()` returning `list[VerificationResult]`
3. Add tests in `tests/test_adapters/test_your_framework.py`
4. Add a docs page at `docs/adapters/your_framework.md`
5. Update `mkdocs.yml` navigation
6. Update the README with usage examples

## Adding false-positive corpus entries

If you find a legitimate response that ToolWitness incorrectly flags:

1. Add a case to `tests/test_false_positives.py` in the `FALSE_POSITIVE_CORPUS` list
2. If the case reveals a known structural matching limitation, document it with a comment and include `Classification.FABRICATED` in the acceptable set
3. Run the full test suite to confirm the overall FP rate stays acceptable

## Pull requests

- One feature/fix per PR
- Include tests for new functionality
- Ensure `ruff check` and `pytest` both pass
- Update `CHANGELOG.md` with your changes

## Reporting issues

Use the GitHub issue templates:

- **Bug report** — for incorrect classifications, crashes, or unexpected behavior
- **Feature request** — for new adapters, verification strategies, or UI improvements
