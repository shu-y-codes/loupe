"""OHLCV legend, zoom, hover, and absent label (`plans/10-reviewer-chrome.md` follow-on).

Pan/zoom is a Vega interaction AppTest cannot fire. The chart helper is the cheap
proof that the spec is in the Vega: interval selection on x, both panes, a legend,
status tooltips, on-chart absent, volume tooltip without `fill`.
"""

from __future__ import annotations

import json

from ui_helpers import BARS, OHLCV_MARKS

from loupe.ui.charts import (
    OHLCV_ZOOM_CAPTION,
    ohlcv_chart,
    overlay_legend_entries,
    overlay_status,
)


def test_overlay_legend_names_marks_not_rule_ids():
    gaps = dict(overlay_legend_entries("gaps"))
    invalid = dict(overlay_legend_entries("invalid"))
    assert "Session-open hole" in gaps
    assert "Settlement never arrived" in gaps
    assert "Invalid value" in invalid
    assert "Volume defect" in invalid
    assert "Session-open hole" not in invalid
    for family in ("gaps", "duplicates", "invalid", "patterns"):
        blob = " ".join(name for name, _ in overlay_legend_entries(family))
        assert "CMP." not in blob
        assert "VAL." not in blob


def test_ohlcv_chart_zooms_price_and_volume_on_shared_x():
    chart = ohlcv_chart(BARS, {"ohlcv": OHLCV_MARKS}, family="gaps")
    assert chart is not None
    spec = json.dumps(chart.to_dict())
    assert "vconcat" in spec
    assert "ohlcv_x" in spec
    assert "scales" in spec
    assert "Session-open hole" in spec
    assert "Settlement never arrived" in spec
    assert "double-click" in OHLCV_ZOOM_CAPTION.lower()


def test_ohlcv_legend_follows_the_selected_family():
    gaps = json.dumps(ohlcv_chart(BARS, {"ohlcv": OHLCV_MARKS}, family="gaps").to_dict())
    invalid = json.dumps(
        ohlcv_chart(BARS, {"ohlcv": OHLCV_MARKS}, family="invalid").to_dict()
    )
    assert "Session-open hole" in gaps
    assert "Invalid value" in invalid
    assert "Session-open hole" not in invalid
    assert "Invalid value" not in gaps


def test_overlay_status_names_selected_family_defects():
    gap_hole = {
        "session": "present",
        "partial_gap": True,
        "duplicate": False,
        "invalid": False,
        "invalid_volume": False,
        "pattern_member": False,
    }
    absent = {
        "session": "absent",
        "partial_gap": False,
        "duplicate": False,
        "invalid": False,
        "invalid_volume": False,
        "pattern_member": False,
    }
    assert overlay_status("gaps", gap_hole) == "gap: session-open hole"
    assert overlay_status("gaps", absent) == "gap: session missing"
    assert overlay_status("invalid", {**gap_hole, "invalid": True}) == "invalid value"
    assert overlay_status("gaps", {**gap_hole, "partial_gap": False}) == "clean"


def test_ohlcv_hover_carries_ohlc_and_status():
    chart = ohlcv_chart(BARS, {"ohlcv": OHLCV_MARKS}, family="gaps")
    assert chart is not None
    spec = json.dumps(chart.to_dict())
    for field in ("Date", "Open", "High", "Low", "Close", "Status"):
        assert field in spec
    assert "gap: session-open hole" in spec or "gap: session missing" in spec


def test_absent_settlement_is_labelled_on_the_chart():
    chart = ohlcv_chart(BARS, {"ohlcv": OHLCV_MARKS}, family="gaps")
    assert chart is not None
    spec = json.dumps(chart.to_dict())
    assert '"text": "absent"' in spec or '"text":"absent"' in spec


def test_volume_tooltip_excludes_fill_field_name():
    chart = ohlcv_chart(BARS, {"ohlcv": OHLCV_MARKS}, family="invalid")
    assert chart is not None
    spec = json.dumps(chart.to_dict())
    assert '"title": "Volume"' in spec or '"title":"Volume"' in spec
    # Colour encoding must not leak the field name `fill` into tooltips.
    assert '"field": "fill"' not in spec and '"field":"fill"' not in spec
