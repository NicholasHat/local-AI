# Skills

A skill is a capability the model can call as a tool, defined as files on
disk instead of Python code changes. Discovered fresh on every chat turn —
edit a skill's files and the change is live on the next message, no restart.

## Layout

```
skills/<name>/
  skill.yaml   # name, description, parameters (JSON-schema properties), required
  prompt.md    # instruction skill — mutually exclusive with run.py
  run.py       # code skill — mutually exclusive with prompt.md
```

`<name>` must match `name:` in `skill.yaml`, and be lowercase
letters/digits/hyphens only (e.g. `summarize-for-email`).

**Instruction skill** (`prompt.md`): a template with `{argument_name}`
placeholders. When called, the placeholders are filled in with the call's
arguments and the result is returned to the model as the tool's output — the
model then follows those instructions in its next response. No code runs.

**Code skill** (`run.py`): defines `def run(**args) -> str`. When called,
the module is imported fresh and `run()` is invoked with the call's
arguments; its return value becomes the tool result.

See `summarize-for-email/` and `word-count/` for one example of each.

## Security model

This is a local, single-user app. Code skills execute in-process with **no
sandbox** — a `run.py` can do anything the rest of the app can do. That's an
acceptable trade-off only because skill *code* is always written by a human,
directly, through the API or by editing files on disk.

The model has its own `create_skill` tool so it can build itself instruction
skills when you ask it to ("make yourself a skill that..."). That tool can
**only** write a `prompt.md` — it has no way to supply a `run.py`, by
construction, not just by convention. This matters because the model's
tool-calling loop can be influenced by content it reads (an uploaded
document, a search result) — if that content ever tried to manipulate the
model into "creating a skill," the worst case is a weird instruction added
to the same conversation the content already came from, not arbitrary code
silently becoming executable. Writing a code skill always requires a human
acting directly, never something the model can trigger from a chat message.
