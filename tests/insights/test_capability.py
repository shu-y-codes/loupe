"""The fourth state: a grain the corpus cannot answer at (`plans/04-api.md` done-when 7).

`PublishedSeries` already told a caller apart three ways — published, withheld, empty. This
adds the one the API needs to render a 422: *no rows can come back, because this contract
holds daily records only*. The tests below exist to keep those four apart, since collapsing
any two of them is exactly what the type was introduced to prevent.
"""

from __future__ import annotations

from loupe.insights import (
    capability_gap,
    frequencies_held,
    published_bars,
    published_vwap,
)
from loupe.quality import run_rules

DAILY_FIXTURE = "con_derived_bar_invalid_vendor.csv"
MINUTE_FIXTURE = "insights_vwap_window.csv"
MISALIGNED_FIXTURE = "tim_timezone_misaligned.csv"


def test_frequencies_held_reports_what_the_store_actually_has(icon, load_and_build):
    load_and_build(DAILY_FIXTURE)
    assert frequencies_held(icon, contract_id="CLZ25") == ("daily",)
    assert frequencies_held(icon, contract_id="NOSUCH26") == ()


def test_capability_gap_fires_only_when_the_grain_is_missing(icon, load_and_build):
    load_and_build(DAILY_FIXTURE)

    gap = capability_gap(icon, requested_frequency="minute", contract_id="CLZ25")
    assert gap is not None
    assert gap.frequencies_available == ("daily",)
    assert gap.substitute_offered is False

    assert capability_gap(icon, requested_frequency="daily", contract_id="CLZ25") is None


def test_a_contract_holding_nothing_is_empty_not_a_capability_gap(icon, load_and_build):
    """"No data at all" is an empty result. The refusal means "data, but not that grain" —
    the only case where telling the user to upload another file is useful advice."""
    load_and_build(DAILY_FIXTURE)
    assert capability_gap(icon, requested_frequency="minute", contract_id="NOSUCH26") is None


def test_published_vwap_refuses_on_a_daily_only_contract(icon, load_and_build):
    load_and_build(DAILY_FIXTURE)
    series = published_vwap(icon, contract_id="CLZ25")

    assert series.frequency_unavailable
    assert series.rows == ()
    assert not series.blocked
    assert not series.unavailable, "refused is not the same as empty"
    assert series.unsupported.requested_frequency == "minute"


def test_the_four_states_are_mutually_exclusive(icon, load_and_build):
    """Published, withheld, refused, empty — one series can only be one of them."""
    load_and_build(DAILY_FIXTURE)
    load_and_build(MINUTE_FIXTURE)

    published = published_vwap(icon, contract_id="ESZ25")
    assert published.rows and not published.blocked
    assert not published.frequency_unavailable and not published.unavailable

    refused = published_vwap(icon, contract_id="CLZ25")
    assert refused.frequency_unavailable
    assert not refused.unavailable and not refused.blocked

    empty = published_vwap(icon, contract_id="NOSUCH26")
    assert empty.unavailable
    assert not empty.frequency_unavailable and not empty.blocked


def test_a_blocked_series_is_not_reported_as_refused(icon, load_and_build):
    """A `critical` finding withholds a series that exists; the grain was never the problem."""
    load_and_build(MISALIGNED_FIXTURE)
    run_rules(icon)

    series = published_vwap(icon, contract_id="ESZ25")
    assert series.blocked
    assert not series.frequency_unavailable
    assert not series.unavailable


def test_bars_are_unaffected_by_the_new_state(icon, load_and_build):
    """Daily-only is a normal answer for bars: the supplied bars are what was uploaded."""
    load_and_build(DAILY_FIXTURE)
    series = published_bars(icon, contract_id="CLZ25", source="vendor")
    assert series.rows
    assert not series.frequency_unavailable
