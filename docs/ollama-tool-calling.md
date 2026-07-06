# Ollama tool-calling schema (`/api/chat`)

Verified against the official Ollama API docs. This is the spine of `agent.py`
and the `memory.py` message format. Code to this shape, not to memory.

## Request — defining tools

```json
{
  "model": "qwen2.5",
  "messages": [{"role": "user", "content": "..."}],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get the weather in a given city",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string", "description": "The city"}
          },
          "required": ["city"]
        }
      }
    }
  ],
  "stream": false
}
```

## Response — model requests a tool

```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      {"function": {"name": "get_weather", "arguments": {"city": "Tokyo"}}}
    ]
  },
  "done": true
}
```

## Passing a tool result back

Append a message with role `tool`, then call `/api/chat` again:

```json
{"role": "tool", "content": "11 degrees celsius", "tool_name": "get_weather"}
```

## Notes that drive our design

- **No call `id`.** Unlike OpenAI, Ollama tool calls carry no id. Results are
  associated by **`tool_name`** (and by order within the turn). `memory.py`
  keeps each `tool_calls` assistant message adjacent to its `tool` result(s).
- **`arguments` is already a JSON object**, not a stringified JSON — no
  `json.loads()` needed on the args.
- **`content` is empty** on a tool-call turn; the real answer arrives on a
  later turn once results are fed back.
- **Loop termination:** keep looping while the response contains `tool_calls`;
  stop when it doesn't. Guard with `agent.MAX_ITERATIONS`.
- Start **non-streaming** (`stream: false`); add streaming later.
