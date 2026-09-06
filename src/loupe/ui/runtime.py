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


def scope_disclosure(summary: dict[str, Any]) -> tuple[str, list[str]] | None:
    """What a score was measured over, and which dimensions were missing from it.

    `specs/dq-rules-and-scoring.md` §11.3: a six-dimension score is better evidenced than a
    five-dimension one and is **not the same measurement**, so every surface that shows a
    score has to say which it is. Returns the scope signature and the human reasons any
    dimension was out of scope, or `None` when nothing is missing.

    Reads what the envelope already decided — `scope_signature` and `dimensions_not_in_scope`
    are composed in `quality` and carried on every slice.
    """
    slices = summary.get("slices", [])
    if not slices:
        return None
    signatures = sorted({s.get("scope_signature", "") for s in slices if s.get("scope_signature")})
    reasons: list[str] = []
    for slice_ in slices:
        for missing in slice_.get("dimensions_not_in_scope") or []:
            reason = missing.get("reason") or f"{missing.get('dimension')} not in scope"
            if reason not in reasons:
                reasons.append(reason)
    if not reasons:
        return None
    return (" / ".join(signatures), reasons)


#: Why the missing dimension matters, per persona. Risk gets the sharp version: the settlement
#: question is the one reconciliation exists to answer (`specs/loupe-solution-design.md` §2,
#: "Load both grains").
_SCOPE_CONSEQUENCE = {
    "Risk": "Settlement is being judged on the daily file's internal consistency alone — "
    "load the minute tape to reconcile it.",
    "Trader": "Cross-frequency checks did not run for every contract here.",
    "Analyst": "Scores with different signatures are not directly comparable.",
}


def score_disclosure_text(summary: dict[str, Any], persona: str) -> str | None:
    """One line under the headline: what the score covered, and what it therefore cannot say."""
    disclosure = scope_disclosure(summary)
    if disclosure is None:
        return None
    signature, reasons = disclosure
    consequence = _SCOPE_CONSEQUENCE.get(persona, _SCOPE_CONSEQUENCE["Analyst"])
    reason = reasons[0].rstrip(". ")
    return f"Scored over `{signature}` · {reason}. {consequence}"


#: Marks a score measured over fewer dimensions than its neighbours in the same table.
REDUCED_SCOPE_MARK = "†"


def reduced_scope_contracts(summary: dict[str, Any]) -> set[str]:
    """Contracts whose score covers fewer dimensions than the best-evidenced one in scope.

    §11.3 draws the line at comparability: equal `scope_signature` means two scores are
    comparable, unequal means the page must say so. A headline caption is enough when every
    contract shares a signature — the limitation is absolute and applies to all of them. It is
    *not* enough when they differ, because the inventory then puts a five-dimension number and
    a six-dimension one in the same column, sorted against each other, looking equally
    authoritative.

    Returns an empty set when every contract was measured over the same dimensions, so the
    mark never appears where it would be noise.
    """
    by_contract: dict[str, str] = {}
    for slice_ in summary.get("slices", []):
        signature = slice_.get("scope_signature")
        contract = slice_.get("contract_id")
        if not signature or not contract:
            continue
        # A contract's slices share a signature; keep the widest if they ever disagree.
        if len(signature) > len(by_contract.get(contract, "")):
            by_contract[contract] = signature
    if len(set(by_contract.values())) < 2:
        return set()
    fullest = max(by_contract.values(), key=lambda s: (s.count("+"), s))
    return {c for c, s in by_contract.items() if s != fullest}
