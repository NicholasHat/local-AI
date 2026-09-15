"""Unit tests for workflows.py — definitions, rendering, and the DAG runner
against a mocked agent.run (no live model)."""

import textwrap
import time

import pytest

import agent
import jobstore
import providers
import settings
import spaces
import workflows

MINIMAL = textwrap.dedent(
    """
    description: two steps
    inputs:
      - {name: topic, type: string}
    steps:
      - id: first
        prompt: "First about {inputs.topic}"
      - id: second
        depends_on: [first]
        prompt: "Second sees: {steps.first.output}"
    """
)

FANOUT = textwrap.dedent(
    """
    description: council-like
    inputs:
      - {name: question, type: string}
      - {name: models, type: models}
    output: merge
    steps:
      - id: voice
        each: models
        model: "{item}"
        tools: [read_space]
        prompt: "Q: {inputs.question} (space {space_id}, run {run_id})"
      - id: merge
        role: judge
        depends_on: [voice]
        prompt: "Merge:\\n{steps.voice.output}"
    """
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(workflows, "WORKFLOWS_DIR", tmp_path / "workflows")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setenv("OLLAMA_MODEL", "default-model")
    # No live Ollama in unit tests: treat every model as tool-capable unless
    # a test says otherwise.
    monkeypatch.setattr(providers, "tool_capable_models", lambda: None)


class _FakeAgent:
    """Stands in for agent.run: records every call, returns a scripted
    output (default: echoes the prompt), and can raise or go blank."""

    def __init__(self, outputs=None, blank_first=False, fail_step=None):
        self.calls = []
        self.outputs = outputs or {}
        self.blank_first = blank_first
        self.fail_step = fail_step
        self._blanked = set()

    def __call__(
        self,
        user_message,
        conversation,
        model=None,
        *,
        tools=None,
        options=None,
        context=None,
    ):
        self.calls.append(
            {
                "prompt": user_message,
                "model": model,
                "tools": list(tools or []),
                "options": options,
                "agent_name": context.agent_name,
                "doc_sources": context.doc_sources,
                "system": conversation.messages[0]["content"],
            }
        )
        name = context.agent_name
        if self.fail_step and name.startswith(self.fail_step):
            raise RuntimeError("boom")
        if self.blank_first and name not in self._blanked:
            self._blanked.add(name)
            return ""
        conversation.add_assistant({"role": "assistant", "content": "x"})
        step_id = name.split(" @ ")[0]
        return self.outputs.get(step_id, f"out({user_message})")


def _install(monkeypatch, fake):
    monkeypatch.setattr(agent, "run", fake)
    return fake


# --- Definitions ---------------------------------------------------------------


def test_parse_minimal_defaults():
    wf = workflows.parse("demo", MINIMAL)
    assert wf.name == "demo"
    assert wf.output == "second"  # defaults to the last step
    assert wf.steps[0].role == "chat"
    assert wf.steps[0].tools == []
    assert wf.inputs[0].required is True


@pytest.mark.parametrize(
    ("yaml_text", "fragment"),
    [
        ("steps: []", "non-empty"),
        ("steps:\n  - id: a\n    role: wizard\n    prompt: p", "unknown role"),
        ("steps:\n  - id: a\n    tools: [write_file]\n    prompt: p", "unknown tool"),
        ("steps:\n  - id: a\n    depends_on: [zzz]\n    prompt: p", "unknown step"),
        (
            "steps:\n  - id: a\n    depends_on: [b]\n    prompt: p\n"
            "  - id: b\n    depends_on: [a]\n    prompt: p",
            "cycle",
        ),
        (
            "steps:\n  - id: a\n    prompt: p\n"
            "  - id: b\n    prompt: '{steps.a.output}'",
            "does not list 'a' in depends_on",
        ),
        ("steps:\n  - id: a\n    prompt: 'hi {item}'", "no `each`"),
        ("steps:\n  - id: a\n    prompt: '{inputs.nope}'", "undeclared input"),
        (
            "inputs:\n  - {name: t, type: string}\nsteps:\n"
            "  - id: a\n    each: t\n    prompt: p",
            "list/models input",
        ),
        ("name: other\nsteps:\n  - id: a\n    prompt: p", "must match"),
        ("output: nope\nsteps:\n  - id: a\n    prompt: p", "unknown step 'nope'"),
        ("steps:\n  - id: a\n    prompt: p\n  - id: a\n    prompt: q", "Duplicate"),
        ("steps: [\n", "Invalid YAML"),
    ],
)
def test_parse_rejects_bad_definitions(yaml_text, fragment):
    with pytest.raises(workflows.WorkflowError, match=fragment):
        workflows.parse("demo", yaml_text)


def test_parse_rejects_bad_name():
    with pytest.raises(workflows.WorkflowError, match="Invalid workflow name"):
        workflows.parse("Bad Name", MINIMAL)


def test_coding_tools_are_never_grantable():
    """The coding agent's tools aren't in agent.py's schema, so a workflow
    can't reach them — the structural boundary from plan.md decision 2."""
    for tool in ("write_file", "run_tests", "read_file", "list_files"):
        with pytest.raises(workflows.WorkflowError, match="unknown tool"):
            workflows.parse(
                "demo", f"steps:\n  - id: a\n    tools: [{tool}]\n    prompt: p"
            )


def test_save_get_delete_and_discover_reports_errors(tmp_path):
    workflows.save("demo", MINIMAL)
    assert workflows.get("demo").description == "two steps"
    (workflows.WORKFLOWS_DIR / "broken.yaml").write_text("steps: []")
    valid, errors = workflows.discover()
    assert [w.name for w in valid] == ["demo"]
    assert errors and "broken.yaml" in errors[0]
    workflows.delete("demo")
    with pytest.raises(workflows.WorkflowError, match="No such"):
        workflows.get("demo")


def test_save_rejects_invalid_and_leaves_no_file():
    with pytest.raises(workflows.WorkflowError):
        workflows.save("demo", "steps: []")
    assert not (workflows.WORKFLOWS_DIR / "demo.yaml").exists()


def test_builtin_definitions_are_valid(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(workflows, "WORKFLOWS_DIR", Path("workflows"))
    valid, errors = workflows.discover()
    assert errors == []
    assert {"research", "council", "project-brief"} <= {w.name for w in valid}


# --- Rendering + inputs --------------------------------------------------------


def test_render_substitutes_only_known_placeholders():
    ctx = {
        "inputs": {"topic": "cats", "tags": ["a", "b"]},
        "steps": {"first": "F"},
        "item": "qwen",
        "space_id": "s1",
        "run_id": "r1",
    }
    text = (
        "{inputs.topic}|{inputs.tags}|{steps.first.output}|{item}|{space_id}|{run_id}"
    )
    assert workflows.render(text, ctx) == "cats|a\nb|F|qwen|s1|r1"
    # str.format-style braces elsewhere are inert.
    assert workflows.render('json {"k": 1} and {unknown}', ctx) == (
        'json {"k": 1} and {unknown}'
    )


def test_resolve_inputs_defaults_types_and_errors():
    wf = workflows.parse(
        "demo",
        textwrap.dedent(
            """
            inputs:
              - {name: q, type: string}
              - {name: models, type: models}
              - {name: extra, type: string, required: false, default: dflt}
            steps:
              - id: a
                prompt: "{inputs.q}"
            """
        ),
    )
    resolved = workflows.resolve_inputs(wf, {"q": "hi", "models": "m1, m2"})
    assert resolved == {"q": "hi", "models": ["m1", "m2"], "extra": "dflt"}
    with pytest.raises(workflows.WorkflowError, match="Missing required input 'q'"):
        workflows.resolve_inputs(wf, {"models": ["m1"]})
    with pytest.raises(workflows.WorkflowError, match="Unknown input"):
        workflows.resolve_inputs(wf, {"q": "x", "models": ["m"], "zzz": 1})


# --- Runner --------------------------------------------------------------------


def _wait(job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobstore.load(workflows.KIND, job_id)
        if job.status != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_run_orders_steps_renders_and_posts_to_space(monkeypatch):
    fake = _install(monkeypatch, _FakeAgent(outputs={"first": "ONE"}))
    workflows.save("demo", MINIMAL)
    job = _wait(workflows.start("demo", {"topic": "cats"}, doc_sources=["a.pdf"]).id)

    assert job.status == "succeeded", job.error
    assert [c["agent_name"] for c in fake.calls] == [
        "first @ default-model",
        "second @ default-model",
    ]
    assert fake.calls[0]["prompt"] == "First about cats"
    assert fake.calls[1]["prompt"] == "Second sees: ONE"
    assert fake.calls[0]["doc_sources"] == ["a.pdf"]
    assert fake.calls[0]["tools"] == []
    assert "shared space with id" in fake.calls[0]["system"]

    assert job.result["output"] == "out(Second sees: ONE)"
    assert job.result["outputs"] == {"first": "ONE", "second": "out(Second sees: ONE)"}
    space = spaces.get(job.payload["space_id"])
    assert [(p["author"], p["content"]) for p in space["posts"]] == [
        ("first @ default-model", "ONE"),
        ("second @ default-model", "out(Second sees: ONE)"),
    ]
    types = [e["type"] for e in job.events]
    assert types == ["step_started", "step_finished", "step_started", "step_finished"]
    assert job.events[1]["model"] == "default-model"
    assert job.events[1]["tool_calls"] == 0


def test_each_fans_out_over_models_and_joins_downstream(monkeypatch):
    fake = _install(
        monkeypatch, _FakeAgent(outputs={"voice[m1]": "A1", "voice[m2]": "A2"})
    )
    workflows.save("council", FANOUT)
    job = _wait(
        workflows.start("council", {"question": "Q?", "models": ["m1", "m2"]}).id
    )

    assert job.status == "succeeded", job.error
    voices = {c["agent_name"]: c for c in fake.calls[:2]}
    assert set(voices) == {"voice[m1] @ m1", "voice[m2] @ m2"}
    assert voices["voice[m1] @ m1"]["model"] == "m1"
    assert voices["voice[m1] @ m1"]["tools"] == ["read_space"]
    assert job.payload["space_id"] in voices["voice[m1] @ m1"]["prompt"]
    assert job.id in voices["voice[m1] @ m1"]["prompt"]

    merge = fake.calls[2]
    assert merge["agent_name"] == "merge @ default-model"  # judge -> env default
    assert merge["prompt"] == "Merge:\n### m1\nA1\n\n### m2\nA2"
    assert job.result["output"] == "out(Merge:\n### m1\nA1\n\n### m2\nA2)"


def test_step_options_and_provider_options(monkeypatch):
    import providers

    fake = _install(monkeypatch, _FakeAgent())
    monkeypatch.setattr(
        providers,
        "resolve_options",
        lambda role: {"num_ctx": 1} if role == "chat" else None,
    )
    workflows.save(
        "demo",
        "steps:\n  - id: a\n    prompt: p\n    options: {temperature: 0}\n"
        "  - id: b\n    prompt: q\n",
    )
    job = _wait(workflows.start("demo", {}).id)
    assert job.status == "succeeded", job.error
    by_name = {c["agent_name"]: c for c in fake.calls}
    assert by_name["a @ default-model"]["options"] == {"temperature": 0}
    assert by_name["b @ default-model"]["options"] == {"num_ctx": 1}


def test_failed_step_fails_the_run_and_skips_dependents(monkeypatch):
    fake = _install(monkeypatch, _FakeAgent(fail_step="first"))
    workflows.save("demo", MINIMAL)
    job = _wait(workflows.start("demo", {"topic": "t"}).id)

    assert job.status == "failed"
    assert "Step 'first' failed: boom" in job.error
    assert [c["agent_name"] for c in fake.calls] == ["first @ default-model"]
    assert [e["type"] for e in job.events] == ["step_started", "step_failed"]
    assert job.events[1]["error"] == "boom"


def test_blank_output_is_retried_once_then_fails(monkeypatch):
    fake = _install(monkeypatch, _FakeAgent(blank_first=True))
    workflows.save("demo", "steps:\n  - id: a\n    prompt: p\n")
    job = _wait(workflows.start("demo", {}).id)
    assert job.status == "succeeded", job.error
    assert len(fake.calls) == 2  # blank, then retried

    always_blank = _install(monkeypatch, _FakeAgent(outputs={"a": ""}))
    job = _wait(workflows.start("demo", {}).id)
    assert job.status == "failed"
    assert "returned no output" in job.error
    assert len(always_blank.calls) == workflows.MAX_STEP_ATTEMPTS


def test_start_validates_inputs_before_creating_anything(monkeypatch):
    _install(monkeypatch, _FakeAgent())
    workflows.save("council", FANOUT)
    with pytest.raises(workflows.WorkflowError, match="Missing required input"):
        workflows.start("council", {"question": "q"})
    with pytest.raises(workflows.WorkflowError, match="Missing required input"):
        workflows.start("council", {"question": "q", "models": []})
    # An optional list input left empty is caught at fan-out expansion.
    with pytest.raises(workflows.WorkflowError, match="which is empty"):
        workflows._instances(workflows.get("council"), {"question": "q", "models": []})
    assert spaces.list_recent() == []
    assert jobstore.list_recent(workflows.KIND) == []


def test_instance_limit(monkeypatch):
    _install(monkeypatch, _FakeAgent())
    workflows.save("council", FANOUT)
    too_many = [f"m{i}" for i in range(workflows.MAX_STEP_INSTANCES)]
    with pytest.raises(workflows.WorkflowError, match="exceeds the limit"):
        workflows.start("council", {"question": "q", "models": too_many})


def test_missing_model_for_role_fails_loudly(monkeypatch):
    fake = _install(monkeypatch, _FakeAgent())
    monkeypatch.delenv("OLLAMA_MODEL")
    workflows.save("demo", "steps:\n  - id: a\n    prompt: p\n")
    job = _wait(workflows.start("demo", {}).id)
    assert job.status == "failed"
    assert "no model configured for role 'chat'" in job.error
    assert fake.calls == []


def test_tools_are_dropped_for_models_that_cannot_call_them(monkeypatch):
    fake = _install(
        monkeypatch, _FakeAgent(outputs={"voice[m1]": "A1", "voice[m2]": "A2"})
    )
    monkeypatch.setattr(providers, "tool_capable_models", lambda: {"m1"})
    workflows.save("council", FANOUT)
    job = _wait(
        workflows.start("council", {"question": "Q?", "models": ["m1", "m2"]}).id
    )

    assert job.status == "succeeded", job.error
    voices = {c["agent_name"]: c for c in fake.calls[:2]}
    assert voices["voice[m1] @ m1"]["tools"] == ["read_space"]
    assert voices["voice[m2] @ m2"]["tools"] == []
    finished = {e["step"]: e for e in job.events if e["type"] == "step_finished"}
    assert finished["voice[m1]"]["tools_dropped"] is False
    assert finished["voice[m2]"]["tools_dropped"] is True
