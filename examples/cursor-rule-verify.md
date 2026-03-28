# ToolWitness Verification Rule for Cursor

Drop this rule into your project's `.cursor/rules/` folder (or adapt it
for Claude Desktop / other MCP hosts) to enable automatic response
verification.

## How it works

1. The **ToolWitness proxy** wraps your MCP servers and records every
   tool call with a cryptographic receipt (Conversation 1).
2. The **ToolWitness MCP server** exposes a `tw_verify_response` tool
   that the agent calls with its response text (Conversation 2).
3. ToolWitness compares both conversations — if the agent misrepresented
   what a tool returned, it gets flagged as **FABRICATED** or
   **EMBELLISHED**.

## Setup

Your `mcp.json` needs two entries:

```json
{
  "mcpServers": {
    "filesystem-monitored": {
      "command": "/path/to/toolwitness",
      "args": ["proxy", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/your/path"]
    },
    "toolwitness": {
      "command": "/path/to/toolwitness",
      "args": ["serve"]
    }
  }
}
```

Find your full path with: `which toolwitness`

## Example rule file

Save this as `.cursor/rules/toolwitness-verify.mdc`:

```
# ToolWitness response verification

After using any tool from the filesystem-monitored MCP server (read_file,
list_directory, get_file_info, etc.), verify your response by calling
tw_verify_response from the toolwitness MCP server.

Pass your complete response text to tw_verify_response. If the result
shows FABRICATED or EMBELLISHED, review the evidence and correct your
response before presenting it to the user.

This ensures your responses faithfully represent what tools actually
returned.
```

## What the agent sees

When the agent calls `tw_verify_response`, it gets back a result like:

```json
{
  "executions_checked": 2,
  "has_failures": false,
  "verifications": [
    {
      "tool_name": "read_file",
      "classification": "verified",
      "confidence": 0.99
    },
    {
      "tool_name": "get_file_info",
      "classification": "verified",
      "confidence": 0.99
    }
  ]
}
```

If fabrication is detected:

```json
{
  "executions_checked": 1,
  "has_failures": true,
  "verifications": [
    {
      "tool_name": "get_file_info",
      "classification": "fabricated",
      "confidence": 0.80,
      "evidence": {
        "match_ratio": 0.0,
        "mismatched_count": 2,
        "mismatched_details": [
          {"key": "size_bytes", "expected": 6169}
        ]
      }
    }
  ]
}
```
