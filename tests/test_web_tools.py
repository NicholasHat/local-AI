"""tools/web.py — parsing and fallback logic, no network."""

import urllib.error

import config
from tools import web

_DDG_PAGE = """
<html><body>
<a class="result__a"
   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=1">Result A</a>
<a class="result__snippet" href="#">Snippet A</a>
<a class="result__a" href="https://example.com/b">Result B</a>
<a class="result__snippet" href="#">Snippet B</a>
</body></html>
"""


def test_duckduckgo_parser_unwraps_redirects():
    parser = web._DuckDuckGoParser()
    parser.feed(_DDG_PAGE)
    assert parser.results == [
        {"title": "Result A", "url": "https://example.com/a", "snippet": "Snippet A"},
        {"title": "Result B", "url": "https://example.com/b", "snippet": "Snippet B"},
    ]


def test_search_falls_back_to_next_backend(monkeypatch):
    calls = []

    def fake_get(url, headers=None):
        calls.append(url)
        if "duckduckgo" in url:
            raise urllib.error.URLError("rate limited")
        return (
            b'{"query": {"search": [{"title": "Qwen", '
            b'"snippet": "<b>Qwen</b> is a model"}]}}'
        )

    monkeypatch.setattr(web, "_get", fake_get)
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    out = web.search("qwen", 3)
    assert out.startswith("Web search via wikipedia:")
    assert "https://en.wikipedia.org/wiki/Qwen" in out
    assert "<b>" not in out
    assert any("duckduckgo" in c for c in calls)


def test_search_reports_all_failures(monkeypatch):
    def fake_get(url, headers=None):
        raise TimeoutError("slow")

    monkeypatch.setattr(web, "_get", fake_get)
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    out = web.search("x")
    assert out.startswith("Web search unavailable")
    assert "duckduckgo: slow" in out and "wikipedia: slow" in out


def test_bot_challenge_is_treated_as_failure(monkeypatch):
    monkeypatch.setattr(
        web, "_get", lambda url, headers=None: b"bots use DuckDuckGo too"
    )
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    out = web.search("x")
    assert "bot challenge" in out


def test_searxng_preferred_when_configured(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searx.local")
    monkeypatch.setattr(
        web,
        "_get",
        lambda url, headers=None: (
            b'{"results": [{"title": "T", "url": "http://u", "content": "C"}]}'
            if url.startswith("http://searx.local/search?")
            else b""
        ),
    )
    out = web.search("q")
    assert out.startswith("Web search via searxng:") and "http://u" in out


def test_fetch_extracts_visible_text(monkeypatch):
    page = b"""<html><head><title>My Page</title><style>x{}</style></head>
    <body><script>alert(1)</script><h1>Hello</h1><p>World  here</p></body></html>"""
    monkeypatch.setattr(web, "_get", lambda url, headers=None: page)
    out = web.fetch("https://example.com")
    assert out.startswith("Title: My Page")
    assert "Hello" in out and "World here" in out
    assert "alert" not in out and "x{}" not in out


def test_fetch_rejects_non_http():
    assert web.fetch("file:///etc/passwd").startswith("Refusing")


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("ENABLE_WEB_TOOLS", "false")
    assert not config.web_tools_enabled()
    assert "disabled" in web.search("q")
    assert "disabled" in web.fetch("https://x")
