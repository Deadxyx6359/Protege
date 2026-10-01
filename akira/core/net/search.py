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

**The whole web, with a key (2026-09-30).** DuckDuckGo turned every search
away, and Wikipedia is one site. The person chose a search service that covers
the whole web: Tavily, whose free plan is 1,000 searches a month and takes no
card. With its key added (sealed with DPAPI, `TAVILY_SECRET`), a search goes
there first, under the same `web.search`, through `client.call` to Tavily's
own host and nowhere else; the key goes only in its header and never into a
prompt or the log. Akira makes at most `MONTHLY_LIMIT` searches there a month,
inside the free plan, so a key on a paid plan is not run up unseen. When it
fails, or the month's searches are used, DuckDuckGo is tried as before.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import date
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path

from akira.core.permissions.secrets import SecretError

from .client import NetError, call, fetch, query_value, with_query

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
    """`result`, from the results page, `instant`, from the Instant Answer API,
    `wikipedia`, from Wikipedia's own search when DuckDuckGo gave nothing, or
    `tavily`, from the whole-web search the person added a key for."""


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


# -- the whole web, through Tavily, with the person's key ------------------------------------------

TAVILY_HOST = "api.tavily.com"
TAVILY_URL = f"https://{TAVILY_HOST}/search"
#: Where the key is kept, sealed (`SecretStore`).
TAVILY_SECRET = "search.tavily"
#: What a Tavily key looks like.
_TAVILY_KEY = re.compile(r"tvly-[A-Za-z0-9_-]{8,200}")
#: Searches a month Akira makes there: inside the free plan's 1,000.
MONTHLY_LIMIT = 950
TAVILY_RESULTS = 8
#: How much of a result's text is kept.
MAX_SNIPPET = 600


def tavily_key(text: str) -> str:
    """\a text as a Tavily key, or "" when it is not one. Spaces around it are let go."""
    key = str(text or "").strip()
    return key if _TAVILY_KEY.fullmatch(key) else ""


def has_whole_web(secrets) -> bool:
    """Whether a key for the whole-web search has been added."""
    return secrets is not None and secrets.has(TAVILY_SECRET)


class Usage:
    """How many whole-web searches were made this month, in `search_usage.json`.

    Counted here, on this computer, so the limit holds whatever the service's
    own plan would allow.
    """

    def __init__(self, path: Path | None = None) -> None:
        from akira.core.config import config_dir

        self.path = path if path is not None else config_dir() / "search_usage.json"
        self._lock = threading.Lock()

    @staticmethod
    def _month() -> str:
        return date.today().strftime("%Y-%m")

    def used(self) -> int:
        """Searches made this month."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(data, dict) or data.get("month") != self._month():
            return 0
        count = data.get("tavily")
        return count if isinstance(count, int) and count >= 0 else 0

    def counted(self) -> int:
        """Count one search. The count after it."""
        from akira.core import files

        with self._lock:
            count = self.used() + 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump({"month": self._month(), "tavily": count}, stream)
                files.replace(temporary, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
                raise
            return count


_TAVILY_REFUSED = {
    401: "Tavily refused the key. Check it, or add it again, in Settings, Accounts, Search.",
    403: "Tavily refused the key. Check it, or add it again, in Settings, Accounts, Search.",
    429: "Tavily asked for fewer searches at once.",
    432: "Tavily says this key's searches for the month are used up.",
    433: "Tavily says this key's searches for the month are used up.",
}


def tavily(words: str, *, policy, secrets, audit=None, actor: str = "assistant",
           usage: Usage | None = None) -> list[Hit]:
    """Results for \a words from the whole web, through Tavily. Raises `SearchError`."""
    usage = usage if usage is not None else Usage()
    if usage.used() >= MONTHLY_LIMIT:
        raise SearchError(f"Akira has made its {MONTHLY_LIMIT} whole-web searches for this "
                          "month, which keeps inside Tavily's free plan.")
    try:
        response = call("POST", TAVILY_URL, policy=policy, capability="web.search", scope="",
                        hosts=(TAVILY_HOST,), audit=audit, actor=actor,
                        bearer=lambda: secrets.get(TAVILY_SECRET),
                        payload={"query": words, "max_results": TAVILY_RESULTS,
                                 "search_depth": "basic"},
                        max_bytes=MAX_INSTANT_BYTES)
    except NetError as exc:
        raise SearchError(str(exc)) from None
    except SecretError:
        raise SearchError("No Tavily key has been added, or it could not be unsealed.") from None
    if not response.ok:
        raise SearchError(_TAVILY_REFUSED.get(
            response.status, f"Tavily answered {response.status} {response.reason}."))
    usage.counted()
    try:
        data = json.loads(response.text())
    except ValueError:
        raise SearchError("Tavily's answer could not be read.") from None
    found = data.get("results") if isinstance(data, dict) else None
    hits: list[Hit] = []
    for item in found if isinstance(found, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = " ".join(str(item.get("title") or url).split())[:200]
        if not url.startswith("https://") or url in {hit.url for hit in hits}:
            continue
        hits.append(Hit(title, url, " ".join(str(item.get("content") or "").split())[:MAX_SNIPPET],
                        "tavily"))
        if len(hits) >= MAX_RESULTS:
            break
    return hits


def search(query: str, *, policy, audit=None, actor: str = "assistant",
           secrets=None) -> list[Hit]:
    """Results for \a query: the whole web through Tavily when its key was added
    (\a secrets), else DuckDuckGo. Raises `SearchError` with a reason."""
    words = " ".join((query or "").split())
    if not words:
        raise SearchError("Give something to search for.")
    if len(words) > MAX_QUERY_CHARS:
        raise SearchError(f"A search is at most {MAX_QUERY_CHARS} characters.")
    whole_web = ""
    if has_whole_web(secrets):
        try:
            return tavily(words, policy=policy, secrets=secrets, audit=audit, actor=actor)
        except SearchError as exc:
            # Said with whatever DuckDuckGo then says, if it fails too.
            whole_web = f"{exc} "
    try:
        return _duckduckgo(words, policy=policy, audit=audit, actor=actor)
    except SearchError as exc:
        raise SearchError(f"{whole_web}{exc}") from None


def _duckduckgo(words: str, *, policy, audit, actor: str) -> list[Hit]:
    global _last
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
