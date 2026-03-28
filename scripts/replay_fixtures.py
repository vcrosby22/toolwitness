#!/usr/bin/env python3
"""Layer 3: Replay fixture tests — deterministic verification without LLM calls.

Replays saved fabrication fixtures through ToolWitness verification to ensure
consistent detection. Fixtures are JSON files produced by:
  - test_live_fabrication.py --save-fixtures (Layer 2 captures)
  - Manual additions (hand-crafted edge cases)

Fixture format:
    {
        "technique": "B (overloaded context)",
        "tool_output": {"name": "Bob", ...}  OR  {"get_customer": {...}, ...},
        "agent_response": "Bob is ...",
        "expected_classification": "fabricated",
        "confidence": 0.85,
        "evidence": {...}
    }

Usage:
    python scripts/replay_fixtures.py
    python scripts/replay_fixtures.py --fixtures-dir tests/fixtures/replay
    python scripts/replay_fixtures.py --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt

DEFAULT_FIXTURES_DIR = (
    Path(__file__).parent.parent / "tests" / "fixtures" / "replay"
)


def load_fixtures(fixtures_dir: Path) -> list[dict]:
    """Load all JSON fixtures from a directory."""
    if not fixtures_dir.exists():
        print(f"Fixtures directory not found: {fixtures_dir}")
        return []

    fixtures = []
    for path in sorted(fixtures_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            data["_source_file"] = path.name
            fixtures.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  SKIP {path.name}: {e}")

    return fixtures


def replay_single_tool(tool_output: dict, agent_response: str) -> dict:
    """Replay a single-tool fixture."""
    monitor = ExecutionMonitor()
    monitor.register_tool("test_tool", lambda **kw: tool_output)
    monitor.execute_sync("test_tool", {}, lambda **kw: tool_output)

    execution = monitor.get_latest_execution("test_tool")
    receipt_valid = verify_receipt(execution.receipt, monitor.session_key)

    result = classify(
        tool_name="test_tool",
        agent_response=agent_response,
        execution=execution,
        receipt_valid=receipt_valid,
    )
    return {
        "tool_name": "test_tool",
        "classification": result.classification.value,
        "confidence": result.confidence,
    }


def replay_multi_tool(tool_outputs: dict, agent_response: str) -> list[dict]:
    """Replay a multi-tool fixture (one entry per tool)."""
    monitor = ExecutionMonitor()
    results = []

    for name, output in tool_outputs.items():
        monitor.register_tool(name, lambda _out=output, **kw: _out)
        monitor.execute_sync(name, {}, lambda _out=output, **kw: _out)

    for name in tool_outputs:
        execution = monitor.get_latest_execution(name)
        receipt_valid = verify_receipt(
            execution.receipt, monitor.session_key,
        )
        result = classify(
            tool_name=name,
            agent_response=agent_response,
            execution=execution,
            receipt_valid=receipt_valid,
        )
        results.append({
            "tool_name": name,
            "classification": result.classification.value,
            "confidence": result.confidence,
        })

    return results


def replay_fixture(fixture: dict, verbose: bool = False) -> bool:
    """Replay one fixture. Returns True if detection matches expectation."""
    agent_response = fixture["agent_response"]
    tool_output = fixture["tool_output"]
    expected = fixture.get("expected_classification", "fabricated")

    if isinstance(tool_output, dict) and all(
        isinstance(v, dict) for v in tool_output.values()
    ):
        replay_results = replay_multi_tool(tool_output, agent_response)
    else:
        replay_results = [replay_single_tool(tool_output, agent_response)]

    any_match = any(r["classification"] == expected for r in replay_results)

    if verbose:
        for r in replay_results:
            marker = "OK" if r["classification"] == expected else "MISMATCH"
            print(
                f"    {r['tool_name']}: "
                f"{r['classification']} (conf={r['confidence']:.2f}) "
                f"[{marker}]"
            )

    return any_match


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Layer 3: Replay fixture tests",
    )
    parser.add_argument(
        "--fixtures-dir", type=Path, default=DEFAULT_FIXTURES_DIR,
        help=f"Directory containing fixture JSON files "
        f"(default: {DEFAULT_FIXTURES_DIR})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show per-tool classification details",
    )
    args = parser.parse_args()

    fixtures = load_fixtures(args.fixtures_dir)
    if not fixtures:
        print("No fixtures found. Run test_live_fabrication.py "
              "--save-fixtures to generate some.")
        sys.exit(0)

    print(f"Replaying {len(fixtures)} fixtures from {args.fixtures_dir}\n")

    passed = 0
    failed = 0

    for fixture in fixtures:
        source = fixture.get("_source_file", "unknown")
        technique = fixture.get("technique", "unknown")
        expected = fixture.get("expected_classification", "fabricated")

        print(f"  {source} ({technique})...", end=" ", flush=True)

        ok = replay_fixture(fixture, verbose=args.verbose)
        if ok:
            passed += 1
            print("PASS")
        else:
            failed += 1
            print(f"FAIL (expected {expected})")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, "
          f"{len(fixtures)} total")
    print(f"{'='*50}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
