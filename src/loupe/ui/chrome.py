"""Shared chrome: persona, trade dates, upload. The same page for every persona.

The sidebar is the whole of the page's input surface (`specs/loupe-ui-design.md`). Persona is
a **view selector** and nothing more — it changes which columns and panels are drawn, never
which records are readable. The API is not persona-aware (`specs/api-contract.md` §8), so
switching persona here re-renders and does not re-authorise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import streamlit as st

from .client import ApiProblem, ApiUnavailable, LoupeClient

PERSONAS = ("Risk", "Trader", "Analyst")

#: What each persona came to ask (`specs/loupe-ui-design.md`, motivations).
PRIMARY_QUESTION = {
    "Risk": "Is settlement trustworthy, and how much of the book is hit?",
    "Trader": "Is this series usable for charts and backtests?",
    "Analyst": "What is broken, and should we cleanse or keep it?",
}


@dataclass(frozen=True)
class SidebarState:
    persona: str
    start: date | None
    end: date | None


def render_sidebar(client: LoupeClient) -> SidebarState:
    """Persona, trade dates and upload, in that order."""
    st.sidebar.title("LOUPE")

    persona = st.sidebar.radio("Persona", PERSONAS, key="persona")
    st.sidebar.caption(PRIMARY_QUESTION[persona])

    st.sidebar.markdown("---")
    st.sidebar.subheader("Trade dates")
    start = st.sidebar.date_input("From", value=None, key="start", format="YYYY-MM-DD")
    end = st.sidebar.date_input("To", value=None, key="end", format="YYYY-MM-DD")

    st.sidebar.markdown("---")
    render_upload(client)

    return SidebarState(
        persona=persona,
        start=start if isinstance(start, date) else None,
        end=end if isinstance(end, date) else None,
    )


def render_upload(client: LoupeClient) -> None:
    """File → preview and capability disclosure → confirm → progress → dashboard updates.

    The preview is not a formality. It is where the user learns what the file *cannot* do
    before committing it — a daily-only file yields bars and quality but no 15-minute VWAP —
    and `specs/api-contract.md` §4.2 makes that disclosure the point of the endpoint.
    """
    st.sidebar.subheader("Upload files")
    upload = st.sidebar.file_uploader(
        "CSV or Parquet", type=("csv", "parquet"), key="upload"
    )
    if upload is None:
        return

    content = upload.getvalue()
    try:
        preview = client.preview(upload.name, content)
    except ApiUnavailable as exc:
        st.sidebar.error(str(exc))
        return
    except ApiProblem as problem:
        st.sidebar.error(f"{problem.title}: {problem}")
        return

    render_preview(preview)

    if st.sidebar.button("Confirm upload", key="confirm-upload", type="primary"):
        # Ingest is synchronous by decision (§4.4): Streamlit has no server push, and at this
        # scale a job table buys nothing. `st.status` wraps the blocking call so the user sees
        # progress rather than a frozen page.
        with st.status("Loading and validating…", expanded=True) as status:
            try:
                batch = client.create_batch(upload.name, content)
            except ApiProblem as problem:
                status.update(label=problem.title, state="error")
                st.write(str(problem))
                return
            except ApiUnavailable as exc:
                status.update(label="No answer from the API", state="error")
                st.write(str(exc))
                return
            status.update(label="Loaded", state="complete")
        st.session_state["last_batch"] = batch.get("batch_id")
        st.rerun()


#: `enables` keys, in the reader's words rather than the wire's.
_CAPABILITY_NAMES = {
    "daily_bars": "Daily OHLCV bars",
    "vwap_15m": "Rolling 15-minute VWAP",
    "reconciliation": "Cross-frequency reconciliation",
}


def render_preview(preview: dict[str, Any]) -> None:
    """The dry run, capabilities included — what this file will and will not support."""
    st.sidebar.caption("Preview")
    frequency = (preview.get("inferred_frequency") or {}).get("value") or "?"
    st.sidebar.write(
        f"{preview.get('rows_total', 0):,} rows · {preview.get('file_format', '?')} · "
        f"{frequency}"
    )
    contracts = preview.get("contracts_detected") or []
    if contracts:
        st.sidebar.caption(", ".join(contracts[:6]) + (" …" if len(contracts) > 6 else ""))

    # `enables` is the point of the endpoint (§4.2): a daily-only upload learns that VWAP is
    # unavailable *before* it commits, rather than meeting an empty panel afterwards.
    for key, capability in (preview.get("enables") or {}).items():
        name = _CAPABILITY_NAMES.get(key, key)
        if capability.get("available"):
            st.sidebar.markdown(f"✅ {name}")
        else:
            reason = capability.get("reason") or "not available for this file"
            st.sidebar.markdown(f"🚫 **{name}** — {reason}")

    if preview.get("verdict") == "duplicate":
        st.sidebar.warning(
            f"These exact bytes are already loaded as batch {preview.get('already_ingested')}."
        )
    for warning in preview.get("warnings") or []:
        st.sidebar.warning(warning)

    companion = companion_grain(preview)
    if companion:
        st.sidebar.info(companion)


#: `specs/loupe-solution-design.md` §2, "Advise Risk users to load both grains". Advice, not a
#: gate: each file is fully usable on its own terms, and the message names what the second one
#: would add rather than what this one lacks. The daily case is the one the advice targets —
#: a daily file can only be checked against itself, and settlement is the Risk question.
_COMPANION = {
    "daily": "**Add the minute tape to corroborate settlement.** A daily file can only be "
    "checked against itself — inside the bar range, on the tick, not duplicated. Reconciling "
    "it against the tape is what catches a settlement that is self-consistent and still "
    "wrong. It is also the Trader's series.",
    "minute": "**Add the daily file to bring settlement into scope.** The tape already gives "
    "bars, VWAP and quality on its own; the daily file is the Risk manager's grain, and "
    "holding both lets the two be reconciled.",
}


def companion_grain(preview: dict[str, Any]) -> str | None:
    """Recommend the other grain when reconciliation is not possible for this upload.

    Keyed off `enables.reconciliation`, which the API already computes and explains — the
    preview knows whether the other granularity is present for these contracts, so the UI
    reads that answer instead of asking a second question or inventing its own.

    Not a refusal and not a warning: a single-grain upload is valid and scoreable. This is a
    statement of what the second file would buy, made at the moment the reader is deciding
    which files to load.
    """
    reconciliation = (preview.get("enables") or {}).get("reconciliation") or {}
    if reconciliation.get("available") is not False:
        return None
    frequency = (preview.get("inferred_frequency") or {}).get("value")
    return _COMPANION.get(frequency)


def render_header(persona: str) -> None:
    st.title("Loupe")
    st.caption(PRIMARY_QUESTION[persona])
