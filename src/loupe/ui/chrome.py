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


def render_preview(preview: dict[str, Any]) -> None:
    """The dry run, capabilities included — what this file will and will not support."""
    st.sidebar.caption("Preview")
    st.sidebar.write(
        f"{preview.get('rows_total', 0):,} rows · {preview.get('file_format', '?')}"
    )
    for capability in preview.get("capabilities", []) or []:
        name = capability.get("capability") or capability.get("name") or "capability"
        if capability.get("available"):
            st.sidebar.markdown(f"✅ {name}")
        else:
            reason = capability.get("reason") or "not available for this file"
            st.sidebar.markdown(f"🚫 **{name}** — {reason}")
    rejects = preview.get("rejects_estimated") or preview.get("rejects") or 0
    if rejects:
        st.sidebar.warning(f"{rejects} row(s) would be rejected at load.")


def render_header(persona: str) -> None:
    st.title("Loupe")
    st.caption(PRIMARY_QUESTION[persona])
