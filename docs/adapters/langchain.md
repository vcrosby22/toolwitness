# LangChain Adapter

Monitor tool calls in LangChain agents via middleware callback.

## Install

```bash
pip install toolwitness[langchain]
```

## Usage

```python
from toolwitness.adapters.langchain import ToolWitnessMiddleware
from toolwitness.storage.sqlite import SQLiteStorage

middleware = ToolWitnessMiddleware(
    on_fabrication="raise",  # or "log" or "callback"
    storage=SQLiteStorage(),
)

# Add as a callback to your LangChain agent
agent = create_agent(llm, tools, callbacks=[middleware])
```

## Fabrication handling modes

| Mode | Behavior |
|---|---|
| `"log"` | Log the failure, continue execution |
| `"raise"` | Raise a `FabricationDetectedError` |
| `"callback"` | Call a custom function with the verification result |

### Custom callback

```python
def on_failure(result):
    print(f"Failure detected: {result.tool_name} — {result.classification}")

middleware = ToolWitnessMiddleware(
    on_fabrication="callback",
    fabrication_callback=on_failure,
    storage=SQLiteStorage(),
)
```

## Options

| Parameter | Type | Default | Description |
|---|---|---|---|
| `on_fabrication` | `str` | `"log"` | How to handle detected fabrications |
| `fabrication_callback` | `callable` | `None` | Custom handler (when mode is `"callback"`) |
| `storage` | `SQLiteStorage` | `None` | Persist results for CLI and dashboard |
| `session_id` | `str` | auto-generated | Custom session identifier |

## How it integrates

The middleware hooks into LangChain's callback system:

- `on_tool_start` — records the tool call and generates a receipt
- `on_tool_end` — records the tool output
- `on_llm_end` — verifies the model's response against recorded outputs

This means verification happens automatically as part of the agent's execution loop.

## Next

- [Getting Started](../getting-started.md) — basic usage and CLI
- [How It Works](../how-it-works.md) — verification engine details
