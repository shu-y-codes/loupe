"""The upload flow (`plans/05-ui.md` done-when 7).

File → preview and capability disclosure → confirm → progress → dashboard updates. The
preview is the part that matters: it is where the user learns what a file *cannot* do before
committing it, which is what `specs/api-contract.md` §4.2 makes the endpoint for.
"""

from __future__ import annotations

import pandas as pd
import pytest
import streamlit as st
from ui_helpers import FakeClient

from loupe.ui.chrome import render_preview

DAILY_ONLY_PREVIEW = {
    "filename": "zc_daily.csv",
    "file_format": "csv",
    "rows_total": 1145,
    "capabilities": [
        {"capability": "Daily OHLCV bars", "available": True},
        {
            "capability": "Rolling 15-minute VWAP",
            "available": False,
            "reason": "needs minute bars; this file holds daily records only",
        },
    ],
}


@pytest.fixture
def rendered(monkeypatch):
    """Capture what the preview writes, without a running Streamlit script."""
    written: list[str] = []
    for name in ("write", "markdown", "caption", "warning"):
        monkeypatch.setattr(
            st.sidebar, name, lambda value, *a, **k: written.append(str(value))
        )
    return written


def test_the_preview_discloses_an_unavailable_capability_with_its_reason(rendered):
    """A disabled VWAP is explained in place, not silently missing from the dashboard later."""
    render_preview(DAILY_ONLY_PREVIEW)
    text = " ".join(rendered)

    assert "Rolling 15-minute VWAP" in text
    assert "needs minute bars" in text
    assert "Daily OHLCV bars" in text


def test_the_preview_states_what_would_be_rejected(rendered):
    render_preview({**DAILY_ONLY_PREVIEW, "rejects_estimated": 7})
    assert any("7 row(s) would be rejected" in line for line in rendered)


def test_the_preview_reports_size_before_anything_is_committed(rendered):
    render_preview(DAILY_ONLY_PREVIEW)
    assert any("1,145 rows" in line for line in rendered)


def test_nothing_is_ingested_by_previewing(app):
    """The dry run is a dry run: no batch is created until the user confirms."""
    client = FakeClient(preview=DAILY_ONLY_PREVIEW)
    _ = app("Risk", client=client)
    assert not [name for name, _ in client.calls if name == "create_batch"]


def test_the_inventory_reflects_what_the_api_returned_after_a_load(app):
    """The dashboard is a view of the store, never of local state the page kept."""
    client = FakeClient()
    test = app("Risk", client=client)
    frame = test.dataframe[0].value

    assert isinstance(frame, pd.DataFrame)
    assert list(frame["Contract"]) == ["ZCZ25", "ESZ25"]
    assert [name for name, _ in client.calls if name == "summary"]
