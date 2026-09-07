"""The demo panel and the synthetic-data disclosure (`plans/07-demo-corpus.md`).

The disclosure tests are the reason this file exists. Done-when 5 turns on a property that is
easy to satisfy badly: *a reader who arrives mid-session, or reloads, still knows*. A notice
rendered once when the button is pressed satisfies "the user was told" and fails that property
completely, because Streamlit reruns on every interaction — change family, pick
a contract, and the notice is three reruns gone while the findings remain.

So every disclosure test here runs the page **twice** and asserts on the second run.
"""

from __future__ import annotations

import json

import pytest
from ui_helpers import (
    EMPTY_HEALTH,
    HEALTH,
    MIXED_COVERAGE_BATCHES,
    MIXED_COVERAGE_CONTRACTS,
    PLANTED_MANIFEST,
    SYNTHETIC_BATCHES,
    SYNTHETIC_HEALTH,
    FakeClient,
)


def _no_exception(test):
    assert not test.exception, [str(e.value) for e in test.exception]
    return test


def _text(test) -> str:
    """Everything the page said, whatever element it said it in."""
    parts = [w.value for w in test.warning] + [c.value for c in test.caption]
    parts += [i.value for i in test.info] + [m.value for m in test.markdown]
    parts += [e.value for e in test.error]
    return " ".join(parts)


# ----------------------------------------------------------- the disclosure that persists


def test_a_store_with_planted_defects_says_so(app):
    client = FakeClient(health=SYNTHETIC_HEALTH)
    test = _no_exception(app(client=client))

    banner = " ".join(w.value for w in test.warning)
    assert "planted defects" in banner
    assert "345" in banner, "the disclosure quantifies what is synthetic"
    assert "partly synthetic" in banner.lower()


def test_the_disclosure_survives_a_rerun(app):
    """Done-when 5, stated as the property rather than as the moment.

    Two full script runs. The second is the one that matters: it stands in for every
    interaction after the injection — a family switch, a date change, a contract pick — and a
    notice that only fired on the injection rerun would be gone by now.
    """
    client = FakeClient(health=SYNTHETIC_HEALTH)
    first = _no_exception(app(client=client))
    assert "planted defects" in " ".join(w.value for w in first.warning)

    second = _no_exception(first.run())
    assert "planted defects" in " ".join(w.value for w in second.warning)


def test_the_disclosure_survives_a_family_switch(app):
    """The likeliest real interaction, and it must not be the one that clears the notice."""
    client = FakeClient(health=SYNTHETIC_HEALTH)
    for family in ("gaps", "invalid", "patterns"):
        test = _no_exception(app(client=client, family=family))
        assert "planted defects" in " ".join(w.value for w in test.warning), family


def test_nothing_is_disclosed_when_nothing_was_planted(app):
    """The other side of the filter. A banner that always showed would say nothing at all.

    Asserted over warnings rather than over all page text, and the distinction is real: the
    *offer* to inject describes what it would plant, which is the panel doing its job. What
    must be absent is the claim that the store already holds synthetic data.
    """
    test = _no_exception(app())
    warnings = " ".join(w.value for w in test.warning).lower()
    assert "contains planted defects" not in warnings
    assert "synthetic records" not in warnings


def test_the_disclosure_reaches_the_page_before_any_score(app):
    """It is rendered ahead of the summary, so a reader cannot meet a number without it.

    Asserted on ordering rather than presence: a notice below the inventory is a footnote, and
    the claim being made is that no score is shown unqualified.
    """
    from loupe.ui import app as page

    client = FakeClient(health=SYNTHETIC_HEALTH)
    _no_exception(app(client=client))

    source = page.main.__code__.co_names
    assert "render_synthetic_notice" in source
    assert source.index("render_synthetic_notice") < source.index("load_checks")


# ------------------------------------------------------------------------- the two buttons


def test_an_empty_store_offers_the_fetch_and_says_what_it_downloads(app):
    """Consent before bytes: §1 found no licence grant, so the reader decides knowingly."""
    client = FakeClient(health=EMPTY_HEALTH)
    test = _no_exception(app(client=client))

    labels = [b.label for b in test.button]
    assert "Load demo data" in labels
    assert "Inject demo defects" not in labels, "there is nothing to inject into yet"

    said = _text(test)
    assert "Hugging Face" in said or "huggingface" in said.lower()
    assert "redistribution" in said


def test_a_loaded_store_offers_injection_and_not_the_fetch(app):
    """Two clicks, in order. The second only appears once there is real data to contrast with."""
    test = _no_exception(app())
    labels = [b.label for b in test.button]

    assert "Inject demo defects" in labels
    assert "Load demo data" not in labels


def test_injection_says_what_it_will_do_before_it_is_pressed(app):
    """Planting defects is not something to discover afterwards."""
    test = _no_exception(app())
    said = _text(test)
    assert "copy" in said.lower(), "the vendor files are not modified, and it says so"
    assert "manifest" in said.lower()


def test_a_synthetic_store_offers_the_way_back(app):
    """Done-when 6. A demo that can only be undone with `rm` is one nobody presses."""
    client = FakeClient(health=SYNTHETIC_HEALTH)
    test = _no_exception(app(client=client))
    labels = [b.label for b in test.button]

    assert "Remove demo defects" in labels
    assert "Inject demo defects" not in labels, "already injected; the offer would be a no-op"


@pytest.mark.parametrize("health", [EMPTY_HEALTH, HEALTH, SYNTHETIC_HEALTH])
def test_no_demo_control_reads_as_an_apply_or_override(app, health):
    """The report-only guarantee is not weakened by the demo panel.

    `tests/ui/test_pages.py` asserts this over the whole tree already; repeating it across the
    three demo states is what stops a new button being the exception.
    """
    client = FakeClient(health=health)
    test = _no_exception(app(client=client))
    labels = [b.label.lower() for b in test.button]
    forbidden = ("apply", "override", "dismiss", "accept", "resolve", "edit")
    assert not [label for label in labels if any(w in label for w in forbidden)], labels


def test_pressing_nothing_fetches_nothing(app, monkeypatch):
    """Rendering the panel must not download anything — the button is the consent.

    Guarded by making the network raise: `describe_corpus` is allowed, a request is not.
    """

    def refuse(*args, **kwargs):  # pragma: no cover - never called if the panel behaves
        raise AssertionError("the demo panel fetched without being asked")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    client = FakeClient(health=EMPTY_HEALTH)
    _no_exception(app(client=client))
    assert not [name for name, _ in client.calls if name == "create_batch"]


# -------------------------------------------------------------- ingest chrome (slice 8)


def test_the_uploader_is_absent_from_every_demo_state(app):
    for health in (EMPTY_HEALTH, HEALTH, SYNTHETIC_HEALTH):
        test = _no_exception(app(client=FakeClient(health=health)))
        assert not test.file_uploader
        assert not test.sidebar.file_uploader
        labels = [b.label for b in test.button]
        assert "Confirm upload" not in labels
        assert "Upload files" not in labels


def test_the_conversion_mark_keys_off_demo_plus_csv_not_any_csv():
    """Both sides of the filter: Parquet demo is unmarked, injected CSV is unmarked."""
    from loupe.ui.demo import is_demo_csv_conversion

    assert is_demo_csv_conversion(
        {"filename": "SR3G26.csv", "file_format": "csv", "origin": "demo"}
    )
    assert is_demo_csv_conversion(
        {"filename": "SR3G26.csv", "file_format": None, "origin": "demo"}
    ), "suffix still counts when file_format is absent"
    assert not is_demo_csv_conversion(
        {"filename": "ESZ25.parquet", "file_format": "parquet", "origin": "demo"}
    )
    assert not is_demo_csv_conversion(
        {"filename": "SR3G26.injected.csv", "file_format": "csv", "origin": "injected"}
    )
    assert not is_demo_csv_conversion(
        {"filename": "user.csv", "file_format": "csv", "origin": "upload"}
    )


def test_a_loaded_store_lists_ingested_files_and_marks_demo_csv(app):
    """After a stubbed load the list is present; converted rows are distinct from Parquet."""
    client = FakeClient()
    test = _no_exception(app(client=client))
    assert any(name == "batches" for name, _ in client.calls), (
        "the list is GET /v1/ingest/batches, not a directory walk"
    )

    markdown = [m.value for m in test.markdown]
    parquet = [m for m in markdown if "ESZ25.parquet" in m]
    converted = [m for m in markdown if "SR3G26.csv" in m and "injected" not in m]
    assert parquet, "the Parquet row is listed"
    assert converted, "the converted CSV row is listed"
    assert any("Converted from Parquet" in m for m in converted)
    assert not any("Converted from Parquet" in m for m in parquet)

    labels = [e.label for e in test.expander]
    assert any("ingested files" in label.lower() for label in labels)


def test_injected_csv_does_not_get_the_conversion_mark(app):
    """The synthetic/injected mark is still not this mark."""
    client = FakeClient(health=SYNTHETIC_HEALTH, batches=SYNTHETIC_BATCHES)
    test = _no_exception(app(client=client))

    markdown = [m.value for m in test.markdown]
    injected = [m for m in markdown if "SR3G26.injected.csv" in m]
    demo_csv = [m for m in markdown if "SR3G26.csv" in m and "injected" not in m]
    assert injected, "the planted file is still inventory"
    assert not any("Converted from Parquet" in m for m in injected)
    assert any("Converted from Parquet" in m for m in demo_csv)

    banner = " ".join(w.value for w in test.warning)
    assert "planted defects" in banner
    assert "⚠️" in banner or "synthetic" in banner.lower()


def test_an_empty_store_does_not_list_ingested_files(app):
    client = FakeClient(health=EMPTY_HEALTH)
    test = _no_exception(app(client=client))
    assert not any(name == "batches" for name, _ in client.calls)
    markdown = " ".join(m.value for m in test.markdown)
    assert "ESZ25.parquet" not in markdown
    assert not any("ingested files" in e.label.lower() for e in test.expander)
    said = _text(test).lower()
    assert "upload any csv" not in said
    assert "from the sidebar instead" not in said


def test_ingested_files_group_by_contract_coverage_when_grains_mix(app):
    """A dual-grain contract lists both files under Daily + minute, not by file frequency."""
    client = FakeClient(contracts=MIXED_COVERAGE_CONTRACTS, batches=MIXED_COVERAGE_BATCHES)
    test = _no_exception(app(client=client))
    markdown = " ".join(m.value for m in test.markdown)
    assert "Daily + minute" in markdown
    assert "Daily-only" in markdown
    assert "Minute-only" in markdown
    assert "ESZ25.parquet" in markdown
    assert "ESZ25.csv" in markdown
    assert "ZCZ25.parquet" in markdown
    assert "SR3G26.csv" in markdown


def test_planted_rows_group_under_strip_families_with_off_strip(app, tmp_path):
    """One planted file, many labelled defects. TIM.* is other/off-strip, not dropped."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(PLANTED_MANIFEST))
    client = FakeClient(health=SYNTHETIC_HEALTH)
    test = _no_exception(app(client=client, injected_manifest=str(path)))
    markdown = [m.value for m in test.markdown]
    assert any("**Gaps**" in m for m in markdown)
    assert any("**Duplicates**" in m for m in markdown)
    assert any("**Invalid values**" in m for m in markdown)
    assert any("Other (off the strip)" in m for m in markdown)
    captions = " ".join(c.value for c in test.caption)
    assert "SR3G26.injected.csv" in captions
    tables = [d.value for d in test.dataframe]
    rules = []
    for table in tables:
        if "Rule" in list(table.columns):
            rules.extend(str(v) for v in table["Rule"])
    assert "CMP.MISSING_TIMESTAMP" in rules
    assert "UNQ.EXACT_DUPLICATE" in rules
    assert "VAL.NEGATIVE_VOLUME" in rules
    assert "TIM.OUT_OF_ORDER" in rules


def test_sidebar_synthetic_lists_planted_files_by_family_not_findings_below(
    app, tmp_path
):
    """Sidebar warning drops 'findings below' and nests the planted file under families."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(PLANTED_MANIFEST))
    client = FakeClient(health=SYNTHETIC_HEALTH)
    test = _no_exception(app(client=client, injected_manifest=str(path)))
    warnings = " ".join(w.value for w in test.warning)
    assert "findings below" not in warnings.lower()
    assert "synthetic records" in warnings.lower()
    captions = " ".join(c.value for c in test.caption)
    assert "Planted in:" in captions
    markdown = " ".join(m.value for m in test.markdown)
    assert "**Gaps**" in markdown
    assert "SR3G26.injected.csv" in captions


def test_group_batches_by_coverage_puts_dual_grain_files_together():
    from loupe.ui.demo import (
        COVERAGE_BOTH,
        COVERAGE_DAILY,
        COVERAGE_MINUTE,
        group_batches_by_coverage,
    )

    groups = dict(
        group_batches_by_coverage(
            MIXED_COVERAGE_BATCHES["data"], MIXED_COVERAGE_CONTRACTS["data"]
        )
    )
    both = [batch["filename"] for batch in groups[COVERAGE_BOTH]]
    assert both == ["ESZ25.parquet", "ESZ25.csv"]
    assert [batch["filename"] for batch in groups[COVERAGE_DAILY]] == ["ZCZ25.parquet"]
    assert [batch["filename"] for batch in groups[COVERAGE_MINUTE]] == ["SR3G26.csv"]


def test_group_planted_by_family_keeps_off_strip_and_skips_patterns():
    from loupe.ui.demo import group_planted_by_family

    groups = dict(group_planted_by_family(PLANTED_MANIFEST["defects"]))
    assert set(groups) == {"Gaps", "Duplicates", "Invalid values", "Other (off the strip)"}
    assert groups["Other (off the strip)"][0]["rule_id"] == "TIM.OUT_OF_ORDER"
    assert "Recurring patterns" not in groups

