"""Page tests (`plans/09-reviewer-ui.md` done-when 7, solution brief §13).

`AppTest` over a stubbed client. These assert **view assembly** — four family cards, family
overlay vs caption, VWAP refused in place, report-only — and never a number the API decided.
"""

from __future__ import annotations

from ui_helpers import (
    BATCHES,
    CHANGELOG,
    CHECKS,
    CONTRACTS,
    FINDINGS,
    HEALTH,
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
    return [m.label for m in test.metric]


def _legend(test) -> str:
    return " ".join(
        c.value
        for c in test.caption
        if c.value.startswith("Triangles:")
        or c.value.startswith("Painted:")
        or c.value.startswith("Pins on")
        or c.value.startswith("Bands on")
    )


# ----------------------------------------------------------------- chrome


def test_the_page_renders(app):
    _no_exception(app())


def test_the_sidebar_holds_contract_and_dates_and_no_persona_or_uploader(app):
    test = _no_exception(app())
    assert not test.sidebar.radio
    assert not test.radio
    assert [s.label for s in test.sidebar.selectbox] == ["Contract"]
    assert set(test.sidebar.selectbox[0].options) == {"ZCZ25", "ESZ25"}
    assert [d.label for d in test.sidebar.date_input] == ["From", "To"]
    assert not test.file_uploader
    assert not test.sidebar.file_uploader


# ------------------------------------------------------------- family cards


def test_four_family_labels_are_visible_after_a_stubbed_load(app):
    test = _no_exception(app())
    assert _labels(test) == [
        "Gaps",
        "Duplicates",
        "Invalid values",
        "Recurring patterns",
    ]


def test_zero_on_a_card_is_a_real_answer(app):
    """Duplicates is 0 in the stub because the check ran, not because it is hidden."""
    test = _no_exception(app())
    dup = next(m for m in test.metric if m.label == "Duplicates")
    assert dup.value.startswith("0")


def test_every_family_card_carries_one_sentence_of_help(app):
    test = _no_exception(app())
    for tile in test.metric:
        assert tile.help, f"{tile.label} has no help"
        assert tile.help.count(".") <= 2, f"{tile.label} help is not one line"


def test_a_score_says_which_dimensions_it_was_measured_over(app):
    """§11.3: a five-dimension score is not a six-dimension score wearing the same number."""
    test = _no_exception(app())
    captions = " ".join(c.value for c in test.caption)
    assert "cmp+val+con+unq+tim" in captions
    assert "only one frequency" in captions
    assert "load the minute tape" in captions.lower()


def test_the_disclosure_caption_reads_as_sentences(app):
    test = _no_exception(app())
    caption = next(c.value for c in test.caption if c.value.startswith("Score "))
    assert "contract Settlement" not in caption
    assert "for this contract. Settlement" in caption


def test_nothing_is_disclosed_when_every_dimension_was_in_scope(app):
    """The notice must be absent when it would be false, or it becomes furniture."""
    body = {**CHECKS, "dimensions_not_in_scope": [], "scope_signature": "cmp+val+con+unq+tim+rec"}
    test = _no_exception(app(client=FakeClient(checks=body)))
    captions = " ".join(c.value for c in test.caption)
    assert "only one frequency" not in captions
    assert "load the minute tape" not in captions.lower()
    assert "Zero on a card means the check ran" in captions


# ----------------------------------------------------------------- overlay


def test_gaps_vs_invalid_changes_overlay_marks_not_only_a_caption(app):
    """Same overlay payload, different flags drawn. A renamed caption would share dates."""
    gaps = _no_exception(app(family="gaps"))
    invalid = _no_exception(app(family="invalid"))

    gaps_legend = _legend(gaps)
    invalid_legend = _legend(invalid)

    assert gaps_legend.startswith("Triangles:")
    assert "2025-12-11" in gaps_legend
    assert "2025-09-16" in gaps_legend
    assert "Painted:" not in gaps_legend

    assert invalid_legend.startswith("Painted:")
    assert "2025-12-12" in invalid_legend
    assert "Triangles:" not in invalid_legend
    assert gaps_legend != invalid_legend

    pictures = " ".join(m.value for m in invalid.markdown)
    assert "Broken cell" in pictures or "close" in pictures.lower()


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
    assert not [
        label for label in labels if any(word in label for word in forbidden)
    ], labels


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
