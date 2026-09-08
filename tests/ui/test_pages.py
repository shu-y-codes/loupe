"""Page tests (`plans/09-reviewer-ui.md` done-when 7, solution brief §13).

`AppTest` over a stubbed client. These assert **view assembly** — four family cards as the
selector, no score caption, family overlay vs picture, VWAP refused in place, report-only —
and never a number the API decided.
"""

from __future__ import annotations

from datetime import date

from ui_helpers import (
    BATCHES,
    CHANGELOG,
    CHECKS,
    CONTRACTS,
    FINDINGS,
    HEALTH,
    MIXED_COVERAGE_BATCHES,
    MIXED_COVERAGE_CONTRACTS,
    MIXED_SCOPE,
    PATTERNS,
    RECONCILED,
    SUGGESTIONS,
    SUMMARY,
    SYNTHETIC_BATCHES,
    SYNTHETIC_HEALTH,
    VWAP_REFUSED,
    FakeClient,
)


def test_every_stub_matches_the_response_model_it_stands_in_for():
    """The guard for a whole class of silent failure.

    Unknown keys are the detectable half — a stub cannot be checked for keys it omits, since
    absence is legitimate. That is what the built-path tests are for.
    """
    from loupe.api import models

    envelopes = [
        ("SUMMARY", SUMMARY, models.DqSummaryResponse),
        ("MIXED_SCOPE", MIXED_SCOPE, models.DqSummaryResponse),
        ("RECONCILED", RECONCILED, models.DqSummaryResponse),
        ("CHECKS", CHECKS, models.DqChecksResponse),
        ("FAMILY_CARD", CHECKS["families"][0], models.FamilyCard),
        ("ISSUE", CHECKS["issues"][0], models.AggregatedIssue),
        ("OVERLAY_MARK", CHECKS["overlay"]["ohlcv"][0], models.OverlayMark),
        ("CONTRACTS", CONTRACTS, models.ContractsResponse),
        ("FINDING", FINDINGS[0], models.Finding),
        ("CHANGELOG", CHANGELOG[0], models.ChangelogEntry),
        ("CONTRACT_ROW", SUMMARY["contracts"][0], models.ContractSummary),
        ("SLICE", SUMMARY["slices"][0], models.SliceScore),
        ("HEALTH", HEALTH, models.Health),
        ("SYNTHETIC_HEALTH", SYNTHETIC_HEALTH, models.Health),
        ("BATCHES", BATCHES, models.BatchesResponse),
        ("BATCH", BATCHES["data"][0], models.BatchSummary),
        ("MIXED_COVERAGE_BATCHES", MIXED_COVERAGE_BATCHES, models.BatchesResponse),
        ("MIXED_COVERAGE_CONTRACTS", MIXED_COVERAGE_CONTRACTS, models.ContractsResponse),
        ("MIXED_CONTRACT", MIXED_COVERAGE_CONTRACTS["data"][0], models.Contract),
        ("SYNTHETIC_BATCHES", SYNTHETIC_BATCHES, models.BatchesResponse),
        ("INJECTED_BATCH", SYNTHETIC_BATCHES["data"][2], models.BatchSummary),
        ("CORROBORATION", FINDINGS[0]["corroboration"], models.Corroboration),
        ("PATTERN", PATTERNS["data"][0], models.Pattern),
        ("PATTERNS", PATTERNS, models.PatternsResponse),
        ("SUGGESTION", SUGGESTIONS["data"][0], models.Suggestion),
        ("SUGGESTIONS", SUGGESTIONS, models.SuggestionsResponse),
    ]
    for name, stub, model in envelopes:
        unknown = set(stub) - set(model.model_fields)
        assert not unknown, f"{name} invents fields the API never returns: {sorted(unknown)}"


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


# ----------------------------------------------------------------- chrome


def test_the_page_renders(app):
    _no_exception(app())


def test_review_nav_is_present_and_not_a_persona_radio(app):
    test = _no_exception(app())
    assert test.sidebar.segmented_control(key="destination_display").value == "Review"
    assert not test.sidebar.radio
    assert not test.radio


def test_the_sidebar_holds_contract_and_dates_and_no_persona_or_uploader(app):
    test = _no_exception(app())
    assert not test.sidebar.radio
    assert not test.radio
    assert [s.label for s in test.sidebar.selectbox] == ["Contract"]
    assert set(test.sidebar.selectbox[0].options) == {"ZCZ25", "ESZ25"}
    assert [d.label for d in test.sidebar.date_input] == ["From", "To"]
    assert not test.file_uploader
    assert not test.sidebar.file_uploader


def test_dual_grain_contract_defaults_minute_and_passes_it_explicitly(app):
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS)
    test = _no_exception(app(client=client))

    grain = test.sidebar.segmented_control(key="quality_grain_display")
    assert grain.value == "Minute"
    assert "Minute quality grain" in " ".join(c.value for c in test.caption)
    assert any(
        params.get("frequency") == "minute"
        for name, params in client.calls
        if name in {"checks", "bars_daily"}
    )


def test_daily_quality_grain_labels_vwap_context_and_preserves_dates(app):
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS)
    test = _no_exception(
        app(
            client=client,
            quality_grain="daily",
            quality_grain_display="Daily",
            start=None,
            end=None,
        )
    )

    assert test.sidebar.segmented_control(key="quality_grain_display").value == "Daily"
    assert any("context only for Daily quality grain" in c.value for c in test.caption)
    assert all(
        params.get("frequency") == "daily"
        for name, params in client.calls
        if name in {"checks", "bars_daily"}
    )


def test_explicit_dates_survive_contract_change(app):
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS)
    test = _no_exception(app(client=client))
    test.sidebar.date_input(key="start").set_value(date(2025, 1, 2))
    test.sidebar.date_input(key="end").set_value(date(2025, 1, 3))
    test = _no_exception(test.run())
    test = _no_exception(test.sidebar.selectbox(key="contract").select("ZCZ25").run())

    assert test.sidebar.date_input(key="start").value == date(2025, 1, 2)
    assert test.sidebar.date_input(key="end").value == date(2025, 1, 3)
    last_checks = [params for name, params in client.calls if name == "checks"][-1]
    assert last_checks["start"] == date(2025, 1, 2)
    assert last_checks["end"] == date(2025, 1, 3)


# ------------------------------------------------------------- family cards


def test_four_family_labels_are_visible_after_a_stubbed_load(app):
    test = _no_exception(app())
    assert _labels(test) == [
        "Gaps",
        "Duplicates",
        "Invalid values",
        "Recurring patterns",
    ]


def test_cards_are_the_family_control_not_a_check_row(app):
    test = _no_exception(app())
    labels = [getattr(control, "label", "") or "" for control in test.segmented_control]
    assert "Check" not in labels
    assert test.sidebar.segmented_control(key="destination_display").value == "Review"


def test_the_page_does_not_draw_a_score_caption(app):
    test = _no_exception(app())
    assert not any(c.value.startswith("Score ") for c in test.caption)
    captions = " ".join(c.value for c in test.caption)
    assert "cmp+val+con+unq+tim" not in captions
    assert "load the minute tape" not in captions.lower()
    assert any("Double-click" in c.value for c in test.caption)


def test_zero_on_a_card_is_a_real_answer(app):
    """Duplicates is 0 in the stub because the check ran, not because it is hidden."""
    test = _no_exception(app())
    counts = " ".join(m.value for m in test.markdown)
    assert "0 records" in counts
    assert "0 exact copies" in counts


def test_every_family_card_carries_one_sentence_of_help_on_the_count(app):
    test = _no_exception(app())
    # Count lines are markdown with help (not st.metric — count leads, detail is body).
    count_tiles = [
        m
        for m in test.markdown
        if m.help and any(unit in m.value for unit in ("runs", "records", "rows", "standing"))
    ]
    assert len(count_tiles) == 4
    for tile in count_tiles:
        assert tile.help.count(".") <= 2, f"{tile.value!r} help is not one line"
    blob = " ".join(m.value for m in test.markdown)
    assert "2 runs" in blob
    assert "0 records" in blob
    assert "1 rows" in blob
    assert "1 standing" in blob
    assert "1.125rem" in blob


# ----------------------------------------------------------------- overlay


def test_gaps_vs_invalid_changes_overlay_marks_not_only_a_caption(app):
    """Same overlay payload, different picture. The family switch is not a renamed caption."""
    gaps = _no_exception(app(family="gaps"))
    invalid = _no_exception(app(family="invalid"))

    assert any("Picture of gaps" in h.value for h in gaps.subheader)
    pictures = " ".join(m.value for m in invalid.markdown)
    assert "Broken cell" in pictures
    gaps_pictures = " ".join(m.value for m in gaps.markdown)
    assert "Broken cell" not in gaps_pictures


def test_clicking_a_card_changes_the_overlay_family(app):
    """The cells are the selector. A second Check control would fail this click."""
    client = FakeClient()
    test = _no_exception(app(client=client))
    labels = [getattr(control, "label", "") or "" for control in test.segmented_control]
    assert "Check" not in labels
    card = next(b for b in test.button if b.label == "Invalid values")
    after = _no_exception(card.click().run())
    assert after.session_state["family"] == "invalid"
    pictures = " ".join(m.value for m in after.markdown)
    assert "Broken cell" in pictures
    families = [params.get("family") for name, params in client.calls if name == "checks"]
    assert "invalid" in families


def test_issues_table_is_what_days_records_what_we_did(app):
    test = _no_exception(app())
    tables = [list(d.value.columns) for d in test.dataframe]
    assert ["What", "Days", "Records", "What we did"] in tables
    issues = next(d.value for d in test.dataframe if "What we did" in list(d.value.columns))
    assert "Missing grid slots" in list(issues["What"])
    assert not any("OUT.RETURN_MAD" in str(v) for v in issues["What"])


def test_explanation_cells_are_not_given_cell_level_help_keys_beyond_headers():
    """Help lives on column headers. What / What we did *cells* are already the explanation."""
    from loupe.ui import help as helptext

    for column in ("What", "Days", "Records", "What we did"):
        assert column in helptext.COLUMNS
    for gone in ("Why", "Impact", "Address"):
        assert gone not in helptext.COLUMNS


# ------------------------------------------------------------ report-only v1


def test_no_apply_or_override_control_exists_in_the_tree(app):
    """v1 reports and does not apply. Asserted as absence from the whole element tree."""
    test = _no_exception(app())
    labels = [b.label.lower() for b in test.button]
    labels += [c.label.lower() for c in test.checkbox]
    labels += [s.label.lower() for s in test.selectbox]
    labels += [s.label.lower() for s in test.sidebar.selectbox]
    forbidden = ("apply", "override", "dismiss", "accept", "resolve", "edit")
    assert not [label for label in labels if any(word in label for word in forbidden)], labels


# -------------------------------------------------------- capability refusal


def test_vwap_is_refused_in_place_rather_than_rendered_empty(app):
    """A daily-only contract gets an explanation where the chart would be, not a blank one."""
    client = FakeClient(vwap=VWAP_REFUSED)
    test = _no_exception(app(client=client))
    explained = [i.value for i in test.info if "minute bars" in i.value.lower()]
    assert explained, "the VWAP panel must stay and say what it needs"
    assert any("Rolling 15-minute VWAP" in h.value for h in test.subheader)


def test_a_vwap_that_exists_is_drawn(app):
    test = _no_exception(app())
    assert not [i for i in test.info if "needs minute bars" in i.value.lower()]


# --------------------------------------------------------------- degradation


def test_an_api_that_is_not_running_is_reported_rather_than_traced(app):
    from loupe.ui.client import ApiUnavailable

    client = FakeClient(health=ApiUnavailable("No answer from http://127.0.0.1:8000/v1"))
    test = app(client=client)
    assert not test.exception
    assert any("No answer" in e.value for e in test.error)


def test_an_empty_store_invites_demo_load_not_upload(app):
    from ui_helpers import EMPTY_HEALTH

    client = FakeClient(
        health=EMPTY_HEALTH,
        contracts={"data": [], "total": 0},
        checks={**CHECKS, "checked": False, "families": CHECKS["families"]},
    )
    test = _no_exception(app(client=client))
    assert "Load demo data" in [b.label for b in test.button]
    assert any("Load demo data" in i.value for i in test.info)
    assert not any("Upload" in i.value for i in test.info)
    assert not test.file_uploader
    assert not test.sidebar.selectbox
