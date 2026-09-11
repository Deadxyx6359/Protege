"""The network, through one door (C1).

`fetch` is the one way Protégé reaches the network. The rules every request is
held to are in `client`, the only module allowed to import the network.
"""

from .client import (MAX_BYTES, MAX_REDIRECTS, TIMEOUT_S, NetError, Response, fetch, host_of,
                     is_public, redact)

__all__ = ["MAX_BYTES", "MAX_REDIRECTS", "TIMEOUT_S", "NetError", "Response", "fetch",
           "host_of", "is_public", "redact"]
