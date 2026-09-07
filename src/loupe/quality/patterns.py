"""Recurring patterns — where findings concentrate, corrected for exposure (spec §12).

A count is not a pattern. Half a contract's missing-slot findings falling in one hour is only
interesting if that hour does not also hold half its records, so every bucket is scored as a
**ratio**: the bucket's share of a rule's findings against the bucket's share of the records.
`lift` is that ratio, and the thresholds are on it rather than on the raw count.

Detection is deterministic and the narrative is a template. Nothing here calls a language
model, and only aggregates leave the process — locked decision 5.

**Six of §12's eight dimensions are computed, and the two absent ones are absent for a
reason.** Lift needs a denominator, and a denominator needs the buckets to partition the
records. Hour, day of week, trade date, contract, frequency and batch all do. `field` and
`rule` do not:

- Every record carries an `open`, a `high`, a `low` and a `close`, so "the share of records in
  the `close` bucket" is either 1.0 or an invented 1/4. There is no exposure to correct for.
- Grouping is per rule (§12's own `(rule_id, dimension, bucket)`), so a `rule` bucket inside a
  rule's own group is the group key: `share_of_findings` is 1.0 by construction and the lift
  is a statement about nothing.

Reporting either would mean printing a number whose denominator does not exist, which is the
same failure §11.7 refuses for the worst-field tile. What those two dimensions were meant to
catch is reachable through the ones that do partition: the corpus's off-tick settlements are a
`frequency` pattern on `VAL.OFF_TICK_PRICE`, which is why §12 calls `frequency` **required** —
"without it, a settlement-close pattern is attributed to a contract or field, and the
suggestion proposes the wrong fix".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

#: Report calibration, not rule calibration — patterns have no `dq.dq_rule` row, because a
#: pattern is a reading of findings rather than a check that produces them. The API exposes
#: `min_lift` and `min_support` as query parameters (`specs/api-contract.md` §7) so a caller
#: can widen or narrow the list without a re-seed.
DEFAULT_LIFT = 3.0
DEFAULT_MIN_SUPPORT = 20
#: Recurrence, so a single bad afternoon is not reported as a standing pattern. Not applied to
#: the `trade_date` dimension, where one day *is* the bucket and a one-off outage is the whole
#: point of looking.
DEFAULT_MIN_PERIODS = 3

#: The corpus is Chicago-stamped end to end (`specs/sample-corpus.md` §4.1) and every seeded
#: product carries that zone. Bound as a parameter rather than inlined so a deployment with a
#: second venue changes one expression rather than every bucket that mentions a clock.
_TIMEZONE = "America/Chicago"

#: `(name, finding expression, record expression)`. Both sides of every pair bucket the same
#: quantity the same way, which is what makes the two shares comparable at all.
#:
#: Hour of day is exchange-local, converted from UTC through the product's timezone on both
#: sides. `stage.market_record.ts_exchange` already holds that reading, but deriving both sides
#: from `ts_utc` keeps the finding side — which has no `ts_exchange` — and the record side on
#: one definition instead of two that agree by coincidence.
_BUCKETS: dict[str, tuple[str, str]] = {
    "hour_of_day": (
        "strftime(f.ts_start_utc AT TIME ZONE tz.name, '%H:00') || '-' || "
        "strftime(f.ts_start_utc AT TIME ZONE tz.name + INTERVAL 1 HOUR, '%H:00') "
        "|| ' ' || tz.name",
        "strftime(r.ts_utc AT TIME ZONE tz.name, '%H:00') || '-' || "
        "strftime(r.ts_utc AT TIME ZONE tz.name + INTERVAL 1 HOUR, '%H:00') "
        "|| ' ' || tz.name",
    ),
    "day_of_week": ("dayname(f.trade_date)", "dayname(r.trade_date)"),
    "trade_date": ("CAST(f.trade_date AS VARCHAR)", "CAST(r.trade_date AS VARCHAR)"),
    "contract": ("f.contract_id", "r.contract_id"),
    "frequency": ("f.frequency", "r.frequency"),
    "batch": ("b.filename", "rb.filename"),
}

DIMENSIONS: tuple[str, ...] = tuple(_BUCKETS)

#: Dimensions whose buckets are days, where `min_periods` cannot apply.
_ONE_DAY_PER_BUCKET = frozenset({"trade_date"})


@dataclass(frozen=True)
class Pattern:
    """One over-concentration, in the shape §12 fixes."""

    pattern_id: str
    rule_id: str
    dimension: str
    bucket: str
    share_of_findings: float
    share_of_records: float
    lift: float
    support: int
    distinct_days: int
    narrative: str
    confidence: str

    def as_json(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "rule_id": self.rule_id,
            "dimension": self.dimension,
            "bucket": self.bucket,
            "share_of_findings": self.share_of_findings,
            "share_of_records": self.share_of_records,
            "lift": self.lift,
            "support": self.support,
            "distinct_days": self.distinct_days,
            "narrative": self.narrative,
            "confidence": self.confidence,
        }


def pattern_id(rule_id: str, dimension: str, bucket: str) -> str:
    """A stable id for one `(rule, dimension, bucket)`.

    Deterministic rather than random, and that is load-bearing: patterns are recomputed on
    every request, so a suggestion's `from_pattern` has to name something the next request will
    produce again. A fresh ULID per call would make every suggestion cite a pattern that no
    longer exists by the time anyone looks it up.
    """
    digest = hashlib.sha1(f"{rule_id}|{dimension}|{bucket}".encode()).hexdigest()
    return f"p_{digest[:16]}"


def _scope(
    contracts: list[str] | None,
    start: date | None,
    end: date | None,
    *,
    prefix: str,
    frequency: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["TRUE"]
    args: list[Any] = []
    if contracts:
        placeholders = ", ".join("?" for _ in contracts)
        clauses.append(f"{prefix}contract_id IN ({placeholders})")
        args.extend(contracts)
    if start is not None:
        clauses.append(f"{prefix}trade_date >= ?")
        args.append(start)
    if end is not None:
        clauses.append(f"{prefix}trade_date <= ?")
        args.append(end)
    if frequency is not None:
        clauses.append(f"{prefix}frequency = ?")
        args.append(frequency)
    return " AND ".join(clauses), args


def find_patterns(
    con: duckdb.DuckDBPyConnection,
    *,
    contracts: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    run_id: str | None = None,
    lift: float = DEFAULT_LIFT,
    min_support: int = DEFAULT_MIN_SUPPORT,
    min_periods: int = DEFAULT_MIN_PERIODS,
    dimensions: tuple[str, ...] = DIMENSIONS,
    frequency: str | None = None,
) -> list[Pattern]:
    """Every `(rule, dimension, bucket)` whose findings concentrate beyond `lift`.

    Ordered by lift, then support, so the strongest concentration reads first. The three
    thresholds are all *and*-ed: a bucket has to be disproportionate, sizeable and recurrent,
    because any one of the three alone reports noise — a rule with four findings is 100%
    concentrated wherever those four landed.
    """
    unknown = [d for d in dimensions if d not in _BUCKETS]
    if unknown:
        raise ValueError(f"unknown pattern dimension(s) {unknown}")

    rule_totals = _rule_totals(con, contracts, start, end, run_id, frequency)
    if not rule_totals:
        return []
    records = _record_exposure(con, contracts, start, end, dimensions, frequency)

    patterns: list[Pattern] = []
    for dimension in dimensions:
        exposure = records.get(dimension, {})
        record_total = sum(exposure.values())
        if not record_total:
            continue
        for (rule_id, bucket), (support, days) in _finding_tallies(
            con, contracts, start, end, run_id, dimension, frequency
        ).items():
            rule_total = rule_totals.get(rule_id, 0)
            if not rule_total or bucket is None:
                continue
            share_of_findings = support / rule_total
            share_of_records = exposure.get(bucket, 0) / record_total
            if share_of_records <= 0:
                # A bucket holding findings and no records is not a lift, it is a join that
                # went wrong or a finding about absence — `CMP.SESSION_MISSING` names a day
                # with no records by definition. Reporting an infinite ratio would put the
                # loudest number in the report on the weakest evidence.
                continue
            measured = share_of_findings / share_of_records
            if measured < lift or support < min_support:
                continue
            if dimension not in _ONE_DAY_PER_BUCKET and days < min_periods:
                continue
            patterns.append(
                Pattern(
                    pattern_id=pattern_id(rule_id, dimension, bucket),
                    rule_id=rule_id,
                    dimension=dimension,
                    bucket=bucket,
                    share_of_findings=round(share_of_findings, 4),
                    share_of_records=round(share_of_records, 4),
                    lift=round(measured, 2),
                    support=support,
                    distinct_days=days,
                    narrative=_narrative(rule_id, dimension, bucket, share_of_findings, days),
                    confidence=_confidence(measured, support, days),
                )
            )
    return sorted(patterns, key=lambda p: (-p.lift, -p.support, p.pattern_id))


def _record_exposure(
    con: duckdb.DuckDBPyConnection,
    contracts: list[str] | None,
    start: date | None,
    end: date | None,
    dimensions: tuple[str, ...],
    frequency: str | None,
) -> dict[str, dict[str, int]]:
    """How the records themselves fall into each dimension's buckets — the denominator."""
    where, args = _scope(contracts, start, end, prefix="r.", frequency=frequency)
    out: dict[str, dict[str, int]] = {}
    for dimension in dimensions:
        expression = _BUCKETS[dimension][1]
        rows = con.execute(
            f"""
            SELECT {expression} AS bucket, count(*)
            FROM stage.market_record r
            LEFT JOIN ref.contract c ON c.contract_id = r.contract_id
            LEFT JOIN ref.product p ON p.root = c.root
            LEFT JOIN stage.ingest_batch rb ON rb.batch_id = r.batch_id
            CROSS JOIN (SELECT ? AS name) tz
            WHERE {where}
            GROUP BY 1
            """,
            [_TIMEZONE, *args],
        ).fetchall()
        out[dimension] = {row[0]: int(row[1]) for row in rows if row[0] is not None}
    return out


def _finding_tallies(
    con: duckdb.DuckDBPyConnection,
    contracts: list[str] | None,
    start: date | None,
    end: date | None,
    run_id: str | None,
    dimension: str,
    frequency: str | None,
) -> dict[tuple[str, str], tuple[int, int]]:
    """Findings per `(rule, bucket)`, with the number of distinct days they span."""
    where, args = _scope(contracts, start, end, prefix="f.", frequency=frequency)
    if run_id is not None:
        where += " AND f.run_id = ?"
        args.append(run_id)
    expression = _BUCKETS[dimension][0]
    rows = con.execute(
        f"""
        SELECT f.rule_id, {expression} AS bucket, count(*), count(DISTINCT f.trade_date)
        FROM dq.dq_finding f
        LEFT JOIN ref.contract c ON c.contract_id = f.contract_id
        LEFT JOIN ref.product p ON p.root = c.root
        LEFT JOIN stage.market_record m ON m.record_id = f.record_id
        LEFT JOIN stage.ingest_batch b ON b.batch_id = m.batch_id
        CROSS JOIN (SELECT ? AS name) tz
        WHERE {where} AND f.status = 'open'
        GROUP BY 1, 2
        """,
        [_TIMEZONE, *args],
    ).fetchall()
    return {
        (row[0], row[1]): (int(row[2]), int(row[3]))
        for row in rows
        if row[1] is not None
    }


def _rule_totals(
    con: duckdb.DuckDBPyConnection,
    contracts: list[str] | None,
    start: date | None,
    end: date | None,
    run_id: str | None,
    frequency: str | None,
) -> dict[str, int]:
    where, args = _scope(contracts, start, end, prefix="f.", frequency=frequency)
    if run_id is not None:
        where += " AND f.run_id = ?"
        args.append(run_id)
    rows = con.execute(
        f"SELECT f.rule_id, count(*) FROM dq.dq_finding f "
        f"WHERE {where} AND f.status = 'open' GROUP BY 1",
        args,
    ).fetchall()
    return {row[0]: int(row[1]) for row in rows}


def _narrative(
    rule_id: str, dimension: str, bucket: str, share: float, days: int
) -> str:
    """Templated prose, never generated (§12). Aggregates only; no raw market data."""
    percentage = f"{round(100 * share)}%"
    label = rule_id.split(".", 1)[-1].replace("_", " ").lower()
    phrasing = {
        "hour_of_day": f"fall in the {bucket} hour",
        "day_of_week": f"fall on {bucket}s",
        "trade_date": f"fall on {bucket}",
        "contract": f"sit on {bucket}",
        "frequency": f"sit in the {bucket} config",
        "batch": f"came from {bucket}",
    }[dimension]
    return (
        f"{percentage} of {label} findings {phrasing}, across {days} "
        f"session{'' if days == 1 else 's'}."
    )


def _confidence(lift: float, support: int, days: int) -> str:
    """Three words rather than a probability, because it is not one.

    A probability would imply a model that was fitted; this is a rule of thumb over how strong,
    how large and how repeated the concentration is, and saying so in words keeps a reader from
    doing arithmetic with it.
    """
    if lift >= 10 and support >= 100 and days >= 10:
        return "high"
    if lift >= 5 and support >= 50:
        return "medium"
    return "low"
