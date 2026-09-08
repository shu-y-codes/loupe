"""Overview — corpus family-tile table (`specs/loupe-ui-design.md`).

HTTP only. One `GET /v1/dq/checks` per loaded contract × held grain. This module does not
group `findings[]` and does not import `quality`. Selecting a row queues Review with that
contract and Quality grain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from . import help as helptext
from .client import ApiProblem, ApiUnavailable, LoupeClient

FAMILY_ORDER = ("gaps", "duplicates", "invalid", "patterns")
FAMILY_LABEL = {
    "gaps": "Gaps",
    "duplicates": "Duplicates",
    "invalid": "Invalid values",
    "patterns": "Recurring patterns",
}


@dataclass(frozen=True)
class OverviewRow:
    contract_id: str
    root: str
    frequency: str
    checked: bool | None
    families: dict[str, dict[str, Any]]
    error: str | None = None


def scopes(contracts: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """One (contract, frequency) per held grain. Minute before daily when both exist."""
    out: list[tuple[dict[str, Any], str]] = []
    for row in contracts:
        held = row.get("frequencies_available") or []
        for frequency in ("minute", "daily"):
            if frequency in held:
                out.append((row, frequency))
    return out


def fingerprint(health: dict[str, Any], contracts: list[dict[str, Any]]) -> str:
    """Bust the table cache when the store's contents change, not on every rerun."""
    ids = ",".join(sorted(str(row.get("contract_id") or "") for row in contracts))
    return "|".join(
        [
            str(health.get("records") or 0),
            str(health.get("batches") or 0),
            str(health.get("synthetic_batches") or 0),
            ids,
        ]
    )


def collect_rows(client: LoupeClient, contracts: list[dict[str, Any]]) -> list[OverviewRow]:
    """Full held window — no start/end. Family cards come from the checks envelope."""
    rows: list[OverviewRow] = []
    for contract, frequency in scopes(contracts):
        contract_id = str(contract.get("contract_id") or "")
        try:
            body = client.checks(contract=contract_id, family="gaps", frequency=frequency)
        except (ApiProblem, ApiUnavailable) as exc:
            rows.append(
                OverviewRow(
                    contract_id=contract_id,
                    root=str(contract.get("root") or ""),
                    frequency=frequency,
                    checked=None,
                    families={},
                    error=str(exc),
                )
            )
            continue
        families = {
            item["family"]: item for item in (body.get("families") or []) if item.get("family")
        }
        rows.append(
            OverviewRow(
                contract_id=contract_id,
                root=str(contract.get("root") or ""),
                frequency=frequency,
                checked=body.get("checked"),
                families=families,
            )
        )
    return rows


def cached_rows(
    client: LoupeClient,
    health: dict[str, Any],
    contracts: list[dict[str, Any]],
) -> list[OverviewRow]:
    key = fingerprint(health, contracts)
    cache = st.session_state.get("overview_cache")
    if isinstance(cache, dict) and cache.get("fp") == key:
        return list(cache["rows"])
    rows = collect_rows(client, contracts)
    st.session_state["overview_cache"] = {"fp": key, "rows": rows}
    return rows


def family_cell(row: OverviewRow, family: str) -> str:
    if row.error:
        return row.error
    if row.checked is False:
        return "Check has not run"
    card = row.families.get(family) or {}
    count = card.get("count", 0)
    unit = card.get("unit") or ""
    return f"{count:,} {unit}".strip()


def style_overview(frame: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Contract is the scan headline; family cells contain compact headlines only."""
    return frame.style.set_properties(subset=["Contract"], **{"font-weight": "bold"})


def _column_config() -> dict[str, Any]:
    families = {
        label: st.column_config.TextColumn(label, width="medium", help=helptext.CARDS[family])
        for family, label in FAMILY_LABEL.items()
    }
    return {
        "Contract": st.column_config.TextColumn("Contract", width=96),
        "Grain": st.column_config.TextColumn("Grain", width=80),
        **families,
    }


def queue_open(contract_id: str, frequency: str) -> None:
    """Next run opens Review on this contract × grain. Family is left as Review last had it."""
    st.session_state["overview_open"] = (contract_id, frequency)


def render_overview_header() -> None:
    """Main-column title, before the synthetic notice — same slot as Review's header."""
    st.title("Loupe")
    st.caption("Overview · loaded contracts by grain · full held window")
    st.caption("Select a row to open it in Review")


def render_overview(rows: list[OverviewRow]) -> None:
    if not rows:
        st.info("No contracts loaded yet. Load demo data from the sidebar to see quality for it.")
        return

    grain = (
        st.segmented_control(
            "Grain",
            ["All", "Daily", "Minute"],
            key="overview_grain",
            default="All",
        )
        or "All"
    )
    visible = _filter_grain(rows, grain)
    if not visible:
        st.info(f"No {grain.lower()} rows in the loaded set.")
        return

    frame = pd.DataFrame(
        [
            {
                "Contract": row.contract_id,
                "Grain": row.frequency.title(),
                **{FAMILY_LABEL[family]: family_cell(row, family) for family in FAMILY_ORDER},
            }
            for row in visible
        ]
    )
    event = st.dataframe(
        style_overview(frame),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="overview_table",
        column_config=_column_config(),
    )
    selected = getattr(getattr(event, "selection", None), "rows", None) or []
    if selected:
        pick = visible[int(selected[0])]
        last = st.session_state.get("overview_opened_from")
        key = (pick.contract_id, pick.frequency)
        if last != key:
            st.session_state["overview_opened_from"] = key
            queue_open(pick.contract_id, pick.frequency)
            st.rerun()


def _filter_grain(rows: list[OverviewRow], grain: str) -> list[OverviewRow]:
    if grain == "Daily":
        return [row for row in rows if row.frequency == "daily"]
    if grain == "Minute":
        return [row for row in rows if row.frequency == "minute"]
    return list(rows)
