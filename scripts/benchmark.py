#!/usr/bin/env python3
"""Layer 5: Performance benchmarks for ToolWitness.

Measures latency of core operations against documented budgets:
  - Receipt generation:    < 1 ms
  - Structural matching:   < 5 ms
  - Full verification:     < 200 ms
  - Classification:        < 5 ms

Usage:
    python scripts/benchmark.py
    python scripts/benchmark.py --iterations 1000
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from toolwitness import ToolWitnessDetector
from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import generate_receipt, generate_session_key, verify_receipt
from toolwitness.verification.structural import structural_match

BUDGETS_MS = {
    "receipt_generate": 1.0,
    "receipt_verify": 1.0,
    "structural_match": 5.0,
    "classify": 5.0,
    "full_verify_sync": 200.0,
}

SAMPLE_TOOL_OUTPUT = {
    "city": "Miami",
    "temp_f": 72,
    "condition": "sunny",
    "humidity": 65,
    "wind_mph": 12,
    "forecast": [
        {"day": "Monday", "high": 78, "low": 68},
        {"day": "Tuesday", "high": 80, "low": 70},
        {"day": "Wednesday", "high": 75, "low": 65},
    ],
}

SAMPLE_AGENT_RESPONSE = (
    "The current weather in Miami is 72°F and sunny with 65% humidity "
    "and winds at 12 mph. The forecast shows highs of 78°F on Monday, "
    "80°F on Tuesday, and 75°F on Wednesday."
)

FABRICATED_RESPONSE = (
    "The current weather in Miami is 85°F and partly cloudy with 40% humidity. "
    "Expect rain on Tuesday with a high of 90°F."
)


def bench(fn, iterations: int) -> list[float]:
    """Run a function N times and return latencies in ms."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    return times


def run_benchmarks(iterations: int) -> dict:
    session_key = generate_session_key()
    results = {}

    receipt = generate_receipt(
        tool_name="get_weather",
        args={"city": "Miami"},
        output=SAMPLE_TOOL_OUTPUT,
        session_key=session_key,
    )

    # Receipt generation
    times = bench(
        lambda: generate_receipt(
            tool_name="get_weather",
            args={"city": "Miami"},
            output=SAMPLE_TOOL_OUTPUT,
            session_key=session_key,
        ),
        iterations,
    )
    results["receipt_generate"] = times

    # Receipt verification
    times = bench(
        lambda: verify_receipt(receipt, session_key),
        iterations,
    )
    results["receipt_verify"] = times

    # Structural matching
    times = bench(
        lambda: structural_match(
            tool_output=SAMPLE_TOOL_OUTPUT,
            agent_response=SAMPLE_AGENT_RESPONSE,
        ),
        iterations,
    )
    results["structural_match"] = times

    # Classification
    monitor = ExecutionMonitor()
    monitor.register_tool(
        "get_weather", lambda **kw: SAMPLE_TOOL_OUTPUT,
    )
    monitor.execute_sync(
        "get_weather", {"city": "Miami"},
        lambda **kw: SAMPLE_TOOL_OUTPUT,
    )
    execution = monitor.get_latest_execution("get_weather")
    receipt_valid = verify_receipt(execution.receipt, monitor.session_key)

    times = bench(
        lambda: classify(
            tool_name="get_weather",
            agent_response=SAMPLE_AGENT_RESPONSE,
            execution=execution,
            receipt_valid=receipt_valid,
        ),
        iterations,
    )
    results["classify"] = times

    # Full verify_sync (detector end-to-end)
    detector = ToolWitnessDetector()

    @detector.tool()
    def get_weather(city: str) -> dict:
        return SAMPLE_TOOL_OUTPUT

    detector.execute_sync("get_weather", {"city": "Miami"})

    times = bench(
        lambda: detector.verify_sync(SAMPLE_AGENT_RESPONSE),
        iterations,
    )
    results["full_verify_sync"] = times

    return results


def print_report(results: dict) -> bool:
    """Print results and return True if all budgets pass."""
    all_pass = True

    print(f"\n{'='*70}")
    print("TOOLWITNESS PERFORMANCE BENCHMARK")
    print(f"{'='*70}")
    print(
        f"{'Operation':<25} {'p50 ms':>8} {'p95 ms':>8} "
        f"{'p99 ms':>8} {'Budget':>8} {'Status':>8}"
    )
    print("-" * 70)

    for name, times in results.items():
        budget = BUDGETS_MS[name]
        p50 = statistics.median(times)
        p95 = sorted(times)[int(len(times) * 0.95)]
        p99 = sorted(times)[int(len(times) * 0.99)]
        passed = p95 <= budget
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False

        print(
            f"  {name:<23} {p50:>7.3f} {p95:>7.3f} "
            f"{p99:>7.3f} {budget:>7.1f} {status:>8}"
        )

    print("-" * 70)
    print(f"  Overall: {'ALL PASS' if all_pass else 'FAILURES DETECTED'}")
    print(f"{'='*70}")

    return all_pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Layer 5: ToolWitness performance benchmarks",
    )
    parser.add_argument(
        "--iterations", type=int, default=500,
        help="Iterations per benchmark (default: 500)",
    )
    args = parser.parse_args()

    print(f"Running {args.iterations} iterations per benchmark...")
    results = run_benchmarks(args.iterations)
    all_pass = print_report(results)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
