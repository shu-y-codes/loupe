"""OHLCV legend and shared-x zoom (`plans/10-reviewer-chrome.md` done-when 5).

Pan/zoom is a Vega interaction AppTest cannot fire. The chart helper is the cheap
proof that the spec is in the spec: interval selection on x, both panes, a legend.
"""

from __future__ import annotations

import json

from ui_helpers import BARS, OHLCV_MARKS

from loupe.ui.charts import OHLCV_ZOOM_CAPTION, ohlcv_chart, overlay_legend_entries


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
