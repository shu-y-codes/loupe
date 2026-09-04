"""Ingest: idempotency, the reject line, trade-date assignment, and frequency."""

from __future__ import annotations

import json
from datetime import date

import pytest

from loupe.data import load_file, preview_file
from loupe.data.errors import DuplicateFileError


def _records(con):
    return con.execute(
        "SELECT source_row, contract_id, frequency, ts_exchange, trade_date, open, close, volume "
        "FROM stage.market_record ORDER BY source_row"
    ).fetchall()


def test_load_writes_records_and_a_finished_batch(con, fixture_path):
    result = load_file(con, fixture_path("null_fields.csv"))
    assert result.status == "succeeded"
    assert (result.rows_read, result.rows_accepted, result.rows_rejected) == (4, 4, 0)

    status, started, finished = con.execute(
        "SELECT status, started_at, finished_at FROM stage.ingest_batch"
    ).fetchone()
    assert status == "succeeded"
    assert finished is not None and finished >= started


def test_nulls_are_loaded_not_rejected(con, fixture_path):
    """A null price is a quality finding, not a load failure.

    If the loader rejected them, the user could never see them and "detect missing values"
    would be impossible to demonstrate.
    """
    load_file(con, fixture_path("null_fields.csv"))
    rows = _records(con)
    assert len(rows) == 4
    assert rows[1][6] is None  # a null close
    assert rows[2][7] is None  # a null volume
    assert con.execute("SELECT count(*) FROM stage.record_reject").fetchone()[0] == 0


def test_unparseable_rows_land_in_rejects_with_their_reason(con, fixture_path):
    result = load_file(con, fixture_path("unparseable.csv"))
    assert result.status == "partial"
    assert result.rows_read == 7
    assert result.rows_accepted == 2
    assert result.rows_rejected == 5
    assert result.reject_reasons == {
        "STR.BAD_TIMESTAMP": 1,
        "STR.NON_NUMERIC_PRICE": 1,
        "STR.NON_NUMERIC_VOLUME": 1,
        "STR.UNPARSEABLE_ROW": 2,
    }


def test_a_partial_file_is_not_thrown_away(con, fixture_path):
    """Rejects are row-level. Three bad rows in a file do not lose the other four."""
    load_file(con, fixture_path("unparseable.csv"))
    assert con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0] == 2


def test_source_row_survives_a_skipped_line(con, fixture_path):
    """The traceability spine: a finding must be able to name the row in the source file.

    The CSV reader skips a structurally broken line, so scan order and file order diverge
    from that point on unless the mapping is corrected.
    """
    load_file(con, fixture_path("unparseable.csv"))
    accepted = [row[0] for row in _records(con)]
    rejected = [
        row[0]
        for row in con.execute(
            "SELECT source_row FROM stage.record_reject ORDER BY source_row"
        ).fetchall()
    ]
    assert accepted == [1, 7]
    assert rejected == [2, 3, 4, 5, 6]


def test_rejects_keep_the_offending_row(con, fixture_path):
    load_file(con, fixture_path("unparseable.csv"))
    payload = con.execute(
        "SELECT raw_payload FROM stage.record_reject WHERE reason_code = 'STR.UNPARSEABLE_ROW' "
        "AND source_row = 6"
    ).fetchone()[0]
    assert payload == "this row has too few fields"


def test_reloading_the_same_file_is_refused(con, fixture_path):
    """Idempotent on file_hash: the same file twice would double every volume figure."""
    first = load_file(con, fixture_path("null_fields.csv"))
    with pytest.raises(DuplicateFileError) as excinfo:
        load_file(con, fixture_path("null_fields.csv"))
    assert excinfo.value.file_hash == first.file_hash
    assert excinfo.value.existing_batch_id == first.batch_id
    assert con.execute("SELECT count(*) FROM stage.ingest_batch").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0] == 4


def test_a_copy_under_another_name_is_still_a_duplicate(con, fixture_path, tmp_path):
    """The key is the bytes, not the filename."""
    original = fixture_path("null_fields.csv")
    copy = tmp_path / "renamed.csv"
    copy.write_bytes(original.read_bytes())
    load_file(con, original)
    with pytest.raises(DuplicateFileError):
        load_file(con, copy)


def test_preview_flags_a_duplicate_before_the_load_is_attempted(con, fixture_path):
    load_file(con, fixture_path("null_fields.csv"))
    preview = preview_file(con, fixture_path("null_fields.csv"))
    assert preview.is_duplicate
    assert preview.already_ingested is not None


def test_evening_bars_get_the_next_days_trade_date(con, fixture_path):
    load_file(con, fixture_path("session_roll_boundary.csv"))
    by_stamp = {row[3].strftime("%Y-%m-%d %H:%M"): row[4] for row in _records(con)}
    assert by_stamp["2025-09-15 15:58"] == date(2025, 9, 15)
    assert by_stamp["2025-09-15 15:59"] == date(2025, 9, 15)
    assert by_stamp["2025-09-15 16:59"] == date(2025, 9, 15)
    assert by_stamp["2025-09-15 17:00"] == date(2025, 9, 16)
    assert by_stamp["2025-09-15 17:01"] == date(2025, 9, 16)
    assert by_stamp["2025-09-16 09:00"] == date(2025, 9, 16)


def test_sunday_evening_is_mondays_session_and_not_a_weekend_record(con, fixture_path):
    load_file(con, fixture_path("weekend_sunday_evening.csv"))
    dates = {row[4] for row in _records(con)}
    assert dates == {date(2025, 9, 15)}
    weekend = con.execute(
        "SELECT count(*) FROM stage.market_record WHERE dayofweek(trade_date) IN (0, 6)"
    ).fetchone()[0]
    assert weekend == 0


def test_grain_contract_rolls_at_its_own_open(con, fixture_path):
    """ZC opens at 19:00. Applying a 17:00 boundary would misdate its evening block."""
    load_file(con, fixture_path("zc_two_window.csv"))
    by_stamp = {row[3].strftime("%Y-%m-%d %H:%M"): row[4] for row in _records(con)}
    assert by_stamp["2026-01-05 19:00"] == date(2026, 1, 6)
    assert by_stamp["2026-01-06 07:44"] == date(2026, 1, 6)
    assert by_stamp["2026-01-06 13:19"] == date(2026, 1, 6)


def test_ts_utc_is_derived_and_ts_source_is_kept_verbatim(con, fixture_path):
    load_file(con, fixture_path("weekend_sunday_evening.csv"))
    ts_source, ts_exchange, ts_utc = con.execute(
        "SELECT ts_source, ts_exchange, ts_utc FROM stage.market_record ORDER BY source_row LIMIT 1"
    ).fetchone()
    assert ts_source == "2025-09-14 17:00:00"
    assert ts_exchange.hour == 17
    # 17:00 CDT is 22:00 UTC. ts_utc is a conclusion about the data, so it must be derived
    # rather than read: there is no UTC instant anywhere in the source.
    assert ts_utc.hour == 22


def test_ingestion_decisions_are_persisted_on_the_batch(con, fixture_path):
    result = load_file(con, fixture_path("session_roll_boundary.csv"))
    row = con.execute(
        "SELECT frequency, bar_interval, source_timezone, ts_convention, session_boundary, "
        "column_mapping, inferred_interval FROM stage.ingest_batch WHERE batch_id = ?",
        [result.batch_id],
    ).fetchone()
    frequency, interval, tz, convention, boundary, mapping, inferred = row
    assert frequency == "minute"
    assert interval == "1 minute"
    assert tz == "America/Chicago"
    assert convention == "interval_start"
    assert "17:00" in boundary
    assert inferred == "1 minute"
    assert json.loads(mapping)["contract"] == "contract_id"


def test_three_character_root_loads_and_registers(con, fixture_path):
    load_file(con, fixture_path("sr3_symbol.csv"))
    root, month_code, confidence = con.execute(
        "SELECT root, month_code, parse_confidence FROM ref.contract WHERE contract_id = 'SR3M26'"
    ).fetchone()
    assert (root, month_code) == ("SR3", "M")
    assert confidence == 1.0


def test_loading_registers_contracts_and_extends_the_calendar(con, fixture_path):
    load_file(con, fixture_path("session_roll_boundary.csv"))
    assert con.execute(
        "SELECT count(*) FROM ref.contract WHERE contract_id = 'ESZ25'"
    ).fetchone()[0] == 1
    covered = con.execute(
        "SELECT count(*) FROM ref.session_calendar WHERE root = 'ES' "
        "AND trade_date BETWEEN DATE '2025-09-15' AND DATE '2025-09-16'"
    ).fetchone()[0]
    assert covered == 2


def test_an_empty_file_loads_to_nothing_rather_than_failing(con, tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("contract,timestamp,open,high,low,close,volume\n")
    result = load_file(con, path)
    assert result.rows_read == 0
    assert result.status == "succeeded"


@pytest.mark.samples
def test_both_granularities_of_one_contract_do_not_collide(con, samples_dir):
    """Without the discriminator this corpus reports 79 good rows as duplicated.

    The default cleaning policy for a key conflict with differing values is to exclude all
    conflicting rows, so the modelling error would delete real market data.
    """
    load_file(con, samples_dir / "data/daily/CME/ES/ESZ25.parquet")
    load_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")

    without_frequency = con.execute(
        "SELECT count(*) FROM (SELECT contract_id, ts_utc FROM stage.market_record "
        "GROUP BY 1, 2 HAVING count(*) > 1)"
    ).fetchone()[0]
    with_frequency = con.execute(
        "SELECT count(*) FROM (SELECT contract_id, frequency, ts_utc FROM stage.market_record "
        "GROUP BY 1, 2, 3 HAVING count(*) > 1)"
    ).fetchone()[0]

    assert without_frequency == 79
    assert with_frequency == 0


@pytest.mark.samples
def test_real_files_load_clean(con, samples_dir):
    daily = load_file(con, samples_dir / "data/daily/CME/ES/ESZ25.parquet")
    minute = load_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")
    assert (daily.rows_accepted, daily.rows_rejected) == (1_145, 0)
    assert (minute.rows_accepted, minute.rows_rejected) == (114_477, 0)
    assert daily.status == minute.status == "succeeded"


@pytest.mark.samples
def test_derived_session_date_produces_no_weekend_rows(con, samples_dir):
    """The vendor's own trading_date column would put 3.40% of the corpus on a Sunday."""
    load_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")
    weekend = con.execute(
        "SELECT count(*) FROM stage.market_record WHERE dayofweek(trade_date) IN (0, 6)"
    ).fetchone()[0]
    assert weekend == 0


@pytest.mark.samples
def test_capability_matrix_opens_up_once_both_granularities_are_present(con, samples_dir):
    minute = samples_dir / "data/minute/CME/ES/ESZ25.parquet"
    daily = samples_dir / "data/daily/CME/ES/ESZ25.parquet"
    assert not preview_file(con, minute).capabilities["reconciliation"].available
    load_file(con, daily)
    assert preview_file(con, minute).capabilities["reconciliation"].available


@pytest.mark.samples
def test_open_interest_is_daily_only_and_null_is_not_zero(con, samples_dir):
    """Null means "not supplied at this granularity"; zero means "supplied as zero"."""
    load_file(con, samples_dir / "data/daily/CME/ES/ESZ25.parquet")
    load_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")
    minute_non_null, daily_non_null, daily_zero = con.execute(
        """
        SELECT
          count(*) FILTER (WHERE frequency = 'minute' AND open_interest IS NOT NULL),
          count(*) FILTER (WHERE frequency = 'daily'  AND open_interest IS NOT NULL),
          count(*) FILTER (WHERE frequency = 'daily'  AND open_interest = 0)
        FROM stage.market_record
        """
    ).fetchone()
    assert minute_non_null == 0
    assert daily_non_null == 1_145
    assert daily_zero > 0
