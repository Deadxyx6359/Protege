"""Granting a site (C1): a grant names a site plainly, and covers its subdomains,
so a bare top-level domain, an address or a wildcard is refused with a reason.
"""

from __future__ import annotations

import pytest

from protege.core.permissions import Policy


@pytest.mark.parametrize("scope,reason", [
    ("com", "every site ending in .com"),
    ("localhost", "every site ending in .localhost"),
    ("https://example.com", "is not a site"),
    ("example.com/path", "is not a site"),
    ("*.example.com", "is not a site"),
    ("user@example.com", "is not a site"),
    ("   ", "is not a site"),
])
def test_a_grant_that_is_not_one_site_is_refused(scope, reason):
    with pytest.raises(ValueError, match=reason):
        Policy().grant("net.http", (scope,))


def test_a_site_is_kept_plainly():
    policy = Policy()
    policy.grant("net.http", (" Example.COM. ", "docs.python.org"))
    assert policy.granted("net.http").scopes == ("example.com", "docs.python.org")
    assert policy.allows("net.http", "api.example.com")
