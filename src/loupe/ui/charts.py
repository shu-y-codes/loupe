"""Charts, drawn from envelopes the API already decided.

Altair ships inside Streamlit, so a candle costs no new dependency. Every mark here reads a
field that arrived on a response — `max_severity` colours a candle, it is not recomputed from
findings — because deciding what counts as a bad bar is `quality`'s job and this module's job
is to draw the answer.
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

#: Quality on the candle. Ordered worst-first so the legend reads as an escalation.
_SEVERITY_COLOUR = {
    "critical": "#7f1d1d",
    "error": "#b91c1c",
    "warning": "#b45309",
    "info": "#0369a1",
    None: "#334155",
}


def bars_frame(bars: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(bars)
    if frame.empty:
        return frame
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if "max_severity" not in frame:
        frame["max_severity"] = None
    frame["quality"] = frame["max_severity"].fillna("clean")
    return frame


def candles(bars: list[dict[str, Any]], *, height: int = 260) -> None:
    """Daily OHLCV with quality on the candle.

    The colour is `max_severity` as the API reported it per bar. A bar with no finding is
    drawn in the neutral colour rather than left out, because absence of a finding is a
    statement too.
    """
    frame = bars_frame(bars)
    if frame.empty:
        st.caption("No bars in this window.")
        return

    colour = alt.Color(
        "quality:N",
        scale=alt.Scale(
            domain=["clean", "info", "warning", "error", "critical"],
            range=[
                _SEVERITY_COLOUR[None],
                _SEVERITY_COLOUR["info"],
                _SEVERITY_COLOUR["warning"],
                _SEVERITY_COLOUR["error"],
                _SEVERITY_COLOUR["critical"],
            ],
        ),
        legend=alt.Legend(title="Worst finding on the bar"),
    )
    base = alt.Chart(frame).encode(x=alt.X("trade_date:T", title=None))
    wick = base.mark_rule().encode(
        y=alt.Y("low:Q", title="Price", scale=alt.Scale(zero=False)),
        y2="high:Q",
        color=colour,
    )
    body = base.mark_bar(size=6).encode(y="open:Q", y2="close:Q", color=colour)
    st.altair_chart(wick + body, width="stretch")


def raw_vs_clean(rows: list[dict[str, Any]], *, value: str = "close") -> None:
    """Raw against clean, on one axis — the cleaning impact, shown rather than asserted."""
    if not rows:
        st.caption("Nothing to compare in this window.")
        return
    frame = pd.DataFrame(rows)
    if frame.empty or "trade_date" not in frame:
        st.caption("Nothing to compare in this window.")
        return
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    plot_columns: list[str] = []
    for side in ("raw", "clean"):
        flat = f"{side}_{value}"
        if flat not in frame.columns and side in frame.columns:
            frame[flat] = frame[side].map(
                lambda cell, key=value: cell.get(key) if isinstance(cell, dict) else cell
            )
        if flat in frame.columns and not any(
            isinstance(v, dict) for v in frame[flat].tolist()
        ):
            plot_columns.append(flat)
    if not plot_columns:
        st.caption("Nothing to compare in this window.")
        return
    st.line_chart(
        frame.set_index("trade_date")[plot_columns].rename(
            columns={f"raw_{value}": "raw", f"clean_{value}": "clean"}
        ),
        height=200,
    )


def volume(bars: list[dict[str, Any]]) -> None:
    frame = bars_frame(bars)
    if frame.empty or "volume" not in frame:
        return
    st.bar_chart(frame.set_index("trade_date")[["volume"]], height=120)


def vwap_line(points: list[dict[str, Any]]) -> None:
    """The rolling line. Breaks where cleaning removed the window's volume stay breaks.

    A null is plotted as a gap rather than joined across, because a connected line there would
    claim a price the data does not have (`specs/analytics-semantics.md` §4.6).
    """
    if not points:
        st.caption("No VWAP points in this window.")
        return
    frame = pd.DataFrame(points)
    if frame.empty:
        st.caption("No VWAP points in this window.")
        return
    stamp = "ts_utc" if "ts_utc" in frame else frame.columns[0]
    frame[stamp] = pd.to_datetime(frame[stamp])
    value = "vwap" if "vwap" in frame else frame.columns[-1]
    st.line_chart(frame.set_index(stamp)[[value]], height=200)
