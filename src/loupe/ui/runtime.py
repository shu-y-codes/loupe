"""Shared page state: which client to talk to, and small display conversions.

The client is resolved through `get_client()` rather than constructed at each call site, so
`streamlit.testing.v1.AppTest` can put a stub in front of the pages with `use_client()`. That
is the whole reason done-when 3 kept the API behind one module — the seam has to be somewhere
a test can reach.

Display conversions live here because they are the *only* transformation `ui` is allowed to
do: rendering a null as an em dash is presentation, and anything that changes a number is not.
"""

from __future__ import annotations

from typing import Any

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


def score_text(score: float | None) -> str:
    """A score, or an em dash. Never `0` for absent: zero is the worst possible score."""
    return EM_DASH if score is None else f"{score:g}"


def checks_score_caption(checks: dict[str, Any]) -> str:
    """The trust line under the four cards (`specs/loupe-ui-design.md`, Score caption).

    `scope_signature` still travels with the number. When reconciliation is out of scope the
    line names the missing companion grain and the consequence — settlement judged on the
    daily file alone. There is no inventory, so nothing is dagger-marked against a neighbour.
    """
    checked = bool(checks.get("checked"))
    raw = checks.get("score")
    score_bit = (
        score_text(raw)
        if raw is not None
        else ("insufficient data" if checked else EM_DASH)
    )
    parts = [f"Score {score_bit}"]
    signature = checks.get("scope_signature")
    if signature:
        parts.append(f"`{signature}`")
    line = " · ".join(parts)
    missing = checks.get("dimensions_not_in_scope") or []
    if missing:
        reason = (missing[0].get("reason") or "a dimension is out of scope").rstrip(". ")
        consequence = (
            "Settlement is being judged on the daily file's internal consistency alone — "
            "load the minute tape to reconcile it."
        )
        return f"{line} · {reason}. {consequence}"
    return f"{line}. Zero on a card means the check ran."
