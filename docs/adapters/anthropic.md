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

`wrap()` attaches a `.toolwitness` monitor to your client object. Your existing Anthropic code continues to work unchanged — ToolWitness does not intercept or modify API calls. Instead, you use the monitor to record and verify:

1. **Extract** tool use blocks from Claude's response using `client.toolwitness.extract_tool_calls(response)`
2. **Execute** each tool through the monitor: `client.toolwitness.execute(name, args, tool_fn)`
3. **Verify** Claude's final response: `client.toolwitness.verify("agent said...")`

The monitor records HMAC-signed receipts and compares Claude's claims against actual tool outputs.

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
