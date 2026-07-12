"""Unit tests for the skills registry — discovery, both execution paths,
malformed-manifest handling, and the create_instruction_skill trust boundary.
No live model needed."""

import inspect

import pytest

import skills


@pytest.fixture(autouse=True)
def isolated_skills_dir(tmp_path, monkeypatch):
    """Every test gets its own throwaway skills/ dir — never touch the
    project's real skills/ directory."""
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "skills")
    return tmp_path / "skills"


def _write_manifest(
    skill_dir, name, description="a skill", parameters=None, required=None
):
    skill_dir.mkdir(parents=True)
    import yaml

    manifest = {
        "name": name,
        "description": description,
        "parameters": parameters or {},
        "required": required or [],
    }
    (skill_dir / "skill.yaml").write_text(yaml.safe_dump(manifest))


def test_discover_returns_empty_when_no_skills_dir():
    valid, errors = skills.discover()
    assert valid == []
    assert errors == []


def test_discover_finds_instruction_skill(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "greet"
    _write_manifest(skill_dir, "greet", parameters={"name": {"type": "string"}})
    (skill_dir / "prompt.md").write_text("Say hello to {name}.")

    valid, errors = skills.discover()
    assert errors == []
    assert len(valid) == 1
    assert valid[0].kind == "instruction"
    assert valid[0].name == "greet"


def test_discover_finds_code_skill(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "word-count"
    _write_manifest(skill_dir, "word-count", parameters={"text": {"type": "string"}})
    (skill_dir / "run.py").write_text(
        "def run(text):\n    return str(len(text.split()))\n"
    )

    valid, errors = skills.discover()
    assert errors == []
    assert valid[0].kind == "code"


def test_discover_reports_error_when_missing_both_prompt_and_code(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "broken"
    _write_manifest(skill_dir, "broken")

    valid, errors = skills.discover()
    assert valid == []
    assert len(errors) == 1
    assert "exactly one" in errors[0]


def test_discover_reports_error_when_both_prompt_and_code_present(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "broken"
    _write_manifest(skill_dir, "broken")
    (skill_dir / "prompt.md").write_text("x")
    (skill_dir / "run.py").write_text("def run():\n    return 'x'\n")

    valid, errors = skills.discover()
    assert valid == []
    assert "exactly one" in errors[0]


def test_discover_reports_error_on_name_mismatch(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "actual-dir-name"
    _write_manifest(skill_dir, "different-name")
    (skill_dir / "prompt.md").write_text("x")

    valid, errors = skills.discover()
    assert valid == []
    assert "must match its directory" in errors[0]


def test_discover_skips_directories_without_manifest(isolated_skills_dir):
    (isolated_skills_dir / "not-a-skill").mkdir(parents=True)

    valid, errors = skills.discover()
    assert valid == []
    assert errors == []


def test_tool_schemas_shape(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "greet"
    _write_manifest(
        skill_dir,
        "greet",
        description="Greets someone",
        parameters={"name": {"type": "string"}},
        required=["name"],
    )
    (skill_dir / "prompt.md").write_text("Say hello to {name}.")

    schemas = skills.tool_schemas()
    assert len(schemas) == 1
    fn = schemas[0]["function"]
    assert fn["name"] == "skill__greet"
    assert fn["description"] == "Greets someone"
    assert fn["parameters"]["properties"] == {"name": {"type": "string"}}
    assert fn["parameters"]["required"] == ["name"]


def test_execute_instruction_skill_renders_template(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "greet"
    _write_manifest(skill_dir, "greet", parameters={"name": {"type": "string"}})
    (skill_dir / "prompt.md").write_text("Say hello to {name} warmly.")

    result = skills.execute("skill__greet", {"name": "Ada"})
    assert result == "Say hello to Ada warmly."


def test_execute_instruction_skill_missing_arg_raises(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "greet"
    _write_manifest(skill_dir, "greet", parameters={"name": {"type": "string"}})
    (skill_dir / "prompt.md").write_text("Say hello to {name}.")

    with pytest.raises(skills.SkillError):
        skills.execute("skill__greet", {})


def test_execute_code_skill_calls_run(isolated_skills_dir):
    skill_dir = isolated_skills_dir / "word-count"
    _write_manifest(skill_dir, "word-count", parameters={"text": {"type": "string"}})
    (skill_dir / "run.py").write_text(
        "def run(text):\n    return str(len(text.split()))\n"
    )

    result = skills.execute("skill__word-count", {"text": "one two three"})
    assert result == "3"


def test_execute_unknown_skill_raises():
    with pytest.raises(skills.SkillError):
        skills.execute("skill__does-not-exist", {})


def test_write_skill_requires_exactly_one_of_prompt_or_code():
    with pytest.raises(skills.SkillError):
        skills.write_skill("x", "d", {}, [])
    with pytest.raises(skills.SkillError):
        skills.write_skill("x", "d", {}, [], prompt="p", code="c")


def test_write_skill_creates_instruction_skill(isolated_skills_dir):
    skills.write_skill(
        "greet", "Greets", {"name": {"type": "string"}}, ["name"], prompt="Hi {name}"
    )

    valid, errors = skills.discover()
    assert errors == []
    assert valid[0].kind == "instruction"


def test_write_skill_overwrites_switching_kind(isolated_skills_dir):
    skills.write_skill("thing", "d", {}, [], prompt="p")
    skills.write_skill("thing", "d", {}, [], code="def run():\n    return 'ok'\n")

    valid, _ = skills.discover()
    assert len(valid) == 1
    assert valid[0].kind == "code"
    assert not (isolated_skills_dir / "thing" / "prompt.md").exists()


def test_create_instruction_skill_rejects_existing_name(isolated_skills_dir):
    skills.write_skill("greet", "d", {}, [], prompt="p")
    with pytest.raises(skills.SkillError):
        skills.create_instruction_skill("greet", "d2", {}, [], "p2")


def test_create_instruction_skill_has_no_code_parameter():
    """Structural enforcement of the security boundary: the model's own
    create_skill tool calls this function, which must have no way to accept
    a `code` argument even if a malicious/confused caller tried to pass one."""
    assert "code" not in inspect.signature(skills.create_instruction_skill).parameters


def test_delete_skill_removes_directory(isolated_skills_dir):
    skills.write_skill("greet", "d", {}, [], prompt="p")
    skills.delete_skill("greet")
    assert not (isolated_skills_dir / "greet").exists()


def test_delete_skill_missing_raises():
    with pytest.raises(skills.SkillError):
        skills.delete_skill("does-not-exist")


def test_write_skill_rejects_path_traversal_name(isolated_skills_dir):
    with pytest.raises(skills.SkillError):
        skills.write_skill("../evil", "d", {}, [], prompt="p")
    assert not (isolated_skills_dir.parent / "evil").exists()


def test_create_instruction_skill_rejects_path_traversal_name(isolated_skills_dir):
    with pytest.raises(skills.SkillError):
        skills.create_instruction_skill("../../evil", "d", {}, [], "p")
