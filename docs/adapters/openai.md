 I di# OpenAI Adapter

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

1. When the model requests a tool call, ToolWitness records the call and generates an HMAC-signed receipt
2. When you provide the tool result back to the model, ToolWitness records the actual output
3. After the model's final response, you can verify its claims against the recorded tool outputs

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
