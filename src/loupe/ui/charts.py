"""Charts, drawn from envelopes the API already decided.

Altair ships inside Streamlit, so a candle costs no new dependency. Overlay marks come from
`GET /v1/dq/checks` and are keyed on the **selected family**, never `max_severity`. That
field may still arrive on the bar envelope for the publish gate; this module ignores it.
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from . import help as helptext

_NEUTRAL = "#334155"
_INVALID = "#b91c1c"
_GAP = "#d97706"
_ABSENT = "#64748b"
_DUP = "#2563eb"
_PATTERN = "#7c3aed"
_VOLUME_BAD = "#c2410c"
_VOLUME = "#94a3b8"

#: How to reset the shared-x zoom on Daily OHLCV + volume (`specs/loupe-ui-design.md`).
OHLCV_ZOOM_CAPTION = "Drag the dates to pan or zoom. Double-click to reset."


def _date_str(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return str(value)[:10]
    text = str(value)
    return text[:10] if text else text


def overlay_frame(bars: list[dict[str, Any]], marks: list[dict[str, Any]]) -> pd.DataFrame:
    """Join bars to overlay marks by `trade_date`. Absent settlements have no OHLC."""
    by_mark = {_date_str(row["trade_date"]): row for row in marks}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bar in bars:
        day = _date_str(bar.get("trade_date"))
        seen.add(day)
        mark = by_mark.get(day, {})
        rows.append(
            {
                "trade_date": day,
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "volume": bar.get("volume"),
                "session": mark.get("session") or "present",
                "partial_gap": bool(mark.get("partial_gap")),
                "duplicate": bool(mark.get("duplicate")),
                "invalid": bool(mark.get("invalid")),
                "invalid_volume": bool(mark.get("invalid_volume")),
                "pattern_member": bool(mark.get("pattern_member")),
                "overlay_caption": mark.get("caption") or "",
            }
        )
    for day, mark in by_mark.items():
        if day in seen:
            continue
        rows.append(
            {
                "trade_date": day,
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": None,
                "session": mark.get("session") or "absent",
                "partial_gap": bool(mark.get("partial_gap")),
                "duplicate": bool(mark.get("duplicate")),
                "invalid": bool(mark.get("invalid")),
                "invalid_volume": bool(mark.get("invalid_volume")),
                "pattern_member": bool(mark.get("pattern_member")),
                "overlay_caption": mark.get("caption") or "",
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.sort_values("trade_date").reset_index(drop=True)


def overlay_legend_entries(family: str) -> list[tuple[str, str]]:
    """Named marks for the selected family — a chart legend, not a caption of dates."""
    if family == "gaps":
        return [
            ("Session-open hole", _GAP),
            ("Settlement never arrived", _ABSENT),
        ]
    if family == "duplicates":
        return [("Kept timestamp", _DUP)]
    if family == "invalid":
        return [
            ("Invalid value", _INVALID),
            ("Volume defect", _VOLUME_BAD),
        ]
    if family == "patterns":
        return [("Participating session", _PATTERN)]
    return []


def _legend_layer(entries: list[tuple[str, str]]) -> alt.Chart:
    """Invisible points whose colour encoding is the OHLCV legend."""
    frame = pd.DataFrame(
        {"mark": [name for name, _ in entries], "trade_date": pd.NaT, "y": [None] * len(entries)}
    )
    return (
        alt.Chart(frame)
        .mark_point(opacity=0, filled=True)
        .encode(
            x=alt.X("trade_date:T", title=None),
            y=alt.Y("y:Q", title="Price", scale=alt.Scale(zero=False)),
            color=alt.Color(
                "mark:N",
                scale=alt.Scale(
                    domain=[name for name, _ in entries],
                    range=[colour for _, colour in entries],
                ),
                legend=alt.Legend(title=None, orient="bottom", symbolOpacity=1),
            ),
        )
    )


def _x_zoom() -> alt.Parameter:
    return alt.selection_interval(bind="scales", encodings=["x"], name="ohlcv_x")


def ohlcv_chart(
    bars: list[dict[str, Any]],
    overlay: dict[str, Any] | None,
    *,
    family: str,
    height: int = 260,
) -> alt.Chart | None:
    """Daily OHLCV + volume, shared-x pan/zoom, selected-family legend. Never a zero-filled bar."""
    marks = list((overlay or {}).get("ohlcv") or [])
    frame = overlay_frame(bars, marks)
    if frame.empty:
        return None

    present = frame.dropna(subset=["open", "high", "low", "close"])
    layers: list[alt.Chart] = []
    entries = overlay_legend_entries(family)
    if entries:
        layers.append(_legend_layer(entries))

    if family == "patterns":
        bands = frame[frame["pattern_member"]]
        if not bands.empty:
            band = bands.copy()
            band["x2"] = band["trade_date"] + pd.Timedelta(hours=18)
            layers.append(
                alt.Chart(band).mark_rect(opacity=0.18, color=_PATTERN).encode(
                    x="trade_date:T", x2="x2:T"
                )
            )

    if not present.empty:
        paint = family == "invalid"
        present = present.copy()
        present["fill"] = [
            _INVALID if paint and bool(row.invalid) else _NEUTRAL for row in present.itertuples()
        ]
        base = alt.Chart(present).encode(x=alt.X("trade_date:T", title=None))
        layers.append(
            base.mark_rule().encode(
                y=alt.Y("low:Q", title="Price", scale=alt.Scale(zero=False)),
                y2="high:Q",
                color=alt.Color("fill:N", scale=None, legend=None),
            )
        )
        layers.append(
            base.mark_bar(size=6).encode(
                y="open:Q",
                y2="close:Q",
                color=alt.Color("fill:N", scale=None, legend=None),
            )
        )

    if family == "gaps":
        holes = present[present["partial_gap"]] if not present.empty else present
        if not holes.empty:
            layers.append(
                alt.Chart(holes)
                .mark_point(shape="triangle-up", size=90, color=_GAP, filled=True)
                .encode(x="trade_date:T", y="high:Q")
            )
        absent = frame[frame["session"] == "absent"]
        if not absent.empty:
            y_hi = float(present["high"].max()) if not present.empty else 1.0
            y_lo = float(present["low"].min()) if not present.empty else 0.0
            dashed = absent.copy()
            dashed["y"] = y_lo
            dashed["y2"] = y_hi
            layers.append(
                alt.Chart(dashed)
                .mark_rule(strokeDash=[4, 3], color=_ABSENT, strokeWidth=2)
                .encode(x="trade_date:T", y="y:Q", y2="y2:Q")
            )

    if family == "duplicates" and not present.empty:
        pins = present[present["duplicate"]]
        if not pins.empty:
            layers.append(
                alt.Chart(pins)
                .mark_point(shape="diamond", size=80, color=_DUP, filled=True)
                .encode(x="trade_date:T", y="close:Q")
            )

    if not layers:
        return None

    zoom = _x_zoom()
    price = layers[0]
    for layer in layers[1:]:
        price = price + layer
    price = price.properties(height=height)

    volume = _volume_chart(frame, family)
    if volume is None:
        return price.add_params(zoom)
    return alt.vconcat(price, volume).resolve_scale(x="shared").add_params(zoom)


def candles(
    bars: list[dict[str, Any]],
    overlay: dict[str, Any] | None,
    *,
    family: str,
    height: int = 260,
) -> None:
    """Daily OHLCV with selected-family marks. Never a zero-filled absent bar."""
    chart = ohlcv_chart(bars, overlay, family=family, height=height)
    if chart is None:
        st.caption("No bars in this window.")
        return
    st.altair_chart(chart, width="stretch", theme=None)
    st.caption(OHLCV_ZOOM_CAPTION)


def _volume_chart(frame: pd.DataFrame, family: str) -> alt.Chart | None:
    present = frame.dropna(subset=["volume"])
    if present.empty:
        return None
    present = present.copy()
    present["fill"] = [
        _VOLUME_BAD if family == "invalid" and bool(row.invalid_volume) else _VOLUME
        for row in present.itertuples()
    ]
    return (
        alt.Chart(present)
        .mark_bar()
        .encode(
            x=alt.X("trade_date:T", title=None),
            y=alt.Y("volume:Q", title="Volume"),
            color=alt.Color("fill:N", scale=None, legend=None),
        )
        .properties(height=90)
    )


def vwap_line(
    points: list[dict[str, Any]],
    overlay: dict[str, Any] | None,
    *,
    family: str,
) -> None:
    """The rolling line. Null windows stay breaks. Selected family may name them."""
    if not points:
        st.caption("No VWAP points in this window.")
        return
    frame = pd.DataFrame(points)
    if frame.empty:
        st.caption("No VWAP points in this window.")
        return
    stamp = "ts_utc" if "ts_utc" in frame.columns else frame.columns[0]
    frame[stamp] = pd.to_datetime(frame[stamp], utc=True)
    value = "vwap" if "vwap" in frame.columns else frame.columns[-1]
    vwap_meta = (overlay or {}).get("vwap") or {}
    name_breaks = bool(vwap_meta.get("name_breaks")) and family in {
        "gaps",
        "patterns",
        "invalid",
    }
    pattern_hours = vwap_meta.get("pattern_hours") or []

    layers: list[alt.Chart] = []
    if family == "patterns" and pattern_hours:
        hours = {_hour_from_bucket(bucket) for bucket in pattern_hours}
        hours.discard(None)
        shade = frame.copy()
        shade["hour"] = shade[stamp].dt.hour
        shade = shade[shade["hour"].isin(hours)]
        if not shade.empty:
            shade["x2"] = shade[stamp] + pd.Timedelta(minutes=15)
            layers.append(
                alt.Chart(shade).mark_rect(opacity=0.2, color=_PATTERN).encode(
                    x=alt.X(f"{stamp}:T", title=None), x2="x2:T"
                )
            )

    line = frame.dropna(subset=[value])
    if not line.empty:
        layers.append(
            alt.Chart(line)
            .mark_line(color=_NEUTRAL)
            .encode(
                x=alt.X(f"{stamp}:T", title=None),
                y=alt.Y(f"{value}:Q", title="VWAP", scale=alt.Scale(zero=False)),
            )
        )
    if name_breaks:
        holes = frame[frame[value].isna()]
        if not holes.empty:
            y_mid = float(line[value].median()) if not line.empty else 0.0
            holes = holes.copy()
            holes["y"] = y_mid
            layers.append(
                alt.Chart(holes)
                .mark_point(shape="cross", size=80, color=_GAP)
                .encode(x=f"{stamp}:T", y="y:Q")
            )
    if not layers:
        st.caption("No VWAP points in this window.")
        return
    chart = layers[0]
    for layer in layers[1:]:
        chart = chart + layer
    st.altair_chart(chart.properties(height=200), width="stretch")
    if name_breaks:
        st.caption("Crosses name a break where window volume was dropped.")
    st.caption(helptext.JARGON["vwap"])


def gaps_ribbon(slots: list[dict[str, Any]]) -> None:
    """Expected-vs-present minute slots. Vega, not SVG via `st.html`."""
    if not slots:
        st.caption("No slot ribbon for this gap.")
        return
    frame = pd.DataFrame(slots)
    if "label" not in frame.columns:
        st.caption("No slot ribbon for this gap.")
        return
    frame["state"] = [
        "present" if bool(v) else "missing" for v in frame.get("present", [])
    ]
    frame["height"] = 1
    chart = (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("label:N", sort=None, title=None),
            y=alt.Y("height:Q", axis=None),
            color=alt.Color(
                "state:N",
                scale=alt.Scale(
                    domain=["present", "missing"], range=[_NEUTRAL, _GAP]
                ),
                legend=alt.Legend(title=None),
            ),
        )
        .properties(height=80)
    )
    st.altair_chart(chart, width="stretch")


def pattern_histogram(buckets: list[dict[str, Any]]) -> None:
    if not buckets:
        return
    frame = pd.DataFrame(buckets)
    if frame.empty or "label" not in frame.columns:
        return
    long = frame.melt(
        id_vars=["label"],
        value_vars=[c for c in ("share_of_findings", "share_of_records") if c in frame.columns],
        var_name="share",
        value_name="value",
    )
    long["share"] = long["share"].map(
        {"share_of_findings": "share of findings", "share_of_records": "share of records"}
    )
    chart = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("label:N", title=None),
            y=alt.Y("value:Q", title=None),
            color=alt.Color("share:N", legend=alt.Legend(title=None)),
            xOffset="share:N",
        )
        .properties(height=160)
    )
    st.altair_chart(chart, width="stretch")


def _hour_from_bucket(bucket: str) -> int | None:
    text = str(bucket)
    if ":" not in text:
        return None
    head = text.split(":", 1)[0]
    digits = "".join(ch for ch in head if ch.isdigit())
    if not digits:
        return None
    hour = int(digits)
    return hour if 0 <= hour <= 23 else None
