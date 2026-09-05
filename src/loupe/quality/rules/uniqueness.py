"""Uniqueness — `UNQ.*`. Is anything counted twice?

Both rules are evaluated **within a frequency, never across** (`specs/data-model.md` §4.1):
the same contract legitimately has a daily row and 1,380 minute rows for one session, and a
key that ignored frequency would call that a conflict. Measured on the real pair: 79
collisions on `(contract_id, ts_utc)`, zero with frequency in the key.

`UNQ.DUPLICATE_FILE` has no runner. Ingest refuses a repeated `file_hash` outright
(`DuplicateFileError`), so the batch never lands and there is nothing to write a finding
about — it is in the catalogue because the spec requires the row, and marked
`enforced_at = 'ingest'` so the parity test knows why no runner exists.
"""

from __future__ import annotations

from ..registry import RECORDS, Finding, RuleContext, rule


def _value_tuple(alias: str) -> str:
    """The OHLCV tuple a key conflict compares. Aliased, so it can appear in a subquery."""
    return ", ".join(
        f"{alias}.{column}"
        for column in ("open", "high", "low", "close", "volume", "open_interest")
    )


@rule("UNQ.EXACT_DUPLICATE")
def exact_duplicate(ctx: RuleContext) -> list[Finding]:
    """Rows identical across every field. The lowest `source_row` is kept (spec §14).

    One finding per *redundant* record rather than one per group, because cleaning acts on a
    record id: the finding is what tells `dedupe_drop` which row to drop and which one it is
    keeping.
    """
    rows = ctx.con.execute(
        f"""
        WITH grouped AS (
          SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
                 r.source_row,
                 count(*) OVER w AS copies,
                 first_value(r.record_id) OVER (
                   PARTITION BY r.contract_id, r.frequency, r.ts_utc, r.open, r.high,
                                r.low, r.close, r.volume, r.open_interest
                   ORDER BY r.source_row, r.record_id
                 ) AS keep_record_id,
                 first_value(r.source_row) OVER (
                   PARTITION BY r.contract_id, r.frequency, r.ts_utc, r.open, r.high,
                                r.low, r.close, r.volume, r.open_interest
                   ORDER BY r.source_row, r.record_id
                 ) AS keep_source_row
          FROM {RECORDS} r
          WHERE {ctx.frequency_filter()}
          WINDOW w AS (
            PARTITION BY r.contract_id, r.frequency, r.ts_utc, r.open, r.high, r.low,
                         r.close, r.volume, r.open_interest
          )
        )
        SELECT record_id, contract_id, frequency, trade_date, ts_utc, copies,
               keep_record_id, keep_source_row, source_row
        FROM grouped
        WHERE copies > 1 AND record_id <> keep_record_id
        ORDER BY record_id
        """
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            ts_start_utc=ts_utc,
            ts_end_utc=ts_utc,
            record_id=record_id,
            details={
                "copies": int(copies),
                "keeps_record_id": int(keep_record_id),
                "keeps_source_row": int(keep_source_row),
                "source_row": int(source_row),
            },
        )
        for (
            record_id,
            contract_id,
            frequency,
            trade_date,
            ts_utc,
            copies,
            keep_record_id,
            keep_source_row,
            source_row,
        ) in rows
    ]


@rule("UNQ.KEY_CONFLICT")
def key_conflict(ctx: RuleContext) -> list[Finding]:
    """Same key, differing values. **Every** row in the conflict is reported, and excluded.

    There is no principled winner inside one file: picking the first or the last would be a
    tie-break policy invented by the engine rather than stated by the source. Adopting one
    for a known-bad feed is a suggestion (spec §13), not a default.
    """
    rows = ctx.con.execute(
        f"""
        WITH conflicts AS (
          SELECT r.contract_id, r.frequency, r.ts_utc,
                 count(DISTINCT ({_value_tuple("r")})) AS variants
          FROM {RECORDS} r
          WHERE {ctx.frequency_filter()}
          GROUP BY 1, 2, 3
          HAVING count(DISTINCT ({_value_tuple("r")})) > 1
        )
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.source_row,
               c.variants
        FROM {RECORDS} r
        JOIN conflicts c
          ON c.contract_id = r.contract_id AND c.frequency = r.frequency
         AND c.ts_utc = r.ts_utc
        ORDER BY r.record_id
        """
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            ts_start_utc=ts_utc,
            ts_end_utc=ts_utc,
            record_id=record_id,
            details={"variants": int(variants), "source_row": int(source_row)},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, source_row, variants in rows
    ]
