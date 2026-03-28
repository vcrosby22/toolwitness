# Getting Started

## Install

```bash
pip install toolwitness
```

With framework adapters:

=== "OpenAI"
    ```bash
    pip install toolwitness[openai]
    ```

=== "Anthropic"
    ```bash
    pip install toolwitness[anthropic]
    ```

=== "LangChain"
    ```bash
    pip install toolwitness[langchain]
    ```

=== "MCP"
    ```bash
    pip install toolwitness[mcp]
    ```

=== "CrewAI"
    ```bash
    pip install toolwitness[crewai]
    ```

=== "All adapters"
    ```bash
    pip install toolwitness[all]
    ```

---

## Basic Usage (3 Lines)

```python
from toolwitness import ToolWitnessDetector
from toolwitness.storage.sqlite import SQLiteStorage

# Create detector with SQLite persistence
detector = ToolWitnessDetector(storage=SQLiteStorage())

# Register a tool
@detector.tool()
def get_weather(city: str) -> dict:
    return {"city": city, "temp_f": 72, "condition": "sunny"}

# Execute and verify
result = detector.execute_sync("get_weather", {"city": "Miami"})
verification = detector.verify_sync("The weather in Miami is 72°F and sunny.")
print(verification)
# [VerificationResult(tool_name='get_weather', classification=VERIFIED, confidence=0.95)]
```

That's it. The tool call is recorded with a cryptographic receipt, the agent's response is compared against the actual output, and you get a classification with a confidence score.

---

## Per-Adapter Quick Start

??? example "OpenAI"

    ```python
    from openai import OpenAI
    from toolwitness.adapters.openai import wrap
    from toolwitness.storage.sqlite import SQLiteStorage

    client = wrap(OpenAI(), storage=SQLiteStorage())
    # wrap() attaches a .toolwitness monitor to your client.
    # Use client.toolwitness.extract_tool_calls(), execute_tool_calls(),
    # and verify() in your agent loop to monitor tool faithfulness.
    ```

    See [OpenAI adapter docs →](adapters/openai.md)

??? example "Anthropic"

    ```python
    from anthropic import Anthropic
    from toolwitness.adapters.anthropic import wrap
    from toolwitness.storage.sqlite import SQLiteStorage

    client = wrap(Anthropic(), storage=SQLiteStorage())
    ```

    See [Anthropic adapter docs →](adapters/anthropic.md)

??? example "LangChain"

    ```python
    from toolwitness.adapters.langchain import ToolWitnessMiddleware
    from toolwitness.storage.sqlite import SQLiteStorage

    middleware = ToolWitnessMiddleware(
        on_fabrication="raise",  # or "log" or "callback"
        storage=SQLiteStorage(),
    )
    # Add middleware as a callback to your LangChain agent
    ```

    See [LangChain adapter docs →](adapters/langchain.md)

??? example "MCP (Model Context Protocol)"

    ```python
    from toolwitness.adapters.mcp import MCPMonitor

    monitor = MCPMonitor()
    monitor.on_tool_call(params={
        "name": "get_weather",
        "arguments": {"city": "Miami"},
    })
    monitor.on_tool_result(tool_name="get_weather", result={"temp_f": 72})
    results = monitor.verify("Miami is 72°F.")
    ```

    See [MCP adapter docs →](adapters/mcp.md)

??? example "CrewAI"

    ```python
    from toolwitness.adapters.crewai import monitored_tool

    @monitored_tool
    def get_weather(city: str) -> str:
        return '{"city": "Miami", "temp_f": 72}'

    output = get_weather(city="Miami")
    results = get_weather.toolwitness.verify("Miami is 72°F.")
    ```

    See [CrewAI adapter docs →](adapters/crewai.md)

---

## CLI

After running your agent with ToolWitness, inspect results from the command line:

```bash
toolwitness check --last 5                         # Recent results
toolwitness stats                                  # Per-tool failure rates
toolwitness watch                                  # Live tail
toolwitness report --format html                   # HTML report
toolwitness dashboard                              # Local web dashboard
```

!!! info "The dashboard runs on your machine"
    `toolwitness dashboard` starts a local HTTP server at **http://localhost:8321** — same pattern as TensorBoard or `mkdocs serve`. No cloud, no account, no data leaves your machine. Open the URL in your browser and you'll see live results from your local SQLite database. Ctrl+C stops the server.

See [CLI Reference →](cli.md) for all commands and options.

---

## CI Gate

Add ToolWitness to your CI pipeline to fail builds when agents misbehave:

```bash
toolwitness check --fail-if "failure_rate > 0.05"
toolwitness check --fail-if "fabricated_count > 0"
```

Exit code 1 when the condition is met — drop it into any CI system.

---

## Configuration

Generate a config file with commented defaults:

```bash
toolwitness init
```

This creates `toolwitness.yaml`. Config precedence:

1. Environment variables (`TOOLWITNESS_*`) — highest priority
2. YAML file (`toolwitness.yaml`)
3. Code defaults — lowest priority

---

## Multi-Agent Quick Start

If you're running multiple agents that pass data to each other, ToolWitness can track handoffs and catch cross-agent fabrication:

```python
from toolwitness import ToolWitnessDetector
from toolwitness.storage.sqlite import SQLiteStorage

storage = SQLiteStorage()

orchestrator = ToolWitnessDetector(
    storage=storage, agent_name="orchestrator",
)
researcher = ToolWitnessDetector(
    storage=storage,
    agent_name="researcher",
    parent_session_id=orchestrator.session_id,
)

# After orchestrator calls tools, record the handoff
orchestrator.register_handoff(researcher, data="customer record")

# Verify the researcher's response against original tool outputs
local, handoff_results = researcher.verify_with_handoffs(
    "Customer is John Smith..."
)
```

See the full guide at [Multi-Agent Support →](multi-agent.md).

---

## What's Next

- [How It Works](how-it-works.md) — understand the verification engine
- [Multi-Agent Support](multi-agent.md) — monitor agent chains and swarms
- [Privacy & Security](privacy.md) — what ToolWitness sees and doesn't see
- [Adapter docs](adapters/openai.md) — detailed per-framework guides
