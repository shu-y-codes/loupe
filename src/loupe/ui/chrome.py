"""Shared chrome: persona and trade dates. The same page for every persona.

The sidebar is the whole of the page's input surface (`specs/loupe-ui-design.md`). Persona is
a **view selector** and nothing more — it changes which columns and panels are drawn, never
which records are readable. The API is not persona-aware (`specs/api-contract.md` §8), so
switching persona here re-renders and does not re-authorise.

Demo ingest and the ingested-file list live in `demo.py`, next to the button that produces
them. There is no file uploader.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import streamlit as st

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


def render_sidebar() -> SidebarState:
    """Persona and trade dates. Demo ingest sits in `render_demo`, under this."""
    st.sidebar.title("LOUPE")

    persona = st.sidebar.radio("Persona", PERSONAS, key="persona")
    st.sidebar.caption(PRIMARY_QUESTION[persona])

    st.sidebar.markdown("---")
    st.sidebar.subheader("Trade dates")
    start = st.sidebar.date_input("From", value=None, key="start", format="YYYY-MM-DD")
    end = st.sidebar.date_input("To", value=None, key="end", format="YYYY-MM-DD")

    st.sidebar.markdown("---")
    return SidebarState(
        persona=persona,
        start=start if isinstance(start, date) else None,
        end=end if isinstance(end, date) else None,
    )


def render_header(persona: str) -> None:
    st.title("Loupe")
    st.caption(PRIMARY_QUESTION[persona])
