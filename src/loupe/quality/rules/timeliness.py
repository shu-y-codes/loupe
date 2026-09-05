"""Timeliness — `TIM.*`. Are timestamps where they should be?

`TIM.TIMEZONE_MISALIGNED` is the reason this family is not a footnote. If a file's timezone
was misread, every downstream number is wrong — trade dates, daily bars, gaps, VWAP session
boundaries — and **no other rule notices**, because each individual record still looks
perfectly well formed. It is the one `critical` in the catalogue that no amount of per-record
checking would ever find.
"""

from __future__ import annotations

from datetime import time

from loupe.data.preview import RECOGNISED_INTERVALS

from ..registry import RECORDS, Finding, RuleContext, rule

#: Interval label to seconds, inverted from the intervals preview is willing to name. A label
#: this map does not carry means the grid is unknown, and an unknown grid is not tested.
INTERVAL_SECONDS: dict[str, int] = {
    label: seconds for seconds, (label, _) in RECOGNISED_INTERVALS.items()
}

HOURS_IN_DAY = 24


@rule("TIM.OUT_OF_ORDER")
def out_of_order(ctx: RuleContext) -> list[Finding]:
    """`ts_utc` decreases as `source_row` increases within one contract and frequency.

    Ordered by `source_row` rather than by anything derived: the claim is about the order the
    file presented its rows in, which is why ingest preserves that number in the first place.
    """
    rows = ctx.con.execute(
        f"""
        WITH ordered AS (
          SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.source_row,
                 lag(r.ts_utc) OVER (PARTITION BY r.batch_id, r.contract_id, r.frequency
                                     ORDER BY r.source_row) AS prev_ts
          FROM {RECORDS} r
          WHERE {ctx.frequency_filter()}
        )
        SELECT record_id, contract_id, frequency, trade_date, ts_utc, source_row, prev_ts
        FROM ordered
        WHERE prev_ts IS NOT NULL AND ts_utc < prev_ts
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
                "source_row": int(source_row),
                "previous_ts_utc": str(prev_ts),
                "ts_utc": str(ts_utc),
            },
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, source_row, prev_ts in rows
    ]


@rule("TIM.FUTURE_TIMESTAMP")
def future_timestamp(ctx: RuleContext) -> list[Finding]:
    """A timestamp after the moment the record was ingested.

    Compared against `ingested_at` on the record rather than against `now()`, so a run in
    2027 does not retrospectively clear a file that was in the future when it landed.
    """
    rows = ctx.con.execute(
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.ingested_at
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()} AND r.ts_utc > r.ingested_at
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
            details={"ts_utc": str(ts_utc), "ingested_at": str(ingested_at)},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, ingested_at in rows
    ]


def _against_contract_date(ctx: RuleContext, column: str, comparison: str) -> list[Finding]:
    """Findings for records outside a `ref.contract` date bound.

    Null bounds are not a failure: reference data is inferred for every contract in this
    corpus, and comparing against a null would silently pass rather than silently fail.
    """
    rows = ctx.con.execute(
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.{column}
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()}
          AND r.{column} IS NOT NULL
          AND r.trade_date {comparison} r.{column}
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
            details={"trade_date": str(trade_date), column: str(bound)},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, bound in rows
    ]


@rule("TIM.BEFORE_LISTING")
def before_listing(ctx: RuleContext) -> list[Finding]:
    """The session precedes the contract's first trade date."""
    return _against_contract_date(ctx, "first_trade_date", "<")


@rule("TIM.AFTER_EXPIRY")
def after_expiry(ctx: RuleContext) -> list[Finding]:
    """The session follows the contract's last trade date. A record after expiry is not data."""
    return _against_contract_date(ctx, "last_trade_date", ">")


@rule("TIM.OFF_GRID")
def off_grid(ctx: RuleContext) -> list[Finding]:
    """A timestamp not aligned to the batch's inferred interval boundary.

    The interval is the one preview inferred and recorded on the batch, not one re-derived
    here: the grid a file was loaded against is a property of the load, and re-inferring it
    at rule time would let the two disagree.

    Alignment is judged on `ts_exchange`, the wall clock the file labelled, because that is
    the clock the grid is defined on. Judging a daily bar on `ts_utc` would call every row
    off-grid by the venue's UTC offset.
    """
    if not INTERVAL_SECONDS:
        return []
    placeholders = ", ".join("(CAST(? AS VARCHAR), CAST(? AS BIGINT))" for _ in INTERVAL_SECONDS)
    args: list[object] = []
    for label, seconds in sorted(INTERVAL_SECONDS.items()):
        args.extend([label, seconds])

    rows = ctx.con.execute(
        f"""
        WITH grid(label, seconds) AS (VALUES {placeholders})
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               g.label, g.seconds
        FROM {RECORDS} r
        JOIN grid g ON g.label = r.inferred_interval
        WHERE {ctx.frequency_filter()}
          AND CAST(epoch(r.ts_exchange) AS BIGINT) % g.seconds <> 0
        ORDER BY r.record_id
        """,
        args,
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            ts_start_utc=ts_utc,
            ts_end_utc=ts_utc,
            record_id=record_id,
            details={"inferred_interval": label, "interval_seconds": int(seconds)},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, label, seconds in rows
    ]


def _expected_dead_hour(open_local: time, close_local: time) -> int | None:
    """The single dead hour a near-24-hour session leaves, or None if there isn't exactly one.

    A CME-family session runs 17:00 to 16:00 and leaves exactly one 60-minute dead zone, at
    16:00. A session that closes for a third of the day — ICE Sugar's 02:30-11:59 — leaves a
    dead zone that is not one hour and carries no timezone signal at all, so it is not tested.
    """
    if open_local <= close_local:
        return None
    span = (24 * 60) - (
        open_local.hour * 60 + open_local.minute - close_local.hour * 60 - close_local.minute
    )
    dead = 24 * 60 - span
    if dead != 60 or close_local.minute != 0:
        return None
    return close_local.hour


@rule("TIM.TIMEZONE_MISALIGNED")
def timezone_misaligned(ctx: RuleContext) -> list[Finding]:
    """The file's activity dead zone is offset from the expected maintenance break.

    Detection compares *where the silence is*, not where the trading is: a 24-hour futures
    session is nearly uniform in coverage, so the one hour with no bars is the only sharp
    feature the histogram has. If it has moved by a whole number of hours, the labels were
    read in the wrong zone.

    The test is only meaningful where the file covers most of the clock and leaves exactly one
    dead hour, so both conditions are preconditions rather than findings.
    """
    min_records = int(ctx.param("min_records", 100))
    min_active_hours = int(ctx.param("min_active_hours", 20))

    profiles = {
        root: (open_local, close_local)
        for root, open_local, close_local in ctx.con.execute(
            "SELECT root, session_open_local, session_close_local FROM ref.product"
        ).fetchall()
    }
    rows = ctx.con.execute(
        f"""
        SELECT r.batch_id, r.root, hour(r.ts_exchange) AS local_hour, count(*) AS records,
               min(r.ts_utc) AS first_ts, max(r.ts_utc) AS last_ts
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()} AND r.root IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """
    ).fetchall()

    histograms: dict[tuple[str, str], dict[int, int]] = {}
    spans: dict[tuple[str, str], list] = {}
    for batch_id, root, local_hour, records, first_ts, last_ts in rows:
        key = (str(batch_id), root)
        histograms.setdefault(key, {})[int(local_hour)] = int(records)
        span = spans.setdefault(key, [first_ts, last_ts])
        span[0] = min(span[0], first_ts)
        span[1] = max(span[1], last_ts)

    findings: list[Finding] = []
    for (batch_id, root), histogram in histograms.items():
        profile = profiles.get(root)
        if profile is None:
            continue
        expected = _expected_dead_hour(*profile)
        if expected is None:
            continue

        total = sum(histogram.values())
        active = {hour for hour, count in histogram.items() if count > 0}
        if total < min_records or len(active) < min_active_hours:
            continue

        dead = sorted(set(range(HOURS_IN_DAY)) - active)
        if len(dead) != 1 or dead[0] == expected:
            continue

        offset = (dead[0] - expected + 12) % HOURS_IN_DAY - 12
        first_ts, last_ts = spans[(batch_id, root)]
        findings.append(
            ctx.finding(
                frequency="minute",
                ts_start_utc=first_ts,
                ts_end_utc=last_ts,
                affected_rows=total,
                details={
                    "batch_id": batch_id,
                    "root": root,
                    "expected_dead_hour_local": expected,
                    "observed_dead_hour_local": dead[0],
                    "offset_hours": offset,
                    "records": total,
                },
            )
        )
    return findings
