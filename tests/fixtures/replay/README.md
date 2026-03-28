# Replay Fixtures

JSON files in this directory are replayed by `scripts/replay_fixtures.py` (Layer 3).

## How fixtures are created

1. **Automatically** — `scripts/test_live_fabrication.py --save-fixtures` captures detected fabrications from live LLM runs.
2. **Manually** — hand-craft edge cases by creating a JSON file with the format below.

## Format

```json
{
    "technique": "description of what provoked this fabrication",
    "tool_output": {"field": "value"},
    "agent_response": "what the agent actually said",
    "expected_classification": "fabricated",
    "confidence": 0.85,
    "evidence": {},
    "captured_at": "2026-03-28T12:00:00"
}
```

For multi-tool fixtures, `tool_output` is a dict of dicts keyed by tool name.
