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

from loupe.ui.chrome import companion_grain, render_preview

#: Copied from a real `POST /v1/ingest/preview` response, not written from memory. The keys
#: are asserted against `PreviewResponse` below, because a stub shaped like the page expects
#: rather than like the API answers lets a broken page pass.
DAILY_ONLY_PREVIEW = {
    "filename": "zc_daily.csv",
    "file_format": "csv",
    "rows_total": 1145,
    "inferred_frequency": {"value": "daily", "method": "modal delta 1d", "confidence": 1.0},
    "contracts_detected": ["ZCZ25"],
    "verdict": "accept",
    "enables": {
        "daily_bars": {"available": True, "reason": "supplied", "substitute_offered": None},
        "vwap_15m": {
            "available": False,
            "reason": "needs minute bars; this file holds daily records only",
            "substitute_offered": False,
        },
        "reconciliation": {
            "available": False,
            "reason": "not possible: only one granularity is present for this contract",
            "substitute_offered": False,
        },
    },
    "warnings": [],
}

MINUTE_ONLY_PREVIEW = {
    **DAILY_ONLY_PREVIEW,
    "inferred_frequency": {"value": "minute", "method": "modal delta 60s", "confidence": 1.0},
    "enables": {
        "daily_bars": {
            "available": True,
            "reason": "derived from the minute tape",
            "substitute_offered": None,
        },
        "vwap_15m": {"available": True, "reason": "available", "substitute_offered": None},
        "reconciliation": DAILY_ONLY_PREVIEW["enables"]["reconciliation"],
    },
}


def test_the_preview_fixture_uses_only_fields_the_api_returns():
    """The guard that would have caught this file being written from imagination.

    `render_preview` originally read `capabilities` and `rejects_estimated`, neither of which
    exists on the envelope — so the capability disclosure never fired in production while
    every test here passed against a fixture invented to match the code.
    """
    from loupe.api.models import PreviewResponse

    real = set(PreviewResponse.model_fields)
    assert set(DAILY_ONLY_PREVIEW) <= real, set(DAILY_ONLY_PREVIEW) - real
    assert set(MINUTE_ONLY_PREVIEW) <= real, set(MINUTE_ONLY_PREVIEW) - real


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


def test_the_preview_surfaces_loader_warnings(rendered):
    render_preview({**DAILY_ONLY_PREVIEW, "warnings": ["No vendor profile matched"]})
    assert any("No vendor profile matched" in line for line in rendered)


def test_the_preview_reports_size_grain_and_contracts_before_anything_is_committed(rendered):
    render_preview(DAILY_ONLY_PREVIEW)
    text = " ".join(rendered)
    assert "1,145 rows" in text
    assert "daily" in text
    assert "ZCZ25" in text


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


# ---------------------------------------------------------------- both grains


def test_a_daily_file_is_told_what_the_minute_tape_would_add():
    """The case the advice targets: a daily file can only be checked against itself."""
    message = companion_grain(DAILY_ONLY_PREVIEW)
    assert message and "minute tape" in message
    assert "checked against itself" in message


def test_a_minute_file_is_told_what_it_gains_rather_than_what_it_lacks():
    """§2: every persona can use Loupe on the grain they arrive with.

    A Trader uploading the tape has a complete answer to their own question, so the message
    names what the daily file adds and does not imply this upload is deficient.
    """
    message = companion_grain(MINUTE_ONLY_PREVIEW)
    assert message and "daily file" in message
    assert "already gives" in message, "the tape's own usefulness is acknowledged first"
    assert "cannot" not in message


def test_no_recommendation_when_reconciliation_is_already_possible():
    """The notice must be absent when it would be false, or it becomes furniture.

    Keyed off `enables.reconciliation`, which the API already computes — the UI does not ask
    a second question or keep its own idea of what the store holds.
    """
    both = {
        **DAILY_ONLY_PREVIEW,
        "enables": {
            **DAILY_ONLY_PREVIEW["enables"],
            "reconciliation": {"available": True, "reason": "both granularities present"},
        },
    }
    assert companion_grain(both) is None


def test_the_recommendation_is_not_a_refusal(rendered):
    """A single-grain upload stays valid and scoreable; this is advice, not a gate."""
    render_preview(DAILY_ONLY_PREVIEW)
    text = " ".join(rendered)
    assert "1,145 rows" in text, "the file is still previewed and loadable"
    assert DAILY_ONLY_PREVIEW["verdict"] == "accept"
