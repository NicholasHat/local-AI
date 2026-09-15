"""spaces.py — shared communication spaces (Phase 20)."""

import pytest

import spaces


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")


def test_create_post_read():
    space = spaces.create("council", purpose="debate")
    spaces.post(space["id"], "writer @ qwen", "First draft.")
    spaces.post(space["id"], "critic @ llama", "Too vague.")
    full = spaces.get(space["id"])
    assert [p["author"] for p in full["posts"]] == ["writer @ qwen", "critic @ llama"]
    assert spaces.get_meta(space["id"]).post_count == 2


def test_render_shows_latest_posts_with_header():
    space = spaces.create("s", purpose="p")
    for i in range(5):
        spaces.post(space["id"], "a", f"post {i}")
    text = spaces.render(space["id"], limit=2)
    assert "Space 's'" in text and "purpose: p" in text
    assert "post 3" in text and "post 4" in text and "post 2" not in text


def test_render_empty():
    space = spaces.create("s")
    assert "(no posts yet)" in spaces.render(space["id"])


def test_validation():
    with pytest.raises(spaces.SpaceError):
        spaces.create("   ")
    space = spaces.create("s")
    with pytest.raises(spaces.SpaceError):
        spaces.post(space["id"], "", "x")
    with pytest.raises(spaces.SpaceError):
        spaces.post(space["id"], "a", "  ")
    with pytest.raises(spaces.SpaceError):
        spaces.post("missing", "a", "x")


def test_list_recent_orders_by_activity_and_delete():
    a = spaces.create("a")
    b = spaces.create("b")
    spaces.post(a["id"], "x", "bump")
    assert [m.id for m in spaces.list_recent()] == [a["id"], b["id"]]
    spaces.delete(b["id"])
    assert [m.id for m in spaces.list_recent()] == [a["id"]]
    with pytest.raises(spaces.SpaceError):
        spaces.delete(b["id"])


def test_ids_are_validated_before_touching_the_filesystem():
    for bad in ("../conversations/x", "", "not-hex", "ABCDEF123456"):
        with pytest.raises(spaces.SpaceError):
            spaces.get(bad)
        with pytest.raises(spaces.SpaceError):
            spaces.post(bad, "a", "b")
