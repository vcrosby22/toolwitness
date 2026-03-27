# ToolWitness

**Detect when AI agents skip tools or fabricate outputs.**

ToolWitness sits between your AI agent and its tools. It watches tool calls happen, records
cryptographic receipts, then checks whether the agent's response faithfully represents what the
tools actually returned.

> *Stop trusting your agent — get a witness.*

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
```

### Basic usage

```python
from toolwitness import ToolWitnessDetector

detector = ToolWitnessDetector()

@detector.tool()
def get_weather(city: str) -> dict:
    return {"city": city, "temp_f": 72, "condition": "sunny"}

# Execute a tool (generates a cryptographic receipt)
result = detector.execute("get_weather", {"city": "Miami"})

# Later, verify the agent's response against recorded receipts
verification = detector.verify("The weather in Miami is 72°F and sunny.")
print(verification)
# VerificationResult(tool_name='get_weather', classification=VERIFIED, confidence=0.95, ...)
```

### With OpenAI

```python
from openai import OpenAI
from toolwitness.adapters.openai import wrap

client = wrap(OpenAI())  # 1 line to add monitoring
# Use client normally — ToolWitness intercepts tool calls transparently
```

## How it works

1. **Wrap** your tools or client with ToolWitness
2. **Execute** — ToolWitness records each tool call with an HMAC-signed receipt (the model cannot forge these)
3. **Verify** — after the agent responds, ToolWitness compares claims against actual tool outputs
4. **Classify** — each tool interaction gets a classification (VERIFIED → SKIPPED) with a confidence score

## Configuration

```bash
toolwitness init  # Creates toolwitness.yaml with commented defaults
```

Config precedence: environment variables (`TOOLWITNESS_*`) > YAML (`toolwitness.yaml`) > code defaults.

## CLI

```bash
toolwitness check --last 5    # Show recent verification results
toolwitness stats             # Per-tool failure rates
toolwitness watch             # Real-time detection log
toolwitness report --format html  # Static HTML report
```

## Design principles

- **Fail-open**: ToolWitness errors never block your tool calls. If something breaks internally, the tool runs normally and the result is classified as `UNMONITORED`.
- **Local-first**: All data stored in local SQLite. No cloud, no accounts, no telemetry by default.
- **Zero required dependencies**: Core engine uses only Python stdlib. Framework adapters are optional extras.
- **Async-first**: Native async with thin sync wrappers for compatibility.

## License

Apache 2.0 — see [LICENSE](LICENSE).
