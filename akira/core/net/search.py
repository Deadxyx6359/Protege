"""Searching the web, on DuckDuckGo (C2).

The person chose DuckDuckGo. Its plain HTML results page needs no account and
no key, and a search is one GET through the chokepoint like any page.

**Its own permission.** `web.search` sends the query to DuckDuckGo and to
nobody else: the chokepoint is told to reach only DuckDuckGo's host under it,
and a redirect anywhere else is refused, whatever `net.http` allows. Reading a
result is a separate `fetch_page`, under `net.http` for that result's site,
which the person decides on separately.

**What is kept.** The chokepoint logs the request without its query string, so
the words searched for are not written there by it.

**Polite.** One search at a time, at least `MIN_INTERVAL_S` apart. When
DuckDuckGo asks whether a person is searching, the answer is "try again
later": a check that people are people is not something to get past.

**Instant answers.** That check came back on every search Akira made. It says
honestly what it is (`client.USER_AGENT`), and it is not disguised to get
round it. DuckDuckGo publishes a second, programmatic interface, its Instant
Answer API, which answers programs without asking. When the results page asks,
the query goes there instead. It is still DuckDuckGo, still under
`web.search`, and gets fewer results: a summary with its source, usually
Wikipedia, a definition, and official sites. The tool says which it was.

**Wikipedia's own search.** A question phrased as a question often has no
instant answer, and one afternoon every research question came back with
nothing and was answered from memory. When the person allows reading
Wikipedia (`net.http`), the `web_search` tool then asks Wikipedia's search
(`wikipedia`): a page on a site already allowed, the same one agents were told
they could open themselves, and did not.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from html import unescape as html_unescape
from html.parser import HTMLParser

from .client import NetError, fetch, query_value, with_query

SEARCH_HOST = "html.duckduckgo.com"
SEARCH_URL = f"https://{SEARCH_HOST}/html/"
INSTANT_HOST = "api.duckduckgo.com"
INSTANT_URL = f"https://{INSTANT_HOST}/"
MAX_INSTANT_BYTES = 512 * 1024
MAX_RESULTS = 10
MAX_QUERY_CHARS = 300
MIN_INTERVAL_S = 2.0

_lock = threading.Lock()
_last = 0.0


class SearchError(RuntimeError):
    """A search that could not be made, with a reason for the person."""


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    snippet: str
    kind: str = "result"
    """`result`, from the results page, `instant`, from the Instant Answer API, or
    `wikipedia`, from Wikipedia's own search when DuckDuckGo gave nothing."""


class _Results(HTMLParser):
    """The organic results on DuckDuckGo's HTML page, adverts left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[dict] = []
        self.challenged = False
        self._field = ""
        self._advert = False

    def handle_starttag(self, tag, attrs) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if "anomaly-modal" in classes or values.get("id") == "challenge-form":
            self.challenged = True
        if tag == "div" and "result" in classes:
            self._advert = "result--ad" in classes
            if not self._advert:
                self.hits.append({"title": "", "url": "", "snippet": ""})
        if self._advert or not self.hits or tag != "a":
            return
        if "result__a" in classes:
            self._field = "title"
            self.hits[-1]["url"] = values.get("href") or ""
        elif "result__snippet" in classes:
            self._field = "snippet"

    def handle_endtag(self, tag) -> None:
        if tag == "a":
            self._field = ""

    def handle_data(self, data) -> None:
        if self._field and self.hits and not self._advert:
            self.hits[-1][self._field] += data


def _target(href: str) -> str:
    """Where a result really goes: DuckDuckGo wraps it in its own redirect."""
    address = href.strip()
    if address.startswith("//"):
        address = "https:" + address
    if "duckduckgo.com/l/" in address:
        address = query_value(address, "uddg")
    return address if address.startswith(("https://", "http://")) else ""


def _instant(words: str, *, policy, audit, actor: str) -> list[Hit]:
    """What DuckDuckGo's Instant Answer API has for \a words; [] for nothing or a failure.

    It answers "202 Accepted" with a whole answer in the body, so the body is
    what is read, not the status. Only sources off DuckDuckGo are kept: its
    topic pages are its own and no site the person allowed.
    """
    with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_time())
        if wait > 0:
            time.sleep(wait)
        try:
            response = fetch(with_query(INSTANT_URL, {"q": words, "format": "json",
                                                      "no_html": "1", "skip_disambig": "1"}),
                             policy=policy, audit=audit, actor=actor, capability="web.search",
                             hosts=(INSTANT_HOST,), max_bytes=MAX_INSTANT_BYTES)
        except NetError:
            return []
        finally:
            _mark()
    try:
        data = json.loads(response.text())
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    hits: list[Hit] = []

    def add(title, url, snippet) -> None:
        url = str(url or "").strip()
        if (url.startswith("https://") and "duckduckgo.com" not in url.split("/")[2]
                and url not in {hit.url for hit in hits}):
            hits.append(Hit(" ".join(str(title or url).split())[:200], url,
                            " ".join(str(snippet or "").split())[:600], "instant"))

    source = data.get("AbstractSource") or ""
    add(f"{data.get('Heading') or words} ({source})" if source else data.get("Heading"),
        data.get("AbstractURL"), data.get("AbstractText"))
    add(f"{data.get('Heading') or words}: definition ({data.get('DefinitionSource') or ''})",
        data.get("DefinitionURL"), data.get("Definition"))
    for item in data.get("Results") or []:
        if isinstance(item, dict):
            add(item.get("Text"), item.get("FirstURL"), item.get("Text"))
    return hits[:MAX_RESULTS]


def wikipedia_host(policy) -> str:
    """The Wikipedia the person allows reading under `net.http`, or ""."""
    grant = policy.granted("net.http")
    if grant is None:
        return ""
    if policy.allows("net.http", "en.wikipedia.org"):
        return "en.wikipedia.org"
    for scope in grant.scopes:
        host = scope.strip().lower()
        if host.endswith(".wikipedia.org") and policy.allows("net.http", host):
            return host
    return ""


def wikipedia(words: str, *, policy, audit=None, actor: str = "assistant") -> list[Hit]:
    """Wikipedia's own search, when the person allows reading Wikipedia; [] otherwise.

    For when DuckDuckGo asks whether a person is searching, which it did on every
    search one afternoon, so research answered everything from memory. This is
    not `web.search`: it is a page on a site the person allows under `net.http`,
    the same as an agent opening Wikipedia's search page itself, which agents
    were told they could do and did not. Nothing reaches a site not allowed.
    """
    host = wikipedia_host(policy)
    if not host:
        return []
    try:
        response = fetch(with_query(f"https://{host}/w/api.php",
                                    {"action": "query", "list": "search", "srsearch": words,
                                     "format": "json", "srlimit": "8", "utf8": "1"}),
                         policy=policy, audit=audit, actor=actor, capability="net.http",
                         hosts=(host,), max_bytes=MAX_INSTANT_BYTES)
        data = json.loads(response.text()) if response.ok else {}
    except Exception:  # noqa: BLE001 - a second try at a search never breaks the first
        return []
    found = ((data.get("query") or {}).get("search") or []) if isinstance(data, dict) else []
    hits = []
    for item in found:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = " ".join(str(item["title"]).split())
        snippet = re.sub(r"<[^>]+>", "", str(item.get("snippet") or ""))
        hits.append(Hit(f"{title} (Wikipedia)",
                        f"https://{host}/wiki/" + _article(title),
                        " ".join(html_unescape(snippet).split())[:600], "wikipedia"))
    return hits[:MAX_RESULTS]


def _article(title: str) -> str:
    """A Wikipedia title as its address: spaces as underscores, the rest percent-encoded.
    Done here rather than with urllib, which only the chokepoint may import."""
    return "".join(c if c.isascii() and (c.isalnum() or c in "()_,'-.~") else
                   "".join(f"%{b:02X}" for b in c.encode("utf-8"))
                   for c in title.replace(" ", "_"))


def _last_time() -> float:
    return _last


def _mark() -> None:
    global _last
    _last = time.monotonic()


def search(query: str, *, policy, audit=None, actor: str = "assistant") -> list[Hit]:
    """Results for \a query from DuckDuckGo. Raises `SearchError` with a reason."""
    global _last
    words = " ".join((query or "").split())
    if not words:
        raise SearchError("Give something to search for.")
    if len(words) > MAX_QUERY_CHARS:
        raise SearchError(f"A search is at most {MAX_QUERY_CHARS} characters.")
    with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        try:
            response = fetch(with_query(SEARCH_URL, {"q": words}), policy=policy, audit=audit,
                             actor=actor, capability="web.search", hosts=(SEARCH_HOST,))
        except NetError as exc:
            raise SearchError(str(exc)) from None
        finally:
            _last = time.monotonic()
    reader = _Results()
    reader.feed(response.text())
    if response.status in (202, 403, 429) or reader.challenged:
        instant = _instant(words, policy=policy, audit=audit, actor=actor)
        if instant:
            return instant
        raise SearchError("DuckDuckGo asked whether a person is searching, so no results came "
                          "back. Try again in a little while.")
    if not response.ok:
        raise SearchError(f"DuckDuckGo answered {response.status} {response.reason}.")
    hits: list[Hit] = []
    for raw in reader.hits:
        url = _target(raw["url"])
        title = " ".join(raw["title"].split())
        if url and title and url not in {hit.url for hit in hits}:
            hits.append(Hit(title, url, " ".join(raw["snippet"].split())))
        if len(hits) >= MAX_RESULTS:
            break
    return hits
