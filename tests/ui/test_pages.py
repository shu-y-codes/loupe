"""Page tests (`plans/05-ui.md` done-when 4, solution brief §13).

`AppTest` over a stubbed client. These assert **view assembly** — which columns a persona
gets, that a refusal is explained in place, that report-only means no apply control anywhere
in the element tree — and never a number the API decided.
"""

from __future__ import annotations

import pytest
from ui_helpers import (
    BATCHES,
    CHANGELOG,
    CONTRACTS,
    FINDINGS,
    HEALTH,
    MIXED_SCOPE,
    NOT_BUILT,
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

    `render_preview` once read `capabilities` and `rejects_estimated`; the API returns
    `enables` and `warnings`. The capability disclosure never fired in production while every
    test passed, because the fixture had been written to match the code instead of the
    contract. A stub shaped like the page expects rather than like the API answers can only
    ever confirm the page's own assumptions.

    Unknown keys are the detectable half — a stub cannot be checked for keys it omits, since
    absence is legitimate. That is what the built-path tests are for.
    """
    from loupe.api import models

    envelopes = [
        ("SUMMARY", SUMMARY, models.DqSummaryResponse),
        ("MIXED_SCOPE", MIXED_SCOPE, models.DqSummaryResponse),
        ("RECONCILED", RECONCILED, models.DqSummaryResponse),
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


def _columns(test, index: int = 0) -> list[str]:
    return list(test.dataframe[index].value.columns)


# ----------------------------------------------------------------- chrome


def test_the_page_renders_for_every_persona(app):
    for persona in ("Risk", "Trader", "Analyst"):
        _no_exception(app(persona))


def test_the_sidebar_holds_persona_and_dates_and_no_uploader(app):
    test = _no_exception(app("Risk"))
    assert [r.label for r in test.sidebar.radio] == ["Persona"]
    assert set(test.sidebar.radio[0].options) == {"Risk", "Trader", "Analyst"}
    assert [d.label for d in test.sidebar.date_input] == ["From", "To"]
    assert not test.file_uploader
    assert not test.sidebar.file_uploader


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


def test_the_worst_field_tile_states_its_denominator(app):
    """§11.5's rule for scores applied to this tile: say what the number is out of.

    The map excludes three groups of rules by design, so the winning field can rest on a
    small minority of what is open. Naming the field alone invites the reader to think it
    summarises every finding on the screen.
    """
    test = _no_exception(app("Analyst"))
    captions = " ".join(c.value for c in test.caption)
    assert "6 of 10 open findings name a field" in captions


def test_the_denominator_caption_is_absent_rather_than_wrong_when_unknown(app):
    """An older envelope must not take the page down over a caption."""
    client = FakeClient(summary={**SUMMARY, "worst_field": {"field": "close", "findings": 6}})
    test = _no_exception(app("Analyst", client=client))
    tile = next(m for m in test.metric if m.label == "Worst field")
    assert tile.value == "close"


def test_risk_says_when_no_daily_records_are_loaded(app):
    """An empty Closing-day column is ambiguous; only one of its two meanings is true here.

    "Nothing wrong with the close" and "we cannot see the close from here" render identically
    as em dashes, and on a minute-only corpus it is always the second.
    """
    minute_only = {
        **SUMMARY,
        "contracts": [
            {**row, "frequencies": ["minute"], "settlement_issue": None}
            for row in SUMMARY["contracts"]
        ],
    }
    test = _no_exception(app("Risk", client=FakeClient(summary=minute_only)))
    notices = [i.value for i in test.info if "No daily records loaded" in i.value]
    assert len(notices) == 2, "both the inventory and the trend tile should say so"
    assert any("settlement lives in the daily file" in n for n in notices)


def test_risk_stays_quiet_about_daily_records_when_some_are_loaded(app):
    test = _no_exception(app("Risk"))
    assert not [i for i in test.info if "No daily records loaded" in i.value]


def test_a_score_says_which_dimensions_it_was_measured_over(app):
    """§11.3: a five-dimension score is not a six-dimension score wearing the same number.

    Without this the Risk screen shows a confident composite whose settlement evidence was
    never cross-checked, and nothing on the page distinguishes it from one that was.
    """
    test = _no_exception(app("Risk"))
    captions = " ".join(c.value for c in test.caption)
    assert "cmp+val+con+unq+tim" in captions
    assert "only one frequency" in captions
    assert "load the minute tape" in captions.lower()


def test_the_disclosure_names_the_consequence_the_persona_cares_about(app):
    """Same missing dimension, different stake: Risk loses settlement evidence, the Analyst
    loses comparability between two contracts' scores."""
    risk = " ".join(c.value for c in _no_exception(app("Risk")).caption)
    analyst = " ".join(c.value for c in _no_exception(app("Analyst")).caption)

    assert "minute tape" in risk
    assert "not directly comparable" in analyst


def test_nothing_is_disclosed_when_every_dimension_was_in_scope(app):
    """The notice must be absent when it would be false, or it becomes furniture."""
    test = _no_exception(app("Risk", client=FakeClient(summary=RECONCILED)))
    captions = " ".join(c.value for c in test.caption)
    assert "only one frequency" not in captions
    assert "load the minute tape" not in captions.lower()


def test_a_reduced_scope_score_is_marked_in_the_inventory(app):
    """A headline caption cannot say *which row* covers fewer dimensions; the column can.

    ZCZ25 is daily-only and ESZ25 holds both, so the table sorts a five-dimension 41 against a
    six-dimension 96 and they look equally authoritative without the mark.
    """
    test = _no_exception(app("Risk", client=FakeClient(summary=MIXED_SCOPE)))
    frame = test.dataframe[0].value
    scores = dict(zip(frame["Contract"], frame["Score"], strict=True))

    assert scores["ZCZ25"].endswith("†"), "the reduced-scope score is unmarked"
    assert not scores["ESZ25"].endswith("†"), "the fully-scoped score must stay clean"

    captions = " ".join(c.value for c in test.caption)
    assert "† scored without reconciliation" in captions
    assert "ZCZ25" in captions, "the caption names which contract is affected"
    assert "not directly comparable" in captions.lower()


def test_the_mark_is_absent_when_every_contract_shares_a_signature(app):
    """Uniform scope is comparable within the table, so the mark would be noise.

    The absolute limitation is still disclosed by the headline caption — this asserts the
    per-row mark is reserved for the case it exists to catch.
    """
    for envelope in (SUMMARY, RECONCILED):
        test = _no_exception(app("Risk", client=FakeClient(summary=envelope)))
        frame = test.dataframe[0].value
        assert not [s for s in frame["Score"] if s.endswith("†")]
        captions = " ".join(c.value for c in test.caption)
        assert "scored without reconciliation" not in captions


def test_the_mark_reaches_every_persona_that_shows_a_score_column(app):
    for persona in ("Risk", "Trader", "Analyst"):
        test = _no_exception(app(persona, client=FakeClient(summary=MIXED_SCOPE)))
        frame = test.dataframe[0].value
        assert any(s.endswith("†") for s in frame["Score"]), persona


def test_the_disclosure_caption_reads_as_sentences(app):
    """It concatenated a reason fragment straight onto the next sentence."""
    test = _no_exception(app("Risk"))
    caption = next(c.value for c in test.caption if c.value.startswith("Scored over"))
    assert "contract Settlement" not in caption
    assert "for this contract. Settlement" in caption


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


def test_address_carries_real_suggestion_text_when_the_route_answers(app):
    """The built path. This is the assertion slice 5 could not make and slice 6 must.

    `_address()` needed no new code when the route shipped — which is exactly the risk, because
    the 404 test below keeps passing whether or not the populated branch works. Asserted
    against the stub's own rationale so it cannot pass on the pending sentence.
    """
    from ui_helpers import SUGGESTIONS

    test = _no_exception(app("Risk", contract="ZCZ25"))
    table = next(d.value for d in test.dataframe if "Address" in list(d.value.columns))
    address = table["Address"].iloc[0]

    assert address == SUGGESTIONS["data"][0]["rationale"]
    assert "this release reports and does not apply" not in address


def test_address_says_why_there_is_no_suggestion_when_the_route_is_absent(app):
    """The other side of the branch, kept: a UI pointed at an older API must explain itself."""
    client = FakeClient(insights_suggestions=NOT_BUILT)
    test = _no_exception(app("Risk", client=client, contract="ZCZ25"))
    table = next(d.value for d in test.dataframe if "Address" in list(d.value.columns))
    assert "report" in table["Address"].iloc[0].lower()


def test_address_distinguishes_no_suggestion_from_no_report(app):
    """An empty list is a different answer from a missing route, and the cell says which.

    "No suggestion for this contract" means the report ran and found nothing to propose;
    "not in this build" means it never ran. Collapsing them would tell a reader their data is
    fine when the truth is that nobody looked.
    """
    client = FakeClient(insights_suggestions={"data": [], "total": 0})
    test = _no_exception(app("Risk", client=client, contract="ZCZ25"))
    table = next(d.value for d in test.dataframe if "Address" in list(d.value.columns))
    address = table["Address"].iloc[0]
    assert "No suggestion" in address
    assert "build" not in address


def test_the_why_cell_states_what_the_tape_makes_of_a_daily_finding(app):
    """`specs/loupe-ui-design.md`: the corroboration state rides in **Why**, beside the finding.

    Rendered from the envelope, not derived here — the cell prints the API's own sentence, so a
    widget cannot quietly soften what `quality` decided.
    """
    test = _no_exception(app("Risk", contract="ZCZ25"))
    table = next(d.value for d in test.dataframe if "Why" in list(d.value.columns))
    why = table["Why"].iloc[0]
    assert "range disputed" in why
    assert "found prints above the stated high" in why


def test_confirmed_and_disputed_read_as_opposite_instructions(app):
    """The two states must not render alike: one says trust the range, the other says do not.

    Same rule, same contract, same date — only the state differs, which is exactly the pair a
    reader has to be able to tell apart at a glance.
    """
    from ui_helpers import CONFIRMED_FINDINGS

    client = FakeClient(findings={"data": CONFIRMED_FINDINGS, "total": 2})
    test = _no_exception(app("Risk", client=client, contract="ZCZ25"))
    confirmed = next(d.value for d in test.dataframe if "Why" in list(d.value.columns))
    assert "range confirmed against the tape" in confirmed["Why"].iloc[0]
    assert "disputed" not in confirmed["Why"].iloc[0]

    default = _no_exception(app("Risk", contract="ZCZ25"))
    disputed = next(d.value for d in default.dataframe if "Why" in list(d.value.columns))
    assert confirmed["Why"].iloc[0] != disputed["Why"].iloc[0]


def test_a_finding_without_corroboration_gets_no_second_line(app):
    """Absent is the fourth answer, and it renders as silence rather than as a caveat.

    `not_comparable` would say "we could not check"; nothing at all says the question does not
    arise. Printing the first where the truth is the second invents a doubt about the daily
    file that the finding never raised.
    """
    test = _no_exception(app("Risk", contract="ZCZ25"))
    table = next(d.value for d in test.dataframe if "Why" in list(d.value.columns))
    minute_row = table["Why"].iloc[1]
    assert "\n" not in minute_row
    assert "corroborat" not in minute_row.lower()


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


def test_the_patterns_panel_renders_the_rows_the_route_returns(app):
    """Done-when 9's built path. `_report()` needed no new code, so nothing tested it.

    Asserted against the stub's own values — the lift, the bucket and the narrative — so it
    cannot pass against a panel that renders an empty frame or the "not in this build" caption.
    """
    from ui_helpers import PATTERNS

    test = _no_exception(app("Analyst", contract="ZCZ25"))
    pattern = PATTERNS["data"][0]
    frames = [d.value for d in test.dataframe if "lift" in list(d.value.columns)]
    assert frames, "the patterns panel drew no table"

    frame = frames[0]
    assert pattern["bucket"] in list(frame["bucket"])
    assert pattern["lift"] in list(frame["lift"])
    assert pattern["narrative"] in list(frame["narrative"])


def test_the_suggestions_panel_renders_the_rows_the_route_returns(app):
    """The second half of the same panel, asserted on its own: the two reports come from two
    routes, and one of them working says nothing about the other."""
    from ui_helpers import SUGGESTIONS

    test = _no_exception(app("Analyst", contract="ZCZ25"))
    suggestion = SUGGESTIONS["data"][0]
    frames = [d.value for d in test.dataframe if "rationale" in list(d.value.columns)]
    assert frames, "the suggestions panel drew no table"
    assert suggestion["title"] in list(frames[0]["title"])


def test_the_rendered_suggestion_offers_nothing_to_press(app):
    """Report-only reaches the rendered table too, not only the payload.

    A suggestion carries a `proposed_change`, which is a description of a change and not a
    request to make one. No column and no control in the tree may read as an action.
    """
    test = _no_exception(app("Analyst", contract="ZCZ25"))
    frames = [d.value for d in test.dataframe if "rationale" in list(d.value.columns)]
    assert frames
    columns = {c.lower() for c in frames[0].columns}
    assert not (columns & {"actions", "apply", "dismiss"})


def test_patterns_and_suggestions_explain_themselves_when_the_routes_are_absent(app):
    """The 404 side, kept. Both branches matter: a panel that renders nothing is ambiguous
    between "no patterns" and "no report"."""
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


def test_an_empty_store_invites_demo_load_not_upload(app):
    from ui_helpers import EMPTY_HEALTH

    client = FakeClient(health=EMPTY_HEALTH, summary={**SUMMARY, "contracts": [], "slices": []})
    test = _no_exception(app("Risk", client=client))
    assert "Load demo data" in [b.label for b in test.button]
    assert any("Load demo data" in i.value for i in test.info)
    assert not any("Upload" in i.value for i in test.info)
    assert not test.file_uploader
