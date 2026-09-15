"""Agentic workflows — YAML-defined, multi-step, multi-model pipelines run
by the CHAT agent loop with a restricted tool list (plan.md decisions 2 and
3, Phases 19–26).

A workflow is workflows/<name>.yaml:

    name: council
    description: Several models answer; a judge synthesizes.
    inputs:
      - {name: question, type: string, description: ...}
      - {name: models, type: models, description: ...}
    system: optional workflow-wide system prompt
    output: synthesize            # step whose output is the run's result
    steps:
      - id: voice
        name: Voice
        each: models              # one instance per item, in parallel
        model: "{item}"           # explicit model (or role: chat|judge|...)
        tools: [read_space]
        prompt: |
          {inputs.question} ...
      - id: synthesize
        role: judge
        depends_on: [voice]
        prompt: |
          {steps.voice.output} ...

Each step instance gets a fresh memory.Conversation and one agent.run()
call with `tools=` set to exactly the step's allowlist — so a step can only
ever reach what agent.py already exposes to chat. The coding agent's
write/exec tools are structurally unreachable from here, as from chat.

Every run gets its own shared space (spaces.py): the runner posts each
step's output there under "<step> @ <model>", so the space IS the
inter-model transcript, and steps that are granted read_space can read
what earlier or parallel steps said. Runs are jobstore jobs of kind
"workflow", so /api/jobs/workflow/<id>[/events] serves them.
"""

import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import agent
import jobstore
import providers
import skills
import spaces
from memory import Conversation

WORKFLOWS_DIR = Path("workflows")
KIND = "workflow"
MAX_STEP_INSTANCES = 20
MAX_PARALLEL = 4
MAX_STEP_ATTEMPTS = 2

_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_INPUT_TYPES = {"string", "list", "models"}
_LIST_TYPES = {"list", "models"}
# The only placeholder forms a template may use. A deliberately small regex
# renderer — NOT str.format — so braces elsewhere in a prompt are inert.
_PLACEHOLDER = re.compile(
    r"\{(inputs\.[A-Za-z0-9_-]+|steps\.[A-Za-z0-9_-]+\.output|item|space_id|run_id)\}"
)


class WorkflowError(Exception):
    """Invalid definition, unknown workflow, bad inputs, or a failed step.
    Callers surface the message as an HTTP 4xx or the job's error — never
    an unhandled crash."""


@dataclass
class InputSpec:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: object = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default": self.default,
        }


@dataclass
class StepSpec:
    id: str
    name: str
    prompt: str
    role: str = "chat"
    model: str | None = None
    system: str = ""
    tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    each: str | None = None
    options: dict | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "role": self.role,
            "model": self.model,
            "system": self.system,
            "tools": list(self.tools),
            "depends_on": list(self.depends_on),
            "each": self.each,
            "options": self.options,
        }


@dataclass
class Workflow:
    name: str
    description: str
    inputs: list[InputSpec]
    steps: list[StepSpec]
    system: str = ""
    output: str = ""
    yaml_text: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputs": [i.to_dict() for i in self.inputs],
            "steps": [s.to_dict() for s in self.steps],
            "system": self.system,
            "output": self.output,
            "yaml": self.yaml_text,
        }


# --- Definitions -------------------------------------------------------------


def _validate_name(name: str) -> None:
    if not _NAME_PATTERN.match(name or ""):
        raise WorkflowError(
            f"Invalid workflow name {name!r}: lowercase letters, digits, hyphens."
        )


def _known_tool_names() -> set[str]:
    """Every tool a step may be granted: agent.py's built-ins plus the
    skills on disk. Deliberately not filtered by the web-tools flag — a
    definition stays valid offline; agent.available_tool_schemas() drops
    the web tools at run time."""
    return {s["function"]["name"] for s in agent.TOOL_SCHEMAS + skills.tool_schemas()}


def _placeholders(text: str) -> list[str]:
    return _PLACEHOLDER.findall(text or "")


def _parse_inputs(raw) -> list[InputSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorkflowError("`inputs` must be a list.")
    specs = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            raise WorkflowError("Each input needs a `name`.")
        name = str(item["name"])
        if not re.match(r"^[A-Za-z0-9_-]+$", name):
            raise WorkflowError(f"Invalid input name {name!r}.")
        if name in seen:
            raise WorkflowError(f"Duplicate input {name!r}.")
        seen.add(name)
        kind = str(item.get("type") or "string")
        if kind not in _INPUT_TYPES:
            raise WorkflowError(
                f"Input {name!r} has unknown type {kind!r}; "
                "use string, list, or models."
            )
        specs.append(
            InputSpec(
                name=name,
                type=kind,
                description=str(item.get("description") or ""),
                required=bool(item.get("required", True)),
                default=item.get("default"),
            )
        )
    return specs


def _parse_steps(raw, inputs: dict[str, InputSpec]) -> list[StepSpec]:
    if not isinstance(raw, list) or not raw:
        raise WorkflowError("`steps` must be a non-empty list.")
    steps: list[StepSpec] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            raise WorkflowError("Each step needs an `id`.")
        step_id = str(item["id"])
        _validate_name_or_raise(step_id, "step id")
        if any(s.id == step_id for s in steps):
            raise WorkflowError(f"Duplicate step id {step_id!r}.")
        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise WorkflowError(f"Step {step_id!r} needs a `prompt`.")
        role = str(item.get("role") or "chat")
        if role not in providers.ROLES:
            raise WorkflowError(
                f"Step {step_id!r} has unknown role {role!r}; "
                f"roles are {providers.ROLES}."
            )
        model = item.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise WorkflowError(f"Step {step_id!r}: `model` must be a model tag.")
        tools = item.get("tools") or []
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            raise WorkflowError(f"Step {step_id!r}: `tools` must be a list of names.")
        depends_on = item.get("depends_on") or []
        if not isinstance(depends_on, list):
            raise WorkflowError(f"Step {step_id!r}: `depends_on` must be a list.")
        each = item.get("each")
        if each is not None:
            each = str(each)
            if each not in inputs or inputs[each].type not in _LIST_TYPES:
                raise WorkflowError(
                    f"Step {step_id!r}: `each` must name a list/models input."
                )
        options = item.get("options")
        if options is not None and not isinstance(options, dict):
            raise WorkflowError(f"Step {step_id!r}: `options` must be a mapping.")
        steps.append(
            StepSpec(
                id=step_id,
                name=str(item.get("name") or step_id),
                prompt=prompt,
                role=role,
                model=model,
                system=str(item.get("system") or ""),
                tools=[str(t) for t in tools],
                depends_on=[str(d) for d in depends_on],
                each=each,
                options=options,
            )
        )
    return steps


def _validate_name_or_raise(value: str, what: str) -> None:
    if not _NAME_PATTERN.match(value):
        raise WorkflowError(f"Invalid {what} {value!r}: lowercase, digits, hyphens.")


def _check_references(workflow: Workflow) -> None:
    """Tools exist, dependencies exist, templates reference declared
    inputs/steps only, `{item}` only inside an `each` step, `{steps.X}`
    only for a declared dependency (so ordering is guaranteed), and the
    dependency graph is acyclic."""
    known_tools = _known_tool_names()
    step_ids = {s.id for s in workflow.steps}
    input_names = {i.name for i in workflow.inputs}

    for step in workflow.steps:
        for tool in step.tools:
            if tool not in known_tools:
                raise WorkflowError(f"Step {step.id!r} grants unknown tool {tool!r}.")
        for dep in step.depends_on:
            if dep not in step_ids:
                raise WorkflowError(
                    f"Step {step.id!r} depends on unknown step {dep!r}."
                )
            if dep == step.id:
                raise WorkflowError(f"Step {step.id!r} depends on itself.")
        for ref in _placeholders(
            step.prompt + "\n" + step.system + "\n" + (step.model or "")
        ):
            if ref.startswith("inputs."):
                if ref[len("inputs.") :] not in input_names:
                    raise WorkflowError(
                        f"Step {step.id!r} references undeclared input {{{ref}}}."
                    )
            elif ref.startswith("steps."):
                target = ref[len("steps.") : -len(".output")]
                if target not in step_ids:
                    raise WorkflowError(
                        f"Step {step.id!r} references unknown step {{{ref}}}."
                    )
                if target not in step.depends_on:
                    raise WorkflowError(
                        f"Step {step.id!r} uses {{{ref}}} but does not list "
                        f"{target!r} in depends_on."
                    )
            elif ref == "item" and step.each is None:
                raise WorkflowError(
                    f"Step {step.id!r} uses {{item}} but has no `each`."
                )

    if workflow.output not in step_ids:
        raise WorkflowError(f"`output` names unknown step {workflow.output!r}.")

    # Cycle check: Kahn's algorithm over depends_on.
    remaining = {s.id: set(s.depends_on) for s in workflow.steps}
    while remaining:
        ready = [sid for sid, deps in remaining.items() if not deps]
        if not ready:
            raise WorkflowError(f"Dependency cycle among steps {sorted(remaining)}.")
        for sid in ready:
            del remaining[sid]
        for deps in remaining.values():
            deps.difference_update(ready)


def parse(name: str, yaml_text: str) -> Workflow:
    """Parse + validate a definition. Raises WorkflowError on anything
    wrong, with a message a YAML author can act on."""
    _validate_name(name)
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise WorkflowError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError("A workflow definition must be a mapping.")
    declared = data.get("name")
    if declared is not None and str(declared) != name:
        raise WorkflowError(f"`name` {declared!r} must match the file name {name!r}.")

    inputs = _parse_inputs(data.get("inputs"))
    steps = _parse_steps(data.get("steps"), {i.name: i for i in inputs})
    workflow = Workflow(
        name=name,
        description=str(data.get("description") or ""),
        inputs=inputs,
        steps=steps,
        system=str(data.get("system") or ""),
        output=str(data.get("output") or steps[-1].id),
        yaml_text=yaml_text,
    )
    _check_references(workflow)
    return workflow


def _path(name: str) -> Path:
    return WORKFLOWS_DIR / f"{name}.yaml"


def discover() -> tuple[list[Workflow], list[str]]:
    """(valid workflows, error messages for malformed ones). Never raises —
    a broken definition must not take down the list (same posture as
    skills.discover)."""
    valid: list[Workflow] = []
    errors: list[str] = []
    if not WORKFLOWS_DIR.exists():
        return valid, errors
    for path in sorted(WORKFLOWS_DIR.glob("*.yaml")):
        try:
            valid.append(parse(path.stem, path.read_text()))
        except WorkflowError as exc:
            errors.append(f"{path.name}: {exc}")
    return valid, errors


def get(name: str) -> Workflow:
    _validate_name(name)
    path = _path(name)
    if not path.exists():
        raise WorkflowError(f"No such workflow: {name!r}")
    return parse(name, path.read_text())


def save(name: str, yaml_text: str) -> Workflow:
    """Create/update a definition from raw YAML — validated first, so a bad
    file never lands on disk."""
    workflow = parse(name, yaml_text)
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    _path(name).write_text(yaml_text)
    return workflow


def delete(name: str) -> None:
    _validate_name(name)
    path = _path(name)
    if not path.exists():
        raise WorkflowError(f"No such workflow: {name!r}")
    path.unlink()


# --- Rendering ---------------------------------------------------------------


def render(template: str, context: dict) -> str:
    """Substitute the supported placeholders (module docstring). `context`
    holds "inputs" (dict), "steps" (dict of step id -> output), and the
    scalars "item", "space_id", "run_id". Unknown references are left
    untouched — validation already rejected them at load time."""

    def sub(match: re.Match) -> str:
        ref = match.group(1)
        if ref.startswith("inputs."):
            value = context.get("inputs", {}).get(ref[len("inputs.") :])
        elif ref.startswith("steps."):
            value = context.get("steps", {}).get(ref[len("steps.") : -len(".output")])
        else:
            value = context.get(ref)
        if value is None:
            return match.group(0)
        if isinstance(value, list):
            return "\n".join(str(v) for v in value)
        return str(value)

    return _PLACEHOLDER.sub(sub, template)


def resolve_inputs(workflow: Workflow, given: dict) -> dict:
    """Apply defaults and type-check the caller's inputs."""
    given = given or {}
    unknown = set(given) - {i.name for i in workflow.inputs}
    if unknown:
        raise WorkflowError(f"Unknown input(s): {sorted(unknown)}")
    resolved = {}
    for spec in workflow.inputs:
        value = given.get(spec.name, spec.default)
        if value is None or value == "" or value == []:
            if spec.required:
                raise WorkflowError(f"Missing required input {spec.name!r}.")
            value = [] if spec.type in _LIST_TYPES else ""
        if spec.type in _LIST_TYPES:
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            if not isinstance(value, list):
                raise WorkflowError(f"Input {spec.name!r} must be a list.")
            value = [str(v) for v in value]
        else:
            value = str(value)
        resolved[spec.name] = value
    return resolved


# --- Runner ------------------------------------------------------------------


@dataclass
class _Instance:
    id: str
    step: StepSpec
    item: str | None
    deps: set[str] = field(default_factory=set)


def _instances(workflow: Workflow, inputs: dict) -> list[_Instance]:
    """Expand `each` steps into one instance per item and wire instance-
    level dependencies (an instance depends on every instance of each step
    it depends on)."""
    by_step: dict[str, list[_Instance]] = {}
    for step in workflow.steps:
        items = inputs[step.each] if step.each else [None]
        if step.each and not items:
            raise WorkflowError(
                f"Step {step.id!r} fans out over input {step.each!r}, which is empty."
            )
        by_step[step.id] = [
            _Instance(
                id=f"{step.id}[{item}]" if item is not None else step.id,
                step=step,
                item=item,
            )
            for item in items
        ]
    ordered = [inst for step in workflow.steps for inst in by_step[step.id]]
    if len(ordered) > MAX_STEP_INSTANCES:
        raise WorkflowError(
            f"{len(ordered)} step instances exceeds the limit of {MAX_STEP_INSTANCES}."
        )
    for inst in ordered:
        for dep in inst.step.depends_on:
            inst.deps.update(i.id for i in by_step[dep])
    return ordered


def _step_output(workflow: Workflow, outputs: dict[str, str], step_id: str) -> str:
    """A step's output for templates: its single instance's output, or for
    an `each` step every instance's output under a "### <item>" header."""
    step = next(s for s in workflow.steps if s.id == step_id)
    if step.each is None:
        return outputs.get(step_id, "")
    prefix = f"{step_id}["
    blocks = [
        f"### {iid[len(prefix) : -1]}\n{out}"
        for iid, out in outputs.items()
        if iid.startswith(prefix)
    ]
    return "\n\n".join(blocks)


def _system_prompt(workflow: Workflow, inst: _Instance, space_id: str) -> str:
    parts = [workflow.system.strip(), inst.step.system.strip()]
    parts.append(
        f"You are the '{inst.step.name}' step ({inst.id}) of the "
        f"'{workflow.name}' workflow. Other steps post their results to the "
        f"shared space with id {space_id}; if you have the read_space tool, "
        "use it to see what they said. Reply with this step's complete "
        "result as plain text — it is passed to later steps and posted to "
        "the space verbatim. Do not ask questions; do the work."
    )
    return "\n\n".join(p for p in parts if p)


def _run_instance(
    workflow: Workflow,
    inst: _Instance,
    context: dict,
    space_id: str,
    doc_sources: list[str] | None,
    tool_capable: set[str] | None,
) -> tuple[str, str, int, bool]:
    """Execute one instance: resolve its model, render its prompt, run the
    chat agent loop once with the step's tool allowlist, post the output to
    the run's space. Returns (model, output, tool_call_count, tools_dropped).

    A step whose model can't call tools (a council voice on a small model,
    say) runs without its allowlist instead of failing the whole run — Ollama
    rejects tool schemas for such models outright — and the drop is reported
    in the step_finished event so it is visible, not silent."""
    step = inst.step
    if step.model:
        model = render(step.model, context)
    else:
        model = providers.resolve(step.role)
    if not model:
        raise WorkflowError(
            f"Step {inst.id!r}: no model configured for role {step.role!r} "
            "(set a provider route or OLLAMA_MODEL)."
        )
    tools = list(step.tools)
    tools_dropped = bool(tools) and not providers.supports_tools(model, tool_capable)
    if tools_dropped:
        tools = []
    options = step.options or providers.resolve_options(step.role)
    agent_name = f"{inst.id} @ {model}"
    prompt = render(step.prompt, context)
    system = _system_prompt(workflow, inst, space_id)
    run_context = agent.RunContext(agent_name=agent_name, doc_sources=doc_sources)
    # A model occasionally returns an empty reply when tools are advertised
    # (seen live with qwen2.5 + read_space, 2026-09-15). A blank step would
    # poison every step downstream, so retry once with a fresh conversation
    # and otherwise fail the step loudly rather than pass silence along.
    output = ""
    tool_calls = 0
    for _attempt in range(MAX_STEP_ATTEMPTS):
        conversation = Conversation(system_prompt=system)
        output = agent.run(
            prompt,
            conversation,
            model,
            tools=tools,
            options=options,
            context=run_context,
        )
        tool_calls = sum(
            len(m.get("tool_calls") or [])
            for m in conversation.messages
            if m.get("role") == "assistant"
        )
        if output and output.strip():
            break
    else:
        raise WorkflowError(
            f"model {model!r} returned no output after {MAX_STEP_ATTEMPTS} attempts."
        )
    spaces.post(space_id, agent_name, output)
    return model, output, tool_calls, tools_dropped


def _run(
    workflow: Workflow,
    inputs: dict,
    job_id: str,
    space_id: str,
    doc_sources: list[str] | None,
) -> dict:
    instances = _instances(workflow, inputs)
    pending = {inst.id: inst for inst in instances}
    tool_capable = (
        providers.tool_capable_models()
        if any(i.step.tools for i in instances)
        else None
    )
    outputs: dict[str, str] = {}
    running: dict = {}
    failure: WorkflowError | None = None

    def context_for(inst: _Instance) -> dict:
        return {
            "inputs": inputs,
            "steps": {
                s.id: _step_output(workflow, outputs, s.id) for s in workflow.steps
            },
            "item": inst.item,
            "space_id": space_id,
            "run_id": job_id,
        }

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        while pending or running:
            if failure is None:
                ready = [
                    inst
                    for inst in pending.values()
                    if inst.deps <= set(outputs) and len(running) < MAX_PARALLEL
                ]
                for inst in ready[: MAX_PARALLEL - len(running)]:
                    del pending[inst.id]
                    jobstore.append_event(
                        KIND, job_id, {"type": "step_started", "step": inst.id}
                    )
                    started = time.monotonic()
                    future = pool.submit(
                        _run_instance,
                        workflow,
                        inst,
                        context_for(inst),
                        space_id,
                        doc_sources,
                        tool_capable,
                    )
                    running[future] = (inst, started)
            elif not running:
                break
            if not running:
                # Nothing runnable and nothing running: unmet dependencies.
                raise WorkflowError(
                    f"Steps {sorted(pending)} can never run (unmet dependencies)."
                )
            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for future in done:
                inst, started = running.pop(future)
                seconds = round(time.monotonic() - started, 2)
                try:
                    model, output, tool_calls, tools_dropped = future.result()
                except Exception as exc:
                    jobstore.append_event(
                        KIND,
                        job_id,
                        {"type": "step_failed", "step": inst.id, "error": str(exc)},
                    )
                    failure = failure or WorkflowError(
                        f"Step {inst.id!r} failed: {exc}"
                    )
                    continue
                outputs[inst.id] = output
                jobstore.append_event(
                    KIND,
                    job_id,
                    {
                        "type": "step_finished",
                        "step": inst.id,
                        "model": model,
                        "output": output,
                        "seconds": seconds,
                        "tool_calls": tool_calls,
                        "tools_dropped": tools_dropped,
                    },
                )
    if failure is not None:
        raise failure
    return {
        "output": _step_output(workflow, outputs, workflow.output),
        "outputs": outputs,
        "space_id": space_id,
    }


def start(
    name: str,
    inputs: dict,
    doc_sources: list[str] | None = None,
    project_id: str | None = None,
) -> jobstore.Job:
    """Validate, create the run's space, and launch the DAG on a background
    thread as a jobstore job of kind "workflow". Definition/input errors
    raise here (an HTTP 4xx); anything during execution lands in the job's
    error via jobstore.run_in_background."""
    workflow = get(name)
    resolved = resolve_inputs(workflow, inputs)
    _instances(workflow, resolved)  # fail fast on empty fan-outs / limits
    space = spaces.create(f"{workflow.name} run", purpose=workflow.description)
    payload = {
        "name": workflow.name,
        "inputs": resolved,
        "project_id": project_id,
        "doc_sources": doc_sources,
        "space_id": space["id"],
    }
    return jobstore.run_in_background(
        KIND,
        payload,
        lambda job_id: _run(workflow, resolved, job_id, space["id"], doc_sources),
    )
