# OpenAI Adapter

Monitor tool calls made through the OpenAI Python client.

## Install

```bash
pip install toolwitness[openai]
```

## Usage

```python
from openai import OpenAI
from toolwitness.adapters.openai import wrap
from toolwitness.storage.sqlite import SQLiteStorage

# Wrap your OpenAI client — all tool calls are now monitored
client = wrap(OpenAI(), storage=SQLiteStorage())

# Use the client exactly as before
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "What's the weather in Miami?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    }],
)
```

## What happens

`wrap()` attaches a `.toolwitness` monitor to your client object. Your existing OpenAI code continues to work unchanged — ToolWitness does not intercept or modify API calls. Instead, you use the monitor to record and verify:

1. **Extract** tool calls from the model's response using `client.toolwitness.extract_tool_calls(response)`
2. **Execute** each tool through the monitor: `client.toolwitness.execute(name, args, tool_fn)`
3. **Verify** the model's final response: `client.toolwitness.verify("agent said...")`

The monitor records HMAC-signed receipts and compares the agent's claims against actual tool outputs.

## Options

| Parameter | Type | Default | Description |
|---|---|---|---|
| `storage` | `SQLiteStorage` | `None` | Persist results to SQLite for CLI and dashboard access |
| `session_id` | `str` | auto-generated | Custom session identifier for grouping verifications |

## Verification

After the conversation completes:

```python
results = client.toolwitness.verify("The weather in Miami is 72°F and sunny.")
for r in results:
    print(f"{r.tool_name}: {r.classification.name} ({r.confidence:.2f})")
```

## Next

- [Getting Started](../getting-started.md) — basic usage and CLI
- [How It Works](../how-it-works.md) — verification engine details
