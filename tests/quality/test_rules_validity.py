"""`VAL.*` — is each value individually possible?"""

from __future__ import annotations

import pytest
from helpers import findings, set_param, source_rows


def test_non_positive_price_names_the_field(qcon, run_fixture):
    _, result = run_fixture("val_non_positive_price.csv")
    rows = findings(qcon, result.run_id, "VAL.NON_POSITIVE_PRICE")

    assert len(rows) == 1
    assert rows[0]["details"] == {"field": "low", "value": 0.0}
    assert source_rows(qcon, [rows[0]["record_id"]]) == [2]
    assert rows[0]["severity"] == "error"


def test_negative_volume_fires_on_the_planted_row(qcon, run_fixture):
    _, result = run_fixture("val_negative_volume.csv")
    rows = findings(qcon, result.run_id, "VAL.NEGATIVE_VOLUME")

    assert len(rows) == 1
    assert rows[0]["details"]["value"] == -5
    assert source_rows(qcon, [rows[0]["record_id"]]) == [2]


def test_non_integer_volume_reads_the_preserved_source_label(qcon, run_fixture):
    """Volume is a BIGINT, so the fraction is gone by the time a rule could see it.

    DuckDB rounds `'10.5'` to `11` rather than refusing it, and `'10.5'` is not
    `STR.NON_NUMERIC_VOLUME` either — it is a number. Ingest keeps the verbatim label in
    `volume_source` only when it does not parse as an integer, and this is the rule that
    reads it (`specs/data-model.md` §3.1).
    """
    _, result = run_fixture("val_non_integer_volume.csv")
    rows = findings(qcon, result.run_id, "VAL.NON_INTEGER_VOLUME")

    assert len(rows) == 1
    assert rows[0]["details"]["source_value"] == "10.5"
    assert rows[0]["details"]["loaded_value"] == 11
    assert rows[0]["severity"] == "warning"


def test_a_whole_volume_leaves_no_source_label_behind(qcon, run_fixture):
    """`volume_source` is null for every clean row, so the column costs nothing at scale."""
    run_fixture("val_non_integer_volume.csv")
    assert qcon.execute(
        "SELECT count(*) FROM stage.market_record WHERE volume_source IS NOT NULL"
    ).fetchone() == (1,)


def test_off_tick_price_uses_the_root_frequency_field_tick(qcon, run_fixture):
    _, result = run_fixture("val_off_tick_price.csv")
    rows = findings(qcon, result.run_id, "VAL.OFF_TICK_PRICE")

    assert len(rows) == 1
    assert rows[0]["details"]["field"] == "close"
    assert rows[0]["details"]["tick_size"] == pytest.approx(0.25)
    assert rows[0]["details"]["value"] == pytest.approx(6600.30)


def test_off_tick_price_does_not_fire_on_an_exempt_field(qcon, run_fixture):
    """A settlement-bearing field is exempted, not given an invented lattice.

    This is the corpus's live example: VX daily `close` is off-tick on 805 of 959 rows and on
    0 of 373,886 VX minute rows, because that column is a settlement carried to four decimals.
    """
    qcon.execute(
        "UPDATE ref.tick SET exempt = TRUE, tick_size = NULL "
        "WHERE root = 'ES' AND frequency = 'minute' AND field = 'close'"
    )
    _, result = run_fixture("val_off_tick_price.csv")
    assert findings(qcon, result.run_id, "VAL.OFF_TICK_PRICE") == []


def test_an_exactly_representable_tick_does_not_produce_false_positives(qcon, run_fixture):
    """0.25 and 1/64 are dyadic and exact in IEEE 754; the epsilon is for 0.01 and 0.0025."""
    _, result = run_fixture("cmp_partial_session.csv")
    assert findings(qcon, result.run_id, "VAL.OFF_TICK_PRICE") == []


def test_zero_volume_with_range_fires_at_intraday(qcon, run_fixture):
    _, result = run_fixture("val_zero_volume_with_range.csv")
    rows = findings(qcon, result.run_id, "VAL.ZERO_VOLUME_WITH_RANGE")

    assert len(rows) == 1
    assert rows[0]["details"]["basis"] == "intraday"
    assert rows[0]["severity"] == "warning"


def test_zero_volume_with_range_drops_to_info_at_daily(qcon, fixture_path):
    """A daily summary is published for a listed contract whether or not it traded.

    Asked of the bar interval rather than the frequency name, so a five-minute file is judged
    the way a one-minute file is.
    """
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("rol_no_successor.csv"))
    qcon.execute(
        "UPDATE stage.market_record SET volume = 0 WHERE source_row = 1 AND batch_id = ?",
        [batch.batch_id],
    )
    result = run_rules(qcon, batch_id=batch.batch_id)
    rows = findings(qcon, result.run_id, "VAL.ZERO_VOLUME_WITH_RANGE")

    assert len(rows) == 1
    assert rows[0]["severity"] == "info"
    assert rows[0]["details"]["basis"] == "daily"


def test_zero_volume_with_range_can_be_disabled_at_daily_from_the_row(qcon, fixture_path):
    from loupe.data import load_file
    from loupe.quality import run_rules

    set_param(qcon, "VAL.ZERO_VOLUME_WITH_RANGE", "daily_severity", None)
    batch = load_file(qcon, fixture_path("rol_no_successor.csv"))
    qcon.execute(
        "UPDATE stage.market_record SET volume = 0 WHERE source_row = 1 AND batch_id = ?",
        [batch.batch_id],
    )
    result = run_rules(qcon, batch_id=batch.batch_id)

    assert findings(qcon, result.run_id, "VAL.ZERO_VOLUME_WITH_RANGE") == []


def test_price_magnitude_catches_a_decimal_shift(qcon, run_fixture):
    _, result = run_fixture("val_price_magnitude.csv")
    rows = findings(qcon, result.run_id, "VAL.PRICE_MAGNITUDE")

    assert len(rows) == 1
    assert rows[0]["details"]["field"] == "high"
    assert rows[0]["details"]["value"] == pytest.approx(66020.0)
    assert rows[0]["details"]["plausible_range"] == [500.0, 30000.0]


def test_a_root_with_no_band_is_not_evaluated(qcon, run_fixture):
    """An invented band is worse than no test."""
    set_param(qcon, "VAL.PRICE_MAGNITUDE", "bands", {})
    _, result = run_fixture("val_price_magnitude.csv")
    assert findings(qcon, result.run_id, "VAL.PRICE_MAGNITUDE") == []


def test_extreme_volume_is_informational_and_per_granularity(qcon, run_fixture):
    _, result = run_fixture("val_extreme_volume.csv")
    rows = findings(qcon, result.run_id, "VAL.EXTREME_VOLUME")

    assert len(rows) == 1
    assert rows[0]["severity"] == "info"
    assert rows[0]["details"]["max_plausible"] == 100_000
    assert rows[0]["details"]["value"] == 500_000
