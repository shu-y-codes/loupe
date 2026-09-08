"""Shared chrome: page switch, contract and trade dates.

The sidebar is the whole of the page's input surface (`specs/loupe-ui-design.md` Sidebar).
Demo ingest and the ingested-file list live in `demo.py`, next to the button that produces
them. There is no file uploader. Overview | Review is not a persona selector.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import streamlit as st

PAGES = ("Overview", "Review")


@dataclass(frozen=True)
class SidebarState:
    contract: str | None
    frequency: str | None
    frequencies_available: tuple[str, ...]
    start: date | None
    end: date | None


def apply_pending_open() -> None:
    """Overview click-through: land on Review with that contract and Quality grain."""
    pending = st.session_state.pop("overview_open", None)
    if not pending:
        return
    contract_id, frequency = pending
    st.session_state["destination"] = "Review"
    st.session_state["destination_display"] = "Review"
    st.session_state["contract"] = contract_id
    st.session_state["quality_grain"] = frequency
    st.session_state["quality_grain_display"] = str(frequency).title()


def render_destination() -> str:
    """Overview | Review under the Loupe title. Default Overview."""
    apply_pending_open()
    st.sidebar.title("Loupe")
    current = st.session_state.get("destination") or "Overview"
    if current not in PAGES:
        current = "Overview"
        st.session_state["destination"] = current
        st.session_state["destination_display"] = current
    if "destination_display" not in st.session_state:
        st.session_state["destination_display"] = current
    selected = st.sidebar.segmented_control(
        "Page",
        list(PAGES),
        key="destination_display",
    )
    destination = str(selected or "Overview")
    st.session_state["destination"] = destination
    return destination


def render_sidebar(
    contracts: list[str],
    frequencies_by_contract: dict[str, list[str]] | None = None,
) -> SidebarState:
    """Contract picker and trade dates. Demo ingest sits in `render_demo`, under this."""
    contract: str | None = None
    if contracts:
        current = st.session_state.get("contract")
        if current not in contracts:
            st.session_state.pop("contract", None)
        contract = st.sidebar.selectbox("Contract", contracts, key="contract")
    else:
        st.sidebar.caption("No contracts loaded yet.")

    available = tuple(
        frequency
        for frequency in ("minute", "daily")
        if frequency in (frequencies_by_contract or {}).get(contract or "", [])
    )
    frequency: str | None = None
    if contract and len(available) > 1:
        current_grain = st.session_state.get("quality_grain")
        if current_grain not in available:
            st.session_state["quality_grain"] = "minute" if "minute" in available else available[0]
        selected = st.sidebar.segmented_control(
            "Quality grain",
            ["Minute", "Daily"],
            key="quality_grain_display",
            default=st.session_state["quality_grain"].title(),
        )
        frequency = str(selected or "Minute").lower()
        st.session_state["quality_grain"] = frequency
    elif contract and available:
        frequency = available[0]
        st.session_state["quality_grain"] = frequency
        st.sidebar.caption(f"Quality grain · {frequency.title()}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Trade dates")
    start = st.sidebar.date_input("From", value=None, key="start", format="YYYY-MM-DD")
    end = st.sidebar.date_input("To", value=None, key="end", format="YYYY-MM-DD")

    st.sidebar.markdown("---")
    return SidebarState(
        contract=contract,
        frequency=frequency,
        frequencies_available=available,
        start=start if isinstance(start, date) else None,
        end=end if isinstance(end, date) else None,
    )


def render_header(state: SidebarState, contract_metadata: dict[str, Any] | None = None) -> None:
    """Review heading: contract context, observed grain coverage, then filtered scope."""
    st.title("Loupe")
    if state.contract:
        parts = [state.contract]
        metadata = contract_metadata or {}
        month = _contract_month_caption(metadata.get("contract_month"))
        if month:
            parts.append(month)
        exchange = str(metadata.get("exchange") or "").strip()
        if exchange:
            parts.append(exchange)
        if state.frequency:
            coverage = _coverage_caption(metadata, state.frequency)
            if coverage:
                parts.append(coverage)
            parts.append(f"{state.frequency.title()} quality grain")
        window = _window_caption(state.start, state.end)
        if window:
            parts.append(window)
        st.caption(" · ".join(parts))
    else:
        st.caption("Four checks and two charts on one selected contract.")


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _human_date(value: Any) -> str | None:
    parsed = _as_date(value)
    return f"{parsed:%b} {parsed.day}, {parsed.year}" if parsed else None


def _contract_month_caption(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(f"{value}-01" if len(value) == 7 else value)
    except ValueError:
        return None
    return f"{parsed:%B} {parsed.year}"


def _coverage_caption(metadata: dict[str, Any], frequency: str) -> str | None:
    coverage = (metadata.get("coverage") or {}).get(frequency) or {}
    first = _human_date(coverage.get("first_trade_date"))
    last = _human_date(coverage.get("last_trade_date"))
    if not first or not last:
        return None
    return f"{frequency.title()} coverage: {first} – {last}"


def _window_caption(start: date | None, end: date | None) -> str:
    if start and end:
        if start == end:
            return f"Review window: {_human_date(start)}"
        return f"Review window: {_human_date(start)} – {_human_date(end)}"
    if start:
        return f"Review window: from {_human_date(start)}"
    if end:
        return f"Review window: through {_human_date(end)}"
    return ""
