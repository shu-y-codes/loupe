"""Overview page (`plans/13-overview-page.md`).

AppTest over the stubbed client. Review assembly stays in `test_pages.py`; this file
asserts the corpus table, grain filter, click-through, and that Overview does not fetch
bars or VWAP.
"""

from __future__ import annotations

import pandas as pd
from ui_helpers import CHECKS, MIXED_COVERAGE_CONTRACTS, FakeClient

from loupe.ui.overview import OverviewRow, collect_rows, family_cell, scopes, style_overview

FAMILY_COLUMNS = ("Gaps", "Duplicates", "Invalid values", "Recurring patterns")


def _no_exception(test):
    assert not test.exception, [str(e.value) for e in test.exception]
    return test


def _labels(test) -> list[str]:
    return [
        b.label
        for b in test.button
        if b.label
        in {
            "Gaps",
            "Duplicates",
            "Invalid values",
            "Recurring patterns",
        }
    ]


def _overview_table(test):
    tables = []
    for frame in test.dataframe:
        value = frame.value
        if isinstance(value, pd.io.formats.style.Styler):
            value = value.data
        tables.append(value)
    return next(
        frame
        for frame in tables
        if list(frame.columns)[:2] == ["Contract", "Grain"] and "Gaps" in list(frame.columns)
    )


def test_scopes_emit_one_row_per_held_grain():
    dual, daily, minute = MIXED_COVERAGE_CONTRACTS["data"]
    pairs = [(row["contract_id"], freq) for row, freq in scopes(MIXED_COVERAGE_CONTRACTS["data"])]
    assert pairs == [
        ("ESZ25", "minute"),
        ("ESZ25", "daily"),
        ("ZCZ25", "daily"),
        ("SR3G26", "minute"),
    ]
    assert scopes([daily]) == [(daily, "daily")]
    assert scopes([minute]) == [(minute, "minute")]
    assert scopes([dual]) == [(dual, "minute"), (dual, "daily")]


def test_family_cell_does_not_paint_unchecked_as_zero():
    row = OverviewRow(
        contract_id="ESZ25",
        root="ES",
        frequency="daily",
        checked=False,
        families={"gaps": {"count": 0, "unit": "runs", "detail": "Check has not run"}},
    )
    assert family_cell(row, "gaps") == "Check has not run"
    live = OverviewRow(
        contract_id="ESZ25",
        root="ES",
        frequency="minute",
        checked=True,
        families={
            "gaps": {
                "count": 2,
                "unit": "runs",
                "detail": "1 session-open hole · 1 session absent",
            }
        },
    )
    assert family_cell(live, "gaps") == "2 runs"
    large = OverviewRow(
        contract_id="CLG26",
        root="CL",
        frequency="minute",
        checked=True,
        families={"gaps": {"count": 21919, "unit": "runs", "detail": "not rendered"}},
    )
    assert family_cell(large, "gaps") == "21,919 runs"


def test_collect_rows_calls_checks_per_scope_and_not_findings():
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS)
    rows = collect_rows(client, MIXED_COVERAGE_CONTRACTS["data"])
    assert len(rows) == 4
    checks = [params for name, params in client.calls if name == "checks"]
    assert len(checks) == 4
    assert {params["frequency"] for params in checks} == {"minute", "daily"}
    assert all(params.get("start") is None and params.get("end") is None for params in checks)
    assert not any(name == "findings" for name, _ in client.calls)
    assert not any(name in {"bars_daily", "vwap"} for name, _ in client.calls)
    assert all(row.checked is True for row in rows)
    assert rows[0].families["gaps"]["count"] == CHECKS["families"][0]["count"]


def test_overview_is_the_default_destination(app):
    test = _no_exception(app(destination=None))
    nav = test.sidebar.segmented_control(key="destination_display")
    assert list(nav.options) == ["Overview", "Review"]
    assert nav.value == "Overview"
    assert _labels(test) == []
    assert _overview_table(test) is not None


def test_invalid_destination_falls_back_to_overview(app):
    test = _no_exception(app(destination="Not a page"))
    assert test.sidebar.segmented_control(key="destination_display").value == "Overview"
    assert test.session_state["destination"] == "Overview"


def test_style_overview_weights_contract_not_family_detail():
    frame = pd.DataFrame(
        {
            "Contract": ["ESZ25"],
            "Grain": ["Minute"],
            "Gaps": ["2 runs"],
        }
    )
    html = style_overview(frame).to_html()
    assert "font-weight: bold" in html
    assert "ESZ25" in html


def test_overview_table_has_family_tile_headers_and_one_row_per_grain(app):
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS)
    test = _no_exception(app(client=client, destination="Overview", destination_display="Overview"))
    assert not test.exception
    assert _labels(test) == []
    assert not any("Daily OHLCV" in h.value for h in test.subheader)
    assert any("loaded contracts × grain" in c.value for c in test.caption)
    table = _overview_table(test)
    assert list(table.columns) == [
        "Contract",
        "Grain",
        "Gaps",
        "Duplicates",
        "Invalid values",
        "Recurring patterns",
    ]
    assert len(table) == 4
    es = table[table["Contract"] == "ESZ25"]
    assert sorted(es["Grain"].tolist()) == ["Daily", "Minute"]
    assert (table["Contract"] == "ZCZ25").sum() == 1
    assert (table["Contract"] == "SR3G26").sum() == 1
    assert all("\n" not in str(value) for column in FAMILY_COLUMNS for value in table[column])
    assert not any(
        "session-open hole" in str(value) for column in FAMILY_COLUMNS for value in table[column]
    )
    assert not any(name in {"bars_daily", "vwap"} for name, _ in client.calls)
    assert not test.sidebar.selectbox
    assert not test.sidebar.date_input
    assert "Inject demo defects" in [b.label for b in test.button]


def test_overview_grain_filter_admits_and_rejects(app):
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS)
    test = _no_exception(app(client=client, destination="Overview", destination_display="Overview"))
    daily = _no_exception(test.segmented_control(key="overview_grain").set_value("Daily").run())
    daily_table = _overview_table(daily)
    assert set(daily_table["Grain"]) == {"Daily"}
    assert "ESZ25" in set(daily_table["Contract"])
    assert "SR3G26" not in set(daily_table["Contract"])

    minute = _no_exception(daily.segmented_control(key="overview_grain").set_value("Minute").run())
    minute_table = _overview_table(minute)
    assert set(minute_table["Grain"]) == {"Minute"}
    assert "SR3G26" in set(minute_table["Contract"])
    assert "ZCZ25" not in set(minute_table["Contract"])


def test_overview_click_through_opens_review_on_that_contract_and_grain(app):
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS)
    test = _no_exception(app(client=client, destination="Overview", destination_display="Overview"))
    test.session_state["overview_open"] = ("ESZ25", "minute")
    after = _no_exception(test.run())
    assert after.session_state["destination"] == "Review"
    assert after.session_state["contract"] == "ESZ25"
    assert after.session_state["quality_grain"] == "minute"
    assert _labels(after) == [
        "Gaps",
        "Duplicates",
        "Invalid values",
        "Recurring patterns",
    ]
    assert any("Minute quality grain" in c.value for c in after.caption)


def test_overview_empty_store_invites_demo_load(app):
    from ui_helpers import EMPTY_HEALTH

    client = FakeClient(health=EMPTY_HEALTH, contracts={"data": [], "total": 0})
    test = _no_exception(app(client=client, destination="Overview", destination_display="Overview"))
    assert "Load demo data" in [b.label for b in test.button]
    assert any("Load demo data" in i.value for i in test.info)
    assert not any(name == "checks" for name, _ in client.calls)
    assert not test.sidebar.selectbox
