"""The reviewer main column: cards, charts, picture, aggregated issues.

HTTP only. Family membership, overlay marks and What-we-did come from `GET /v1/dq/checks`.
This module does not group `findings[]` and does not import `quality`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from . import charts
from . import help as helptext
from .client import ApiProblem
from .runtime import checks_score_caption

_FAMILY_ORDER = ("gaps", "duplicates", "invalid", "patterns")
_FAMILY_LABEL = {
    "gaps": "Gaps",
    "duplicates": "Duplicates",
    "invalid": "Invalid values",
    "patterns": "Recurring patterns",
}


def render_review(
    checks: dict[str, Any],
    bars: list[dict[str, Any]],
    vwap: dict[str, Any] | ApiProblem | None,
) -> None:
    """Cards, score caption, Daily OHLCV, VWAP, picture, issues — that order is load-bearing."""
    family = _family_control(checks)
    _family_cards(checks, family)
    st.caption(checks_score_caption(checks), help=helptext.JARGON["scope_signature"])

    if not checks.get("checked"):
        st.info("Validation has not finished for this contract yet.")
        return

    overlay = checks.get("overlay") or {}
    st.subheader("Daily OHLCV")
    st.caption("Clean series · selected family. Rule IDs are a caption, not the candle.")
    charts.candles(bars, overlay, family=family)

    st.subheader("Rolling 15-minute VWAP")
    _vwap_panel(vwap, overlay, family)

    _picture(overlay.get("picture") or {}, family)
    _issues(checks.get("issues") or [])


def _family_control(checks: dict[str, Any]) -> str:
    families = checks.get("families") or []
    options = [row["family"] for row in families if row.get("family") in _FAMILY_ORDER]
    if not options:
        options = list(_FAMILY_ORDER)
    labels = {
        row["family"]: row.get("label") or _FAMILY_LABEL[row["family"]]
        for row in families
        if row.get("family") in _FAMILY_ORDER
    }
    for name in options:
        labels.setdefault(name, _FAMILY_LABEL.get(name, name))
    selected = st.segmented_control(
        "Check",
        options,
        format_func=lambda name: labels.get(name, name),
        key="family",
        default="gaps" if "gaps" in options else options[0],
        required=True,
        width="stretch",
        help=helptext.JARGON["marked sessions"],
    )
    return selected or "gaps"


def _family_cards(checks: dict[str, Any], selected: str) -> None:
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
            unit = card.get("unit") or ""
            value = f"{card.get('count', 0)} {unit}".strip()
            st.metric(
                card.get("label") or _FAMILY_LABEL[name],
                value,
                help=helptext.CARDS.get(name),
            )
            detail = card.get("detail") or ""
            if detail:
                st.caption(detail)


def _vwap_panel(
    vwap: dict[str, Any] | ApiProblem | None,
    overlay: dict[str, Any],
    family: str,
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
    charts.vwap_line(vwap.get("data") or [], overlay, family=family)


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
        bar = picture.get("bar")
        if bar:
            st.dataframe(pd.DataFrame([bar]), hide_index=True, width="stretch")
    elif kind == "pattern_histogram":
        charts.pattern_histogram(picture.get("buckets") or [])


def _issues(issues: list[dict[str, Any]]) -> None:
    st.subheader("Issues in this window")
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
