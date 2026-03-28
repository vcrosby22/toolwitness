# Anthropic Adapter

Monitor tool calls made through the Anthropic Python client.

## Install

```bash
pip install toolwitness[anthropic]
```

## Usage

```python
from anthropic import Anthropic
from toolwitness.adapters.anthropic import wrap
from toolwitness.storage.sqlite import SQLiteStorage

# Wrap your Anthropic client
client = wrap(Anthropic(), storage=SQLiteStorage())

# Use the client exactly as before
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "What's the weather in Miami?"}],
    tools=[{
        "name": "get_weather",
        "description": "Get current weather",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        },
    }],
)
```

## What happens

1. When Claude requests a tool use, ToolWitness records the call with an HMAC-signed receipt
2. When you provide the tool result, ToolWitness records the actual output
3. After Claude's final response, verify its claims against recorded tool outputs

## Options

| Parameter | Type | Default | Description |
|---|---|---|---|
| `storage` | `SQLiteStorage` | `None` | Persist results for CLI and dashboard |
| `session_id` | `str` | auto-generated | Custom session identifier |

## Verification

```python
results = client.toolwitness.verify("The weather in Miami is 72°F and sunny.")
for r in results:
    print(f"{r.tool_name}: {r.classification.name} ({r.confidence:.2f})")
```

## Next

- [Getting Started](../getting-started.md) — basic usage and CLI
- [How It Works](../how-it-works.md) — verification engine details
