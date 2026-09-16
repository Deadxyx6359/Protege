"""The network, through one door (C1).

`fetch` is the one way Akira reaches the network, `call` the one way a
connected account's sign-in is carried there (C5), and `tunnel` the one way a
browser's connection is made (C3). The rules every request is held to are in
`client`, the only module allowed to connect.
"""

from .client import (MAX_BYTES, MAX_REDIRECTS, TIMEOUT_S, NetError, Response, call, fetch,
                     fetchable, host_of, is_public, query_value, redact, split_sign_in, tunnel,
                     with_query)

__all__ = ["MAX_BYTES", "MAX_REDIRECTS", "TIMEOUT_S", "NetError", "Response", "call", "fetch",
           "fetchable", "host_of", "is_public", "query_value", "redact", "split_sign_in", "tunnel",
           "with_query"]
