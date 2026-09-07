"""Shared page state: which client to talk to, and small display conversions.

The client is resolved through `get_client()` rather than constructed at each call site, so
`streamlit.testing.v1.AppTest` can put a stub in front of the pages with `use_client()`. That
is the whole reason done-when 3 kept the API behind one module — the seam has to be somewhere
a test can reach.

Display conversions live here because they are the *only* transformation `ui` is allowed to
do: rendering a null as an em dash is presentation, and anything that changes a number is not.
"""

from __future__ import annotations

from .client import LoupeClient

#: An unset cell. `specs/loupe-ui-design.md` uses it for "nothing to say here", which is not
#: the same as zero and not the same as missing data.
EM_DASH = "—"

_client: LoupeClient | None = None


def use_client(client: LoupeClient | None) -> None:
    """Point the pages at a client. Tests pass a stub; `None` restores the default."""
    global _client
    _client = client


def get_client() -> LoupeClient:
    """The client the pages talk through — a stub under test, `LOUPE_API_URL` otherwise."""
    return _client if _client is not None else LoupeClient()
