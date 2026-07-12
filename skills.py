"""Skills registry — user-authored capabilities the model calls as tools.

Each skill is a directory under skills/<name>/ with a skill.yaml manifest
and either a prompt.md (instruction skill: rendered with the call's
arguments and returned as the tool result — the model follows it) or a
run.py (code skill: defines run(**args) -> str, executed in-process).
Discovered fresh on every agent turn so edits take effect without a restart.

Security model: this is a local, single-user app — skills are files on
disk, and code skills run in-process with no sandbox (see skills/README.md).
The one entry point reachable from an untrusted model tool call
(create_instruction_skill, wired to the agent's own create_skill tool) can
only ever write a prompt.md, never a run.py, by construction — it has no
`code` parameter to pass one through. Writing a run.py requires a human
acting through the CRUD API/filesystem directly (write_skill). Path
traversal is blocked here, at the point of any filesystem access, not only
in server.py's request validation.
"""

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_DIR = Path("skills")
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillError(Exception):
    """Invalid skill name/definition, or a failure running one. Callers feed
    the message back as a tool result or an HTTP 4xx — never an unhandled
    crash of the agent loop or the API."""


def _validate_name(name: str) -> None:
    if not _NAME_PATTERN.match(name):
        raise SkillError(
            f"Invalid skill name {name!r}: use lowercase letters, digits, and "
            "hyphens only, e.g. 'summarize-for-email'."
        )


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict
    required: list[str]
    kind: str  # "instruction" | "code"
    body: str  # raw prompt.md or run.py content, for display/editing
    path: Path


def discover() -> tuple[list[Skill], list[str]]:
    """Return (valid skills, error messages for malformed ones).

    Never raises — a broken skill.yaml must not take down the agent loop.
    """
    skills: list[Skill] = []
    errors: list[str] = []
    if not SKILLS_DIR.exists():
        return skills, errors

    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        manifest_path = skill_dir / "skill.yaml"
        if not manifest_path.exists():
            continue
        try:
            skills.append(_load_manifest(skill_dir, manifest_path))
        except Exception as exc:
            errors.append(f"{skill_dir.name}: {exc}")
    return skills, errors


def _load_manifest(skill_dir: Path, manifest_path: Path) -> Skill:
    data = yaml.safe_load(manifest_path.read_text()) or {}
    name = data.get("name", skill_dir.name)
    _validate_name(name)
    if name != skill_dir.name:
        raise SkillError(
            f"skill.yaml name {name!r} must match its directory {skill_dir.name!r}"
        )

    prompt_path = skill_dir / "prompt.md"
    code_path = skill_dir / "run.py"
    has_prompt = prompt_path.exists()
    has_code = code_path.exists()
    if has_prompt == has_code:  # both or neither
        raise SkillError("must have exactly one of prompt.md or run.py")

    return Skill(
        name=name,
        description=data.get("description", ""),
        parameters=data.get("parameters") or {},
        required=data.get("required") or [],
        kind="instruction" if has_prompt else "code",
        body=(prompt_path if has_prompt else code_path).read_text(),
        path=skill_dir,
    )


def tool_schemas() -> list[dict]:
    """Advertised tool schemas for every valid discovered skill."""
    valid, _errors = discover()
    return [
        {
            "type": "function",
            "function": {
                "name": f"skill__{s.name}",
                "description": s.description,
                "parameters": {
                    "type": "object",
                    "properties": s.parameters,
                    "required": s.required,
                },
            },
        }
        for s in valid
    ]


def execute(tool_name: str, args: dict) -> str:
    """Run a skill given its advertised tool name (`skill__<name>`)."""
    name = tool_name.removeprefix("skill__")
    valid, _errors = discover()
    skill = next((s for s in valid if s.name == name), None)
    if skill is None:
        raise SkillError(f"Unknown skill: {name!r}")

    if skill.kind == "instruction":
        template = (skill.path / "prompt.md").read_text()
        try:
            return template.format(**args)
        except KeyError as exc:
            raise SkillError(f"prompt.md references missing argument {exc}") from exc

    spec = importlib.util.spec_from_file_location(
        f"_skill_{skill.name}", skill.path / "run.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.run(**args))


def write_skill(
    name: str,
    description: str,
    parameters: dict,
    required: list[str],
    *,
    prompt: str | None = None,
    code: str | None = None,
) -> str:
    """General-purpose writer behind the human-facing CRUD API. Can write
    either kind, and overwrites an existing skill of the same name (used for
    both create and update). Not reachable from the model's own tool calls —
    see create_instruction_skill for that entry point."""
    if (prompt is None) == (code is None):
        raise SkillError("Provide exactly one of prompt or code.")
    _validate_name(name)

    skill_dir = SKILLS_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "prompt.md").unlink(missing_ok=True)
    (skill_dir / "run.py").unlink(missing_ok=True)

    manifest = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "required": required,
    }
    (skill_dir / "skill.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    if prompt is not None:
        (skill_dir / "prompt.md").write_text(prompt)
    else:
        (skill_dir / "run.py").write_text(code)
    return f"Wrote skill {name!r}."


def create_instruction_skill(
    name: str,
    description: str,
    parameters: dict,
    required: list[str],
    prompt: str,
) -> str:
    """The only registry entry point reachable from the model's own
    create_skill tool call. Structurally cannot write a run.py — it has no
    `code` parameter to pass one through, by design (see module docstring)."""
    if (SKILLS_DIR / name).exists():
        raise SkillError(f"Skill {name!r} already exists.")
    return write_skill(name, description, parameters, required, prompt=prompt)


def delete_skill(name: str) -> None:
    _validate_name(name)
    skill_dir = SKILLS_DIR / name
    if not skill_dir.exists():
        raise SkillError(f"Skill {name!r} does not exist.")
    for child in skill_dir.iterdir():
        child.unlink()
    skill_dir.rmdir()
