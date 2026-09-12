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
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser

from .client import NetError, fetch, query_value, with_query

SEARCH_HOST = "html.duckduckgo.com"
SEARCH_URL = f"https://{SEARCH_HOST}/html/"
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
