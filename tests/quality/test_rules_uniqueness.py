"""`UNQ.*` — is anything counted twice?"""

from __future__ import annotations

from helpers import findings, source_rows


def test_exact_duplicate_reports_the_redundant_row_and_names_the_keeper(qcon, run_fixture):
    """Keep the lowest `source_row`; the finding says which row that is (spec §14)."""
    _, result = run_fixture("unq_exact_duplicate.csv")
    rows = findings(qcon, result.run_id, "UNQ.EXACT_DUPLICATE")

    assert len(rows) == 1
    assert source_rows(qcon, [rows[0]["record_id"]]) == [3]
    assert rows[0]["details"]["keeps_source_row"] == 2
    assert rows[0]["details"]["copies"] == 2
    assert rows[0]["severity"] == "warning"


def test_key_conflict_reports_every_row_in_the_conflict(qcon, run_fixture):
    """There is no principled winner inside one file, so all of them are excluded."""
    _, result = run_fixture("unq_key_conflict.csv")
    rows = findings(qcon, result.run_id, "UNQ.KEY_CONFLICT")

    assert source_rows(qcon, [row["record_id"] for row in rows]) == [2, 3]
    assert {row["details"]["variants"] for row in rows} == {2}
    assert {row["severity"] for row in rows} == {"error"}


def test_an_exact_duplicate_is_not_a_key_conflict(qcon, run_fixture):
    """Identical rows agree about the value, so there is nothing to conflict over."""
    _, result = run_fixture("unq_exact_duplicate.csv")
    assert findings(qcon, result.run_id, "UNQ.KEY_CONFLICT") == []


def test_a_key_conflict_is_not_an_exact_duplicate(qcon, run_fixture):
    _, result = run_fixture("unq_key_conflict.csv")
    assert findings(qcon, result.run_id, "UNQ.EXACT_DUPLICATE") == []


def test_the_two_frequencies_of_one_contract_do_not_collide(qcon, fixture_path):
    """§4: evaluated within a frequency, never across.

    A contract legitimately has one daily row and 1,380 minute rows for the same session.
    Measured on the real pair, a key without frequency produces 79 collisions and a key with
    it produces none, so this is the property that keeps the whole family usable.
    """
    from loupe.data import load_file
    from loupe.quality import run_rules

    load_file(qcon, fixture_path("cmp_sparse_series.csv"))
    qcon.execute(
        """
        INSERT INTO stage.market_record
          (batch_id, source_row, contract_id, frequency, ts_source, ts_exchange, ts_utc,
           trade_date, open, high, low, close, volume)
        SELECT batch_id, source_row, contract_id, 'daily', ts_source, ts_exchange, ts_utc,
               trade_date, open, high, low, close, volume
        FROM stage.market_record
        """
    )
    result = run_rules(qcon)

    assert findings(qcon, result.run_id, "UNQ.KEY_CONFLICT") == []
    assert findings(qcon, result.run_id, "UNQ.EXACT_DUPLICATE") == []
