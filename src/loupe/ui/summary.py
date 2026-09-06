"""The Summary module: what is available, what is ok, what needs your attention.

Same two modules for every persona (`specs/loupe-ui-design.md`). What changes with the persona
is the headline tiles, the inventory's columns and its sort — not the page.

Every number here arrives decided. The rollup, the two callouts, the status and the worst
field are all composed in `quality` and carried on the `/v1/dq/summary` envelope; this module
picks which of them a persona sees and hands the rest to `st.dataframe`. Nothing is computed
across rows, because that is aggregation and aggregation is outside `ui`
(`specs/loupe-solution-design.md` §6).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from . import help as helptext
from .runtime import EM_DASH, issue_text, percentage, score_text

#: Sort per persona (`specs/loupe-ui-design.md`, Summary module).
#: Risk reads worst-first because the question is "what needs me now"; Trader and Analyst read
#: by name because they arrive already knowing which contract they came for.
_SORTS = {
    "Risk": lambda row: (row["score"] if row["score"] is not None else 101, row["contract_id"]),
    "Trader": lambda row: (row["contract_id"],),
    "Analyst": lambda row: (
        row["score"] if row["score"] is not None else 101,
        row["contract_id"],
    ),
}


def _root(contract_id: str, roots: dict[str, str]) -> str:
    return roots.get(contract_id) or EM_DASH


def inventory_frame(
    persona: str, contracts: list[dict[str, Any]], roots: dict[str, str]
) -> pd.DataFrame:
    """The inventory table for one persona.

    Columns differ by persona and that is the whole point of the selector: Risk needs the
    settlement callout and a go/needs-attention flag, Trader needs a one-line warning and no
    status column at all (the score carries go/no-go), Analyst needs finding counts because
    the deep view is where they are going next.
    """
    rows = sorted(contracts, key=_SORTS.get(persona, _SORTS["Trader"]))
    if persona == "Risk":
        return pd.DataFrame(
            [
                {
                    "Status": row["status"],
                    "Root": _root(row["contract_id"], roots),
                    "Contract": row["contract_id"],
                    "Score": score_text(row["score"]),
                    "Closing-day": issue_text(row.get("settlement_issue")),
                }
                for row in rows
            ]
        )
    if persona == "Analyst":
        return pd.DataFrame(
            [
                {
                    "Root": _root(row["contract_id"], roots),
                    "Contract": row["contract_id"],
                    "Score": score_text(row["score"]),
                    "Findings": row["finding_count"],
                    "Top issue": issue_text(row.get("top_issue")),
                }
                for row in rows
            ]
        )
    return pd.DataFrame(
        [
            {
                "Root": _root(row["contract_id"], roots),
                "Contract": row["contract_id"],
                "Score": score_text(row["score"]),
                "Warning": issue_text(row.get("top_issue")),
            }
            for row in rows
        ]
    )


def _column_help(frame: pd.DataFrame) -> dict[str, Any]:
    """Attach help to the named headers only — never to a cell that is its own explanation."""
    return {
        name: st.column_config.Column(name, help=helptext.COLUMNS[name])
        for name in frame.columns
        if name in helptext.COLUMNS
    }


def _tile(label: str, value: Any, *, help_key: str | None = None) -> None:
    st.metric(label, value, help=helptext.TILES.get(help_key or label))


def render_headline(
    persona: str, summary: dict[str, Any], trend: list[dict[str, Any]]
) -> None:
    """The tiles that answer the persona's primary question at book grain."""
    contracts = summary.get("contracts", [])
    if persona == "Risk":
        attention = [row for row in contracts if row["status"] == "ATTN"]
        completeness = _completeness(summary)
        columns = st.columns(4)
        with columns[0]:
            _tile("DQ score", score_text(summary.get("overall_score")))
        with columns[1]:
            _tile("Book hit", f"{len(attention)} of {len(contracts)}")
        with columns[2]:
            _tile("Completeness", percentage(completeness))
        with columns[3]:
            st.caption(f"Settlement trend — {helptext.TILES['Settlement trend']}")
            _render_trend(trend)
        return

    if persona == "Trader":
        warned = [row for row in contracts if row.get("top_issue")]
        columns = st.columns(2)
        with columns[0]:
            _tile("Contracts", len(contracts))
        with columns[1]:
            _tile("With warnings", len(warned))
        return

    findings = sum(row["finding_count"] for row in contracts)
    both = [row for row in contracts if len(row.get("frequencies", [])) > 1]
    worst = summary.get("worst_field")
    columns = st.columns(4)
    with columns[0]:
        _tile("DQ score", score_text(summary.get("overall_score")))
    with columns[1]:
        _tile("Open findings", findings)
    with columns[2]:
        _tile("Both frequencies", f"{len(both)} contracts", help_key="Both frequencies")
    with columns[3]:
        # §11.7: absent is a real answer, not a rendering failure. `OUT.*` and missing-slot
        # runs are unmapped by design, so a corpus can honestly have no worst field.
        _tile("Worst field", worst["field"] if worst else "not applicable")


def _completeness(summary: dict[str, Any]) -> float | None:
    from .runtime import dimension_score

    return dimension_score(summary, "completeness")


def _render_trend(trend: list[dict[str, Any]]) -> None:
    """Daily completeness over trade dates — the settlement-reliability sparkline."""
    if not trend:
        st.caption("No trend yet — run validation over a window with daily records.")
        return
    frame = pd.DataFrame(
        [
            {"trade_date": row.get("day"), "completeness": row.get("dimension_score")}
            for row in trend
            if row.get("dimension_score") is not None
        ]
    )
    if frame.empty:
        st.caption("No daily completeness recorded in this window.")
        return
    st.line_chart(frame.set_index("trade_date"), height=120)


def render_summary(
    persona: str,
    summary: dict[str, Any],
    trend: list[dict[str, Any]],
    roots: dict[str, str],
) -> str | None:
    """Draw the module and return the contract the user selected, if any.

    Selection is what binds the two modules: `specs/loupe-ui-design.md` has Specifics driven by
    the Summary row, so this returns the choice rather than rendering Specifics itself.
    """
    st.subheader("Summary")
    st.caption("what is available · what is ok · what needs attention")

    contracts = summary.get("contracts", [])
    if not contracts:
        st.info(
            "No contracts loaded yet. Upload a CSV or Parquet file from the sidebar to see "
            "quality for it."
        )
        return None

    render_headline(persona, summary, trend)

    frame = inventory_frame(persona, contracts, roots)
    caption = {
        "Risk": "Loaded contracts · worst first · select a row to open Specifics",
        "Trader": "Loaded contracts · by name · score carries go/no-go",
        "Analyst": "Loaded contracts · score then name",
    }[persona]
    st.caption(caption)

    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config=_column_help(frame),
        on_select="rerun",
        selection_mode="single-row",
        key=f"inventory-{persona}",
    )
    selected = getattr(event, "selection", None)
    rows = (selected or {}).get("rows") or []
    if rows:
        return str(frame.iloc[rows[0]]["Contract"])
    return None
