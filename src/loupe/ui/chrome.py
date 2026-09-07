"""Shared chrome: contract and trade dates. One page, no persona radio.

The sidebar is the whole of the page's input surface (`specs/loupe-ui-design.md` Sidebar).
Demo ingest and the ingested-file list live in `demo.py`, next to the button that produces
them. There is no file uploader.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import streamlit as st


@dataclass(frozen=True)
class SidebarState:
    contract: str | None
    start: date | None
    end: date | None


def render_sidebar(contracts: list[str]) -> SidebarState:
    """Contract picker and trade dates. Demo ingest sits in `render_demo`, under this."""
    st.sidebar.title("Loupe")

    contract: str | None = None
    if contracts:
        current = st.session_state.get("contract")
        if current not in contracts:
            st.session_state.pop("contract", None)
        contract = st.sidebar.selectbox("Contract", contracts, key="contract")
    else:
        st.sidebar.caption("No contracts loaded yet.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Trade dates")
    start = st.sidebar.date_input("From", value=None, key="start", format="YYYY-MM-DD")
    end = st.sidebar.date_input("To", value=None, key="end", format="YYYY-MM-DD")

    st.sidebar.markdown("---")
    return SidebarState(
        contract=contract,
        start=start if isinstance(start, date) else None,
        end=end if isinstance(end, date) else None,
    )


def render_header(state: SidebarState) -> None:
    st.title("Loupe")
    if state.contract:
        window = _window_caption(state.start, state.end)
        st.caption(f"{state.contract} · {window}" if window else state.contract)
    else:
        st.caption("Four checks and two charts on one selected contract.")


def _window_caption(start: date | None, end: date | None) -> str:
    if start and end:
        return f"{start.isoformat()} → {end.isoformat()}"
    if start:
        return f"from {start.isoformat()}"
    if end:
        return f"to {end.isoformat()}"
    return ""
