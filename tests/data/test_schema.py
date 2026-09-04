"""The schema applies, is idempotent, and has the shape specs/data-model.md specifies."""

from __future__ import annotations

import pytest

from loupe.data import apply_schema, schema_is_applied
from loupe.data.schema import SCHEMAS


def test_apply_schema_creates_every_schema(bare_con):
    assert not schema_is_applied(bare_con)
    apply_schema(bare_con)
    assert schema_is_applied(bare_con)


def test_apply_schema_is_idempotent(bare_con):
    apply_schema(bare_con)
    apply_schema(bare_con)
    tables = bare_con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema IN "
        "('ref','stage','dq','mart')"
    ).fetchone()[0]
    assert tables > 0


@pytest.mark.parametrize(
    ("schema", "table"),
    [
        ("ref", "contract"),
        ("ref", "product"),
        ("ref", "tick"),
        ("ref", "session_calendar"),
        ("stage", "ingest_batch"),
        ("stage", "market_record"),
        ("stage", "record_reject"),
        ("dq", "dq_rule"),
        ("dq", "dq_run"),
        ("dq", "dq_finding"),
        ("dq", "cleaning_action"),
        ("dq", "market_record_clean"),
        ("mart", "bar_daily"),
        ("mart", "dq_metric_daily"),
    ],
)
def test_table_exists(con, schema, table):
    """Queryable is the assertion; some of these are seeded by the fixture."""
    assert con.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0] >= 0


def test_every_declared_schema_is_present(con):
    found = {
        row[0]
        for row in con.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()
    }
    assert set(SCHEMAS) <= found


def test_market_record_key_is_not_unique(con):
    """Duplicates must be loadable so that they can be detected, reported and scored.

    Enforcing uniqueness on (contract_id, frequency, ts_utc) would push duplicate detection
    into the loader's exception handler, where it cannot be reported or overridden.
    """
    insert = """
        INSERT INTO stage.market_record
          (batch_id, source_row, contract_id, frequency, ts_source, ts_exchange, ts_utc,
           trade_date, open, high, low, close, volume)
        VALUES (uuid(), ?, 'ESZ25', 'minute', '2025-09-15 09:00:00',
                TIMESTAMP '2025-09-15 09:00:00',
                TIMESTAMP '2025-09-15 09:00:00' AT TIME ZONE 'America/Chicago',
                DATE '2025-09-15', 1.0, 2.0, 0.5, 1.5, 10)
    """
    con.execute(insert, [1])
    con.execute(insert, [2])
    assert con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0] == 2


def test_clean_view_excludes_only_excluded_records(con):
    con.execute(
        """
        INSERT INTO stage.market_record
          (record_id, batch_id, source_row, contract_id, frequency, ts_source, ts_exchange,
           ts_utc, trade_date)
        VALUES (1, uuid(), 1, 'ESZ25', 'minute', 'x', TIMESTAMP '2025-09-15 09:00:00',
                TIMESTAMP '2025-09-15 09:00:00' AT TIME ZONE 'UTC', DATE '2025-09-15'),
               (2, uuid(), 2, 'ESZ25', 'minute', 'x', TIMESTAMP '2025-09-15 09:01:00',
                TIMESTAMP '2025-09-15 09:01:00' AT TIME ZONE 'UTC', DATE '2025-09-15')
        """
    )
    con.execute(
        "INSERT INTO dq.cleaning_action (run_id, record_id, action) VALUES (uuid(), 1, 'exclude')"
    )
    assert con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0] == 2
    remaining = con.execute("SELECT record_id FROM dq.market_record_clean").fetchall()
    assert remaining == [(2,)]


def test_clean_view_carries_frequency_and_open_interest(con):
    """SELECT r.* propagates the columns that keep the two granularities apart."""
    columns = {
        row[0]
        for row in con.execute("DESCRIBE dq.market_record_clean").fetchall()
    }
    assert {"frequency", "ts_source", "open_interest"} <= columns


def test_reconciliation_finding_must_name_its_own_side(con):
    """compare_frequency without frequency is not a well-formed pair."""
    import duckdb

    con.execute(
        "INSERT INTO dq.dq_finding (run_id, rule_id, severity, frequency, compare_frequency) "
        "VALUES (uuid(), 'REC.OHLC_DISAGREE', 'error', 'minute', 'daily')"
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO dq.dq_finding (run_id, rule_id, severity, compare_frequency) "
            "VALUES (uuid(), 'REC.OHLC_DISAGREE', 'error', 'daily')"
        )
