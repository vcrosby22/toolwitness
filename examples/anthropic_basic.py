"""Basic Anthropic integration with ToolWitness.

Demonstrates wrapping an Anthropic client to detect fabricated tool outputs.

Requirements:
    pip install toolwitness[anthropic]
    export ANTHROPIC_API_KEY=your-key-here
"""

from anthropic import Anthropic
from toolwitness.adapters.anthropic import wrap

client = wrap(Anthropic())


def get_weather(city: str) -> dict:
    """Simulated weather tool (replace with your real API)."""
    return {
        "city": city,
        "temp_f": 72,
        "condition": "sunny",
        "humidity": 65,
    }


# Register the tool with ToolWitness
client.toolwitness.register_tool("get_weather", get_weather)

# Define tools for Anthropic
tools = [{
    "name": "get_weather",
    "description": "Get current weather for a city",
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
        },
        "required": ["city"],
    },
}]

messages = [
    {"role": "user", "content": "What's the weather in Miami?"},
]

# Step 1: Get the model's response (may include tool_use blocks)
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=messages,
    tools=tools,
)

# Step 2: Check for tool_use blocks
tool_uses = client.toolwitness.extract_tool_uses(response)

if tool_uses:
    # Execute tools and get tool_result blocks
    tool_results = client.toolwitness.execute_tool_uses()

    # Build the follow-up messages
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": tool_results})

    # Step 3: Get the model's final response
    final_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=messages,
        tools=tools,
    )

    # Extract text from the response
    answer = ""
    for block in final_response.content:
        if hasattr(block, "text"):
            answer += block.text

    print(f"Agent says: {answer}\n")

    # Step 4: Verify the response against tool outputs
    results = client.toolwitness.verify(answer)
    for r in results:
        print(
            f"  {r.tool_name}: {r.classification.value} "
            f"(confidence={r.confidence:.2f})"
        )

    failures = client.toolwitness.get_failures(answer)
    if failures:
        print(f"\n  WARNING: {len(failures)} tool(s) may have "
              "fabricated or embellished outputs!")
    else:
        print("\n  All tool outputs verified.")
else:
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
    print(f"Agent says: {text}")
