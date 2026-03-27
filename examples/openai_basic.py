"""Basic OpenAI integration with ToolWitness.

Demonstrates wrapping an OpenAI client to detect fabricated tool outputs.

Requirements:
    pip install toolwitness[openai]
    export OPENAI_API_KEY=your-key-here
"""

from openai import OpenAI
from toolwitness.adapters.openai import wrap

client = wrap(OpenAI())


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

# Define tools for OpenAI
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
    },
}]

messages = [
    {"role": "user", "content": "What's the weather in Miami?"},
]

# Step 1: Get the model's response (may include tool calls)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
    tools=tools,
)

# Step 2: Extract and execute tool calls with monitoring
tool_calls = client.toolwitness.extract_tool_calls(response)

if tool_calls:
    # Execute tools and get response messages
    tool_messages = client.toolwitness.execute_tool_calls()

    # Build the follow-up messages
    messages.append(response.choices[0].message)
    messages.extend(tool_messages)

    # Step 3: Get the model's final response
    final_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )

    answer = final_response.choices[0].message.content
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
    print(f"Agent says: {response.choices[0].message.content}")
