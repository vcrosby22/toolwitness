"""Basic LangChain integration with ToolWitness.

Demonstrates using ToolWitnessMiddleware as a callback handler.

Requirements:
    pip install toolwitness[langchain]
    export OPENAI_API_KEY=your-key-here
"""

from toolwitness.adapters.langchain import ToolWitnessMiddleware

# Initialize middleware
middleware = ToolWitnessMiddleware(
    on_fabrication="log",
    confidence_threshold=0.7,
)

# Simulating what happens during a LangChain agent run:
# 1. Tool starts executing
middleware.on_tool_start(
    serialized={"name": "get_weather"},
    input_str='{"city": "Miami"}',
)

# 2. Tool finishes executing
middleware.on_tool_end(
    output='{"city": "Miami", "temp_f": 72, "condition": "sunny"}'
)

# 3. Agent produces a response
agent_response = "The weather in Miami is 72°F and sunny."

# 4. Verify the response
results = middleware.verify(agent_response)

print(f"Agent says: {agent_response}\n")
for r in results:
    print(
        f"  {r.tool_name}: {r.classification.value} "
        f"(confidence={r.confidence:.2f})"
    )

failures = middleware.get_failures()
if failures:
    print(f"\n  WARNING: {len(failures)} failure(s) detected!")
else:
    print("\n  All tool outputs verified.")

# --- Raising on fabrication ---
print("\n--- Testing fabrication detection ---\n")

strict_middleware = ToolWitnessMiddleware(on_fabrication="raise")

strict_middleware.on_tool_start(
    serialized={"name": "get_weather"},
    input_str='{"city": "Miami"}',
)
strict_middleware.on_tool_end(
    output='{"city": "Miami", "temp_f": 72, "condition": "sunny"}'
)

try:
    strict_middleware.verify("The weather in Miami is 95°F and rainy.")
except Exception as e:
    print(f"  Caught: {e}")
    print(f"  Classification: {e.result.classification.value}")
    print(f"  Confidence: {e.result.confidence:.2f}")
