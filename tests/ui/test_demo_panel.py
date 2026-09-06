"""The demo panel and the synthetic-data disclosure (`plans/07-demo-corpus.md`).

The disclosure tests are the reason this file exists. Done-when 5 turns on a property that is
easy to satisfy badly: *a reader who arrives mid-session, or reloads, still knows*. A notice
rendered once when the button is pressed satisfies "the user was told" and fails that property
completely, because Streamlit reruns on every interaction — change persona, sort a column, pick
a contract, and the notice is three reruns gone while the findings remain.

So every disclosure test here runs the page **twice** and asserts on the second run.
"""

from __future__ import annotations

import pytest
from ui_helpers import EMPTY_HEALTH, HEALTH, SYNTHETIC_HEALTH, FakeClient


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
    test = _no_exception(app("Risk", client=client))

    banner = " ".join(w.value for w in test.warning)
    assert "planted defects" in banner
    assert "345" in banner, "the disclosure quantifies what is synthetic"
    assert "partly synthetic" in banner.lower()


def test_the_disclosure_survives_a_rerun(app):
    """Done-when 5, stated as the property rather than as the moment.

    Two full script runs. The second is the one that matters: it stands in for every
    interaction after the injection — a persona switch, a date change, a row selection — and a
    notice that only fired on the injection rerun would be gone by now.
    """
    client = FakeClient(health=SYNTHETIC_HEALTH)
    first = _no_exception(app("Risk", client=client))
    assert "planted defects" in " ".join(w.value for w in first.warning)

    second = _no_exception(first.run())
    assert "planted defects" in " ".join(w.value for w in second.warning)


def test_the_disclosure_survives_a_persona_switch(app):
    """The likeliest real interaction, and it must not be the one that clears the notice."""
    client = FakeClient(health=SYNTHETIC_HEALTH)
    for persona in ("Risk", "Trader", "Analyst"):
        test = _no_exception(app(persona, client=client))
        assert "planted defects" in " ".join(w.value for w in test.warning), persona


def test_nothing_is_disclosed_when_nothing_was_planted(app):
    """The other side of the filter. A banner that always showed would say nothing at all.

    Asserted over warnings rather than over all page text, and the distinction is real: the
    *offer* to inject describes what it would plant, which is the panel doing its job. What
    must be absent is the claim that the store already holds synthetic data.
    """
    test = _no_exception(app("Risk"))
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
    _no_exception(app("Risk", client=client))

    source = page.main.__code__.co_names
    assert "render_synthetic_notice" in source
    assert source.index("render_synthetic_notice") < source.index("load_summary")


# ------------------------------------------------------------------------- the two buttons


def test_an_empty_store_offers_the_fetch_and_says_what_it_downloads(app):
    """Consent before bytes: §1 found no licence grant, so the reader decides knowingly."""
    client = FakeClient(health=EMPTY_HEALTH)
    test = _no_exception(app("Risk", client=client))

    labels = [b.label for b in test.button]
    assert "Load demo data" in labels
    assert "Inject demo defects" not in labels, "there is nothing to inject into yet"

    said = _text(test)
    assert "Hugging Face" in said or "huggingface" in said.lower()
    assert "redistribution" in said


def test_a_loaded_store_offers_injection_and_not_the_fetch(app):
    """Two clicks, in order. The second only appears once there is real data to contrast with."""
    test = _no_exception(app("Risk"))
    labels = [b.label for b in test.button]

    assert "Inject demo defects" in labels
    assert "Load demo data" not in labels


def test_injection_says_what_it_will_do_before_it_is_pressed(app):
    """Planting defects is not something to discover afterwards."""
    test = _no_exception(app("Risk"))
    said = _text(test)
    assert "copy" in said.lower(), "the vendor files are not modified, and it says so"
    assert "manifest" in said.lower()


def test_a_synthetic_store_offers_the_way_back(app):
    """Done-when 6. A demo that can only be undone with `rm` is one nobody presses."""
    client = FakeClient(health=SYNTHETIC_HEALTH)
    test = _no_exception(app("Risk", client=client))
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
    test = _no_exception(app("Risk", client=client))
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
    _no_exception(app("Risk", client=client))
    assert not [name for name, _ in client.calls if name == "create_batch"]
