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


def issue_text(issue: dict[str, Any] | None) -> str:
    """One callout line, in the rule catalogue's words. Em dash when there is nothing."""
    if not issue:
        return EM_DASH
    label = issue.get("label") or issue.get("rule_id") or ""
    return str(label)


def percentage(value: float | None) -> str:
    return EM_DASH if value is None else f"{value:.1f}%"


def dimension_score(summary: dict[str, Any], dimension: str) -> float | None:
    """Read one dimension's score out of the summary envelope.

    Averaged across slices when a contract holds more than one frequency, because the tile is
    a book-level headline. The per-contract answer is in `contracts[]`, which does not average.
    """
    scores = [
        slice_["dimensions"][dimension]["score"]
        for slice_ in summary.get("slices", [])
        if dimension in slice_.get("dimensions", {})
    ]
    return round(sum(scores) / len(scores), 1) if scores else None
