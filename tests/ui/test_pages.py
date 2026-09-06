"""Page tests (`plans/05-ui.md` done-when 4, solution brief §13).

`AppTest` over a stubbed client. These assert **view assembly** — which columns a persona
gets, that a refusal is explained in place, that report-only means no apply control anywhere
in the element tree — and never a number the API decided.
"""

from __future__ import annotations

import pytest
from ui_helpers import NOT_BUILT, SUMMARY, VWAP_REFUSED, FakeClient


def _no_exception(test):
    assert not test.exception, [str(e.value) for e in test.exception]
    return test


def _labels(test) -> list[str]:
    return [m.label for m in test.metric]


def _columns(test, index: int = 0) -> list[str]:
    return list(test.dataframe[index].value.columns)


# ----------------------------------------------------------------- chrome


def test_the_page_renders_for_every_persona(app):
    for persona in ("Risk", "Trader", "Analyst"):
        _no_exception(app(persona))


def test_the_sidebar_holds_persona_dates_and_upload(app):
    test = _no_exception(app("Risk"))
    assert [r.label for r in test.sidebar.radio] == ["Persona"]
    assert set(test.sidebar.radio[0].options) == {"Risk", "Trader", "Analyst"}
    assert [d.label for d in test.sidebar.date_input] == ["From", "To"]


# --------------------------------------------------------- persona switching


def test_persona_switch_changes_the_summary_columns(app):
    """The same page, different columns — the whole claim of the persona selector."""
    risk = _columns(_no_exception(app("Risk")))
    trader = _columns(_no_exception(app("Trader")))
    analyst = _columns(_no_exception(app("Analyst")))

    assert risk == ["Status", "Root", "Contract", "Score", "Closing-day"]
    assert trader == ["Root", "Contract", "Score", "Warning"]
    assert analyst == ["Root", "Contract", "Score", "Findings", "Top issue"]

    # Risk is the only persona with a go/needs-attention column; Trader's score carries it.
    assert "Status" not in trader and "Status" not in analyst


def test_each_persona_gets_its_own_headline_tiles(app):
    assert _labels(_no_exception(app("Risk"))) == ["DQ score", "Book hit", "Completeness"]
    assert _labels(_no_exception(app("Trader"))) == ["Contracts", "With warnings"]
    assert _labels(_no_exception(app("Analyst"))) == [
        "DQ score",
        "Open findings",
        "Both frequencies",
        "Worst field",
    ]


def test_book_hit_counts_the_attention_rows(app):
    """One ATTN of two contracts in the fixture."""
    test = _no_exception(app("Risk"))
    book = next(m for m in test.metric if m.label == "Book hit")
    assert book.value == "1 of 2"


def test_worst_field_reads_not_applicable_when_no_mapped_rule_fired(app):
    """§11.7's absent state is rendered as words, never as a blank or a fabricated field."""
    without = FakeClient(summary={**SUMMARY, "worst_field": None})
    test = _no_exception(app("Analyst", client=without))
    tile = next(m for m in test.metric if m.label == "Worst field")
    assert tile.value == "not applicable"


# ------------------------------------------------------------------ callouts


def test_risk_shows_the_settlement_callout_and_an_em_dash_where_there_is_none(app):
    test = _no_exception(app("Risk"))
    frame = test.dataframe[0].value
    closing = dict(zip(frame["Contract"], frame["Closing-day"], strict=True))
    assert closing["ZCZ25"] == "Close outside the bar range"
    # ESZ25 is minute-only, so it has no settlement callout — an em dash, not a stand-in.
    assert closing["ESZ25"] == "—"


def test_trader_and_analyst_read_the_unfiltered_callout(app):
    """The same contract, a different question: Trader's Warning is not Risk's Closing-day."""
    trader = _no_exception(app("Trader")).dataframe[0].value
    warnings = dict(zip(trader["Contract"], trader["Warning"], strict=True))
    assert warnings["ESZ25"] == "Missing timestamps"


def test_every_kpi_tile_carries_one_sentence_of_help(app):
    for persona in ("Risk", "Trader", "Analyst"):
        test = _no_exception(app(persona))
        for tile in test.metric:
            assert tile.help, f"{persona}: {tile.label} has no help"
            assert tile.help.count(".") <= 2, f"{persona}: {tile.label} help is not one line"


def test_the_explanation_cells_are_never_given_help(app):
    """Why / Impact / Address and the findings What column explain themselves.

    Asserted against the help catalogue rather than the rendered proto: the policy is that no
    entry exists for those headers, so no code path can attach one.
    """
    from loupe.ui import help as helptext

    for column in ("Why", "Impact", "Address", "What"):
        assert column not in helptext.COLUMNS

    test = _no_exception(app("Risk", contract="ZCZ25"))
    assert [d for d in test.dataframe if "Why" in list(d.value.columns)]


# ----------------------------------------------------------------- specifics


def test_specifics_waits_for_a_selection(app):
    test = _no_exception(app("Risk"))
    assert any("Select a contract" in i.value for i in test.info)


def test_specifics_leads_with_why_impact_address(app):
    test = _no_exception(app("Risk", contract="ZCZ25"))
    tables = [list(d.value.columns) for d in test.dataframe]
    assert ["Why", "Impact", "Address"] in tables


def test_address_is_text_and_says_why_there_is_no_suggestion_yet(app):
    """Done-when 9: build against the slice 6 route, never stub the copy in a widget."""
    client = FakeClient(suggestions=NOT_BUILT)
    test = _no_exception(app("Risk", client=client, contract="ZCZ25"))
    table = next(d.value for d in test.dataframe if "Address" in list(d.value.columns))
    assert "report" in table["Address"].iloc[0].lower()


# ------------------------------------------------------------ report-only v1


@pytest.mark.parametrize("persona", ["Risk", "Trader", "Analyst"])
def test_no_apply_or_override_control_exists_in_the_tree(app, persona):
    """v1 reports and does not apply. Asserted as absence from the whole element tree."""
    test = _no_exception(app(persona, contract="ZCZ25"))
    labels = [b.label.lower() for b in test.button]
    labels += [c.label.lower() for c in test.checkbox]
    labels += [s.label.lower() for s in test.selectbox]
    forbidden = ("apply", "override", "dismiss", "accept", "resolve", "edit")
    assert not [
        label for label in labels if any(word in label for word in forbidden)
    ], labels


# -------------------------------------------------------- capability refusal


def test_vwap_is_refused_in_place_rather_than_rendered_empty(app):
    """A daily-only contract gets an explanation where the chart would be, not a blank one.

    This is the last step of the three-way distinction slice 3 built and slice 4 surfaced:
    refused, empty and blocked are different answers, and the UI must not collapse them.
    """
    client = FakeClient(vwap=VWAP_REFUSED)
    test = _no_exception(app("Trader", client=client, contract="ZCZ25"))
    explained = [i.value for i in test.info if "minute bars" in i.value]
    assert explained, "the VWAP panel must stay and say what it needs"


def test_a_vwap_that_exists_is_drawn(app):
    test = _no_exception(app("Trader", contract="ZCZ25"))
    assert not [i for i in test.info if "needs minute bars" in i.value.lower()]


# ----------------------------------------------------------------- changelog


def test_trader_specifics_shows_the_changelog_as_counts(app):
    test = _no_exception(app("Trader", contract="ZCZ25"))
    tables = [d.value for d in test.dataframe if "Action" in list(d.value.columns)]
    assert tables, "the changelog panel is part of the Trader view"
    assert tables[0]["Records"].iloc[0] == 4


# ----------------------------------------------------- analyst deep view


def test_the_neighbourhood_is_collapsed_until_a_finding_is_selected(app):
    test = _no_exception(app("Analyst", contract="ZCZ25"))
    assert any("Select a finding" in c.value for c in test.caption)


def test_patterns_and_suggestions_explain_that_they_ship_later(app):
    client = FakeClient(insights_patterns=NOT_BUILT, insights_suggestions=NOT_BUILT)
    test = _no_exception(app("Analyst", client=client, contract="ZCZ25"))
    captions = " ".join(c.value for c in test.caption)
    assert "not in this build" in captions


# --------------------------------------------------------------- degradation


def test_an_api_that_is_not_running_is_reported_rather_than_traced(app):
    from loupe.ui.client import ApiUnavailable

    client = FakeClient(summary=ApiUnavailable("No answer from http://127.0.0.1:8000/v1"))
    test = app("Risk", client=client)
    assert not test.exception
    assert any("No answer" in e.value for e in test.error)


def test_an_empty_store_invites_an_upload(app):
    client = FakeClient(summary={**SUMMARY, "contracts": [], "slices": []})
    test = _no_exception(app("Risk", client=client))
    assert any("Upload" in i.value for i in test.info)
