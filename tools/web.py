"""Web tools: search and fetch public pages so the agent can research and
stay current. Stdlib only (urllib + html.parser) — no new dependency.

This is the ONLY place the app talks to the public internet for content,
and it never runs inference there (the no-cloud-API rule is about models).
Search tries backends in order and the first that returns results wins:
a self-hosted SearXNG instance when SEARXNG_URL is set (JSON API, the
robust option), then DuckDuckGo's HTML endpoint (verified 2026-09-15:
results are <a class="result__a" href="//duckduckgo.com/l/?uddg=<encoded
target>"> with <a class="result__snippet"> — but it rate-limits and serves
a bot challenge readily, so it is best-effort only), then Wikipedia's
search API (always works, narrower coverage). The result says which
backend answered so the model can weigh it. All of it is disabled by
ENABLE_WEB_TOOLS=false (config.web_tools_enabled), in which case agent.py
doesn't advertise these tools at all.

Every failure is returned as a readable string, never raised — the model
should see "search unavailable: ..." and carry on with local documents.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import config

_USER_AGENT = "Mozilla/5.0 (local-ai-assistant; +https://localhost)"
_TIMEOUT_SECONDS = 15
_MAX_FETCH_CHARS = 8000


def _get(url: str, headers: dict | None = None) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read()


class _DuckDuckGoParser(HTMLParser):
    """Collects (title, url, snippet) triples from the HTML results page."""

    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self._current: dict | None = None
        self._capture: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if "result__a" in classes:
            self._current = {
                "title": "",
                "url": _unwrap(attrs.get("href", "")),
                "snippet": "",
            }
            self._capture = "title"
        elif "result__snippet" in classes and self._current is not None:
            self._capture = "snippet"

    def handle_data(self, data):
        if self._current is not None and self._capture:
            self._current[self._capture] += data

    def handle_endtag(self, tag):
        if tag != "a" or self._current is None or not self._capture:
            return
        if self._capture == "snippet":
            self.results.append(self._current)
            self._current = None
        self._capture = None


def _unwrap(href: str) -> str:
    """DuckDuckGo wraps targets as //duckduckgo.com/l/?uddg=<encoded>."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def _search_searxng(base_url: str, query: str, max_results: int) -> list[dict]:
    url = f"{base_url.rstrip('/')}/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json"}
    )
    data = json.loads(_get(url).decode("utf-8", "replace"))
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in data.get("results", [])[:max_results]
    ]


def _search_duckduckgo(query: str, max_results: int) -> list[dict]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    html = _get(url).decode("utf-8", "replace")
    if "bots use DuckDuckGo too" in html:
        raise WebBackendError("DuckDuckGo served a bot challenge")
    parser = _DuckDuckGoParser()
    parser.feed(html)
    return parser.results[:max_results]


def _search_wikipedia(query: str, max_results: int) -> list[dict]:
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": max_results,
        }
    )
    data = json.loads(_get(url).decode("utf-8", "replace"))
    results = []
    for hit in data.get("query", {}).get("search", []):
        title = hit.get("title", "")
        results.append(
            {
                "title": title,
                "url": "https://en.wikipedia.org/wiki/"
                + urllib.parse.quote(title.replace(" ", "_")),
                "snippet": re.sub(r"<[^>]+>", "", hit.get("snippet", "")),
            }
        )
    return results


class WebBackendError(Exception):
    """A search backend answered, but not with results."""


def _backends() -> list[tuple[str, object]]:
    backends: list[tuple[str, object]] = []
    searxng = config.get_searxng_url()
    if searxng:
        backends.append(("searxng", lambda q, n: _search_searxng(searxng, q, n)))
    backends.append(("duckduckgo", _search_duckduckgo))
    backends.append(("wikipedia", _search_wikipedia))
    return backends


def search(query: str, max_results: int = 5) -> str:
    """Search the web; return numbered title/url/snippet blocks, prefixed by
    which backend answered. Backends are tried in order (module docstring);
    every failure is recorded and reported only if all of them fail."""
    if not config.web_tools_enabled():
        return "Web tools are disabled (ENABLE_WEB_TOOLS=false)."
    max_results = max(1, min(int(max_results or 5), 10))
    failures = []
    for name, backend in _backends():
        try:
            results = backend(query, max_results)
        except (
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            WebBackendError,
        ) as exc:
            failures.append(f"{name}: {exc}")
            continue
        if results:
            blocks = "\n\n".join(
                f"[{i}] {r['title'].strip()}\n{r['url']}\n{r['snippet'].strip()}"
                for i, r in enumerate(results, 1)
            )
            return f"Web search via {name}:\n\n{blocks}"
        failures.append(f"{name}: no results")
    return "Web search unavailable — " + "; ".join(failures)


class _TextExtractor(HTMLParser):
    """Drops script/style/nav noise and keeps visible text, one block per
    tag that normally starts a line."""

    _SKIP = {"script", "style", "noscript", "svg", "head"}
    _BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)


def fetch(url: str, max_chars: int = _MAX_FETCH_CHARS) -> str:
    """Fetch a page and return its title plus visible text (truncated)."""
    if not config.web_tools_enabled():
        return "Web tools are disabled (ENABLE_WEB_TOOLS=false)."
    if not re.match(r"^https?://", url or ""):
        return f"Refusing to fetch non-http(s) URL: {url!r}"
    try:
        raw = _get(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return f"Fetch failed for {url}: {exc}"
    extractor = _TextExtractor()
    extractor.feed(raw.decode("utf-8", "replace"))
    text = re.sub(r"[ \t]+", " ", "".join(extractor.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated, {len(text)} chars total]"
    title = extractor.title.strip()
    return f"Title: {title}\nURL: {url}\n\n{text}" if title else f"URL: {url}\n\n{text}"
