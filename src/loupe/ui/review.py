"""The reviewer main column: cards, charts, picture, aggregated issues.

HTTP only. Family membership, overlay marks and What-we-did come from `GET /v1/dq/checks`.
This module does not group `findings[]` and does not import `quality`. The four cards *are*
the family control; there is no Check row and no score caption.
"""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from . import charts
from . import help as helptext
from .client import ApiProblem

_FAMILY_ORDER = ("gaps", "duplicates", "invalid", "patterns")
_FAMILY_LABEL = {
    "gaps": "Gaps",
    "duplicates": "Duplicates",
    "invalid": "Invalid values",
    "patterns": "Recurring patterns",
}


def render_review(
    checks: dict[str, Any],
    bars: dict[str, Any] | list[dict[str, Any]],
    vwap: dict[str, Any] | ApiProblem | None,
    *,
    scope_identity: dict[str, Any] | None = None,
) -> None:
    """Cards, Daily OHLCV, VWAP, picture, issues — that order is load-bearing."""
    family = _selected_family()
    _family_cards(checks, family)

    if not checks.get("checked"):
        st.info("Validation has not finished for this contract yet.")
        return

    overlay = checks.get("overlay") or {}
    frequency = (checks.get("scope") or {}).get("frequency") or (
        scope_identity or {}
    ).get("frequency")
    bar_rows = bars.get("data", []) if isinstance(bars, dict) else bars
    bar_meta = bars.get("meta", {}) if isinstance(bars, dict) else {}
    source = bar_meta.get("bar_source") or (
        "derived_from_minute" if frequency == "minute" else "supplied_daily"
    )
    st.subheader("Daily OHLCV")
    source_label = (
        "Derived from minute" if source == "derived_from_minute" else "Supplied daily"
    )
    st.caption(
        f"{source_label} · {str(frequency or '').title()} quality grain · selected family. "
        "Rule IDs stay off the candle."
    )
    charts.candles(
        bar_rows,
        overlay,
        family=family,
        scope_key=charts.chart_scope_key(scope_identity, bar_rows, "trade_date"),
    )

    st.subheader("Rolling 15-minute VWAP")
    _vwap_panel(vwap, overlay, family, frequency, scope_identity)

    _picture(overlay.get("picture") or {}, family)
    _issues(checks.get("issues") or [], family)


def _selected_family() -> str:
    family = st.session_state.get("family") or "gaps"
    if family not in _FAMILY_ORDER:
        family = "gaps"
        st.session_state["family"] = family
    return family


def _select_family(name: str) -> None:
    st.session_state["family"] = name


def _family_cards(checks: dict[str, Any], selected: str) -> None:
    """The four cells are the family control. Count leads; detail is body size."""
    families = checks.get("families") or []
    by_id = {row["family"]: row for row in families}
    columns = st.columns(4)
    for column, name in zip(columns, _FAMILY_ORDER, strict=True):
        card = by_id.get(name) or {
            "family": name,
            "label": _FAMILY_LABEL[name],
            "count": 0,
            "unit": "",
            "detail": "",
        }
        with column, st.container(border=True):
            if name == selected:
                st.badge("Selected")
            st.button(
                card.get("label") or _FAMILY_LABEL[name],
                key=f"family_card_{name}",
                type="primary" if name == selected else "secondary",
                width="stretch",
                on_click=_select_family,
                args=(name,),
            )
            unit = card.get("unit") or ""
            count_label = f"{card.get('count', 0)} {unit}".strip()
            # Count slightly larger than body; detail is regular — not st.metric's inverted
            # hierarchy (label small / value huge).
            st.markdown(
                f'<p style="font-size:1.125rem;font-weight:600;margin:0.25rem 0 0 0">'
                f"{html.escape(count_label)}</p>",
                unsafe_allow_html=True,
                help=helptext.CARDS.get(name),
            )
            detail = (card.get("detail") or "").strip()
            if detail:
                st.markdown(detail)


def _vwap_panel(
    vwap: dict[str, Any] | ApiProblem | None,
    overlay: dict[str, Any],
    family: str,
    quality_frequency: str | None,
    scope_identity: dict[str, Any] | None,
) -> None:
    """The panel stays and explains itself; it never silently renders empty."""
    if isinstance(vwap, ApiProblem):
        if vwap.code == "CAP.FREQUENCY_UNAVAILABLE":
            st.info(f"**Needs minute bars.** {vwap}")
        else:
            st.warning(str(vwap))
        return
    if vwap is None:
        st.caption("No VWAP points in this window.")
        return
    points = vwap.get("data") or []
    context_only = quality_frequency == "daily"
    if context_only:
        st.caption("Minute tape · context only for Daily quality grain")
    charts.vwap_line(
        points,
        overlay,
        family=family,
        show_family_marks=not context_only,
        scope_key=charts.chart_scope_key(scope_identity, points, "ts_utc"),
    )


def _picture(picture: dict[str, Any], family: str) -> None:
    label = _FAMILY_LABEL.get(family, family)
    st.subheader(f"Picture of {label.lower()}")
    kind = picture.get("kind") or "empty"
    caption = picture.get("caption") or ""
    rule_ids = picture.get("rule_ids") or []

    if kind == "empty":
        st.caption(caption or "This check ran. Nothing in this window.")
        return

    if caption and kind not in {"absent_session", "empty"}:
        st.markdown(caption)
    if rule_ids:
        st.caption(" · ".join(str(rule) for rule in rule_ids))

    if kind == "gaps_ribbon":
        charts.gaps_ribbon(picture.get("slots") or [])
    elif kind == "absent_session":
        st.info(caption or "Settlement never arrived. Loupe does not invent a zero-filled bar.")
    elif kind == "duplicate_rows":
        rows = picture.get("rows") or []
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    elif kind == "invalid_cell":
        field = picture.get("field")
        if field:
            st.markdown(f"Broken cell: **{field}**")
        evidence_frequency = picture.get("evidence_frequency")
        evidence_source = picture.get("evidence_source")
        if evidence_frequency or evidence_source:
            st.caption(
                "Evidence · "
                + " · ".join(
                    str(value)
                    for value in (evidence_frequency, evidence_source)
                    if value
                )
            )
        bar = picture.get("bar")
        if bar:
            st.dataframe(pd.DataFrame([bar]), hide_index=True, width="stretch")
    elif kind == "pattern_histogram":
        shown = picture.get("buckets_shown") or len(picture.get("buckets") or [])
        total = picture.get("patterns_total") or shown
        st.caption(f"Showing {shown} of {total} standing patterns")
        charts.pattern_histogram(
            picture.get("buckets") or [],
            axis_label=picture.get("axis_label") or picture.get("dimension") or "Bucket",
        )
        st.caption(
            "A findings share much larger than record exposure is over-representation. "
            "The configured standing threshold, not raw count alone, determines inclusion."
        )


def _issues(issues: list[dict[str, Any]], family: str) -> None:
    st.subheader(f"Issues in selected family · {_FAMILY_LABEL.get(family, family)}")
    if not issues:
        st.success("This check ran. Nothing in this window.")
        return
    frame = pd.DataFrame(
        [
            {
                "What": row.get("what") or "",
                "Days": row.get("days") or 0,
                "Records": row.get("records") or 0,
                "What we did": row.get("what_we_did") or "",
            }
            for row in issues
        ]
    )
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            name: st.column_config.Column(name, help=helptext.COLUMNS[name])
            for name in frame.columns
            if name in helptext.COLUMNS
        },
    )
