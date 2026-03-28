# ToolWitness

**Detect when AI agents skip tools or fabricate outputs.**

ToolWitness sits between your AI agent and its tools. It watches tool calls happen, records
cryptographic receipts, then checks whether the agent's response faithfully represents what the
tools actually returned.

> *Stop trusting your agent — get a witness.*

**[Documentation](https://vcrosby22.github.io/toolwitness/)** | **[Getting Started](https://vcrosby22.github.io/toolwitness/getting-started/)** | **[How It Works](https://vcrosby22.github.io/toolwitness/how-it-works/)**

## What ToolWitness detects

| Classification | What happened | Example |
|---------------|---------------|---------|
| **VERIFIED** | Agent accurately reported tool output | Tool returned 72°F, agent said "72 degrees" |
| **EMBELLISHED** | Agent added claims beyond tool output | Tool returned temp only, agent added humidity |
| **FABRICATED** | Agent's response contradicts tool output | Tool returned 72°F, agent said 85°F |
| **SKIPPED** | Agent claimed a tool ran but it never did | No execution receipt exists |
| **UNMONITORED** | Tool wasn't wrapped by ToolWitness | Outside monitoring scope |

## What ToolWitness sees vs. doesn't see

| ToolWitness sees | ToolWitness does NOT see |
|-----------------|------------------------|
| Tool function name + arguments | Your source code |
| Tool return value (to compare against agent claims) | Other files in your project |
| Agent's text response (to verify against tool output) | Environment variables or secrets (unless passed as tool args) |
| Timing of tool calls | Network traffic outside tool calls |
| Nothing else | Your prompts, system messages, or conversation history |

ToolWitness is a **passive observer at the tool boundary**. It does not scan your codebase, read
your files, or phone home. All data stays local by default. Telemetry is off unless you
explicitly enable it.

## Quick start

```bash
pip install toolwitness
```

With framework extras:

```bash
pip install toolwitness[openai]      # OpenAI adapter
pip install toolwitness[anthropic]   # Anthropic adapter
pip install toolwitness[langchain]   # LangChain middleware
pip install toolwitness[mcp]         # MCP proxy adapter
pip install toolwitness[crewai]      # CrewAI @monitored_tool
```

### Basic usage

```python
from toolwitness import ToolWitnessDetector
from toolwitness.storage.sqlite import SQLiteStorage

# Persist to SQLite so the CLI and dashboard can read data
detector = ToolWitnessDetector(storage=SQLiteStorage())

@detector.tool()
def get_weather(city: str) -> dict:
    return {"city": city, "temp_f": 72, "condition": "sunny"}

# Execute a tool (generates a cryptographic receipt)
result = detector.execute_sync("get_weather", {"city": "Miami"})

# Verify the agent's response against recorded receipts
verification = detector.verify_sync("The weather in Miami is 72°F and sunny.")
print(verification)
# [VerificationResult(tool_name='get_weather', classification=VERIFIED, confidence=0.95)]
```

### With OpenAI

```python
from openai import OpenAI
from toolwitness.adapters.openai import wrap
from toolwitness.storage.sqlite import SQLiteStorage

client = wrap(OpenAI(), storage=SQLiteStorage())
# Use client normally — ToolWitness intercepts tool calls transparently
```

### With Anthropic

```python
from anthropic import Anthropic
from toolwitness.adapters.anthropic import wrap
from toolwitness.storage.sqlite import SQLiteStorage

client = wrap(Anthropic(), storage=SQLiteStorage())
```

### With LangChain

```python
from toolwitness.adapters.langchain import ToolWitnessMiddleware
from toolwitness.storage.sqlite import SQLiteStorage

middleware = ToolWitnessMiddleware(
    on_fabrication="raise",  # or "log" or "callback"
    storage=SQLiteStorage(),
)
# Add middleware as a callback to your LangChain agent
```

### With MCP (Model Context Protocol)

```python
from toolwitness.adapters.mcp import MCPMonitor

monitor = MCPMonitor()
# Intercept tool calls from JSON-RPC messages
monitor.on_tool_call(params={"name": "get_weather", "arguments": {"city": "Miami"}})
monitor.on_tool_result(tool_name="get_weather", result={"temp_f": 72})
results = monitor.verify("Miami is 72°F.")
```

### With CrewAI

```python
from toolwitness.adapters.crewai import monitored_tool

@monitored_tool
def get_weather(city: str) -> str:
    return '{"city": "Miami", "temp_f": 72}'

# Use with CrewAI agents normally — calls are monitored
output = get_weather(city="Miami")
results = get_weather.toolwitness.verify("Miami is 72°F.")
```

## How it works

1. **Wrap** your tools or client with ToolWitness
2. **Execute** — ToolWitness records each tool call with an HMAC-signed receipt (the model cannot forge these)
3. **Verify** — after the agent responds, ToolWitness compares claims against actual tool outputs
4. **Classify** — each tool interaction gets a classification (VERIFIED → SKIPPED) with a confidence score

## Alerting

Configure alerts for failures via webhook, Slack, or custom callbacks:

```python
from toolwitness.alerting.rules import AlertEngine, AlertRule
from toolwitness.alerting.channels import SlackChannel
from toolwitness.core.types import Classification

engine = AlertEngine()
engine.add_rule(AlertRule(
    classifications={Classification.FABRICATED, Classification.SKIPPED},
    min_confidence=0.8,
    channels=[SlackChannel("https://hooks.slack.com/services/...")],
))
```

Or via `toolwitness.yaml`:

```yaml
alerting:
  slack_webhook_url: "https://hooks.slack.com/services/..."
  rules:
    - classifications: [fabricated, skipped]
      min_confidence: 0.8
```

## Configuration

```bash
toolwitness init  # Creates toolwitness.yaml with commented defaults
```

Config precedence: environment variables (`TOOLWITNESS_*`) > YAML (`toolwitness.yaml`) > code defaults.

## CLI

```bash
toolwitness check --last 5                              # Recent verification results
toolwitness check --fail-if "failure_rate > 0.05"       # CI gate — exits 1 on breach
toolwitness stats                                       # Per-tool failure rates
toolwitness watch                                       # Real-time detection log
toolwitness report --format html                        # Self-contained HTML report
toolwitness dashboard                                   # Local web dashboard
toolwitness export --format json                        # Structured data export
toolwitness init                                        # Create config file
```

### CI gate

Add to your CI pipeline to fail builds when agents misbehave:

```bash
toolwitness check --fail-if "failure_rate > 0.05"
toolwitness check --fail-if "fabricated_count > 0"
```

## Multi-agent support

ToolWitness monitors multi-agent systems — not just individual agents. When agents hand off data to
each other, fabrication compounds: one corrupted value in Agent A becomes the foundation for Agent B's
entire response. ToolWitness tracks these handoffs and catches corruption at the boundary.

```python
from toolwitness import ToolWitnessDetector
from toolwitness.storage.sqlite import SQLiteStorage

storage = SQLiteStorage()

# Create linked agents
orchestrator = ToolWitnessDetector(storage=storage, agent_name="orchestrator")
researcher = ToolWitnessDetector(
    storage=storage,
    agent_name="researcher",
    parent_session_id=orchestrator.session_id,
)

# Orchestrator calls tools, then hands off to researcher
orchestrator.register_handoff(researcher, data="customer record")

# Verify researcher's response against original tool outputs
local, handoff_results = researcher.verify_with_handoffs(
    "Customer is John Smith..."
)
```

Three capabilities:

- **Session hierarchy** — agents declare names and parents, forming a visible tree
- **Handoff tracking** — data transfers recorded with originating tool receipt IDs
- **Cross-agent verification** — receiving agent's claims checked against the *original* tool output

All five adapters (OpenAI, Anthropic, LangChain, MCP, CrewAI) support `agent_name` and
`parent_session_id` parameters.

See the full guide at [Multi-Agent Support →](https://vcrosby22.github.io/toolwitness/multi-agent/)

## Dashboard

```bash
toolwitness dashboard  # Starts at http://localhost:8321
```

The local dashboard reads from SQLite and auto-refreshes every 5 seconds. Pages:

- **Overview** — KPI cards, classification breakdown, recent failures
- **Full Report** — session timelines, failure detail cards with evidence, remediation suggestions, per-tool stats
- **Agent tree** — multi-agent sessions with hierarchy, handoff arrows, and corruption chain evidence

## Design principles

- **Fail-open**: ToolWitness errors never block your tool calls. If something breaks internally, the tool runs normally and the result is classified as `UNMONITORED`.
- **Local-first**: All data stored in local SQLite. No cloud, no accounts, no telemetry by default.
- **Zero required dependencies**: Core engine uses only Python stdlib. Framework adapters are optional extras.
- **Async-first**: Native async with thin sync wrappers for compatibility.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and code style.

## License

Apache 2.0 — see [LICENSE](LICENSE).
