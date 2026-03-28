# CrewAI Adapter

Monitor tool calls in CrewAI agents using the `@monitored_tool` decorator.

## Install

```bash
pip install toolwitness[crewai]
```

## Usage

Replace `@tool` with `@monitored_tool`:

```python
from toolwitness.adapters.crewai import monitored_tool

@monitored_tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return '{"city": "Miami", "temp_f": 72, "condition": "sunny"}'

# Use with CrewAI agents normally
output = get_weather(city="Miami")

# Verify the agent's response
results = get_weather.toolwitness.verify("Miami is 72°F and sunny.")
```

## How it works

The `@monitored_tool` decorator:

1. Wraps the function the same way CrewAI's `@tool` does
2. Before execution: records the tool call and arguments
3. After execution: records the return value and generates an HMAC-signed receipt
4. Attaches a `.toolwitness` attribute for verification access

Your CrewAI agents use the tool exactly as before — the monitoring is transparent.

## With storage persistence

```python
from toolwitness.adapters.crewai import CrewAIMonitor, monitored_tool
from toolwitness.storage.sqlite import SQLiteStorage

monitor = CrewAIMonitor(storage=SQLiteStorage())

@monitored_tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return '{"city": "Miami", "temp_f": 72}'
```

## Options

| Parameter | Type | Default | Description |
|---|---|---|---|
| `storage` | `SQLiteStorage` | `None` | Persist results for CLI and dashboard |
| `session_id` | `str` | auto-generated | Custom session identifier |

## Next

- [Getting Started](../getting-started.md) — basic usage and CLI
- [How It Works](../how-it-works.md) — verification engine details
