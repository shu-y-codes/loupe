"""Validity — `VAL.*`. Is each value individually possible?

Each value is judged on its own; relationships between fields are consistency's job.

Two rules here are deliberately not simple thresholds. `VAL.OFF_TICK_PRICE` reads the tick
from `(root, frequency, field)`, because the same root gives opposite verdicts across the two
configs — VX minute is 0 off-tick in 373,886 rows while VX daily `close` is off-tick in 805 of
959, and the second is a settlement carried to four decimals rather than 84% bad data. And
`VAL.ZERO_VOLUME_WITH_RANGE` asks *intraday* of the bar interval, not of the frequency name:
a minute bar exists because something transacted, while a daily summary is published for a
listed contract whether or not it traded.
"""

from __future__ import annotations

from ..registry import RECORDS, Finding, RuleContext, rule
from .completeness import _fields

PRICE_FIELDS = ("open", "high", "low", "close")


def _explode_prices(ctx: RuleContext, fields: list[str]) -> str:
    """A `(record, field, price)` relation over the requested price columns."""
    names = ", ".join(f"'{name}'" for name in fields)
    values = ", ".join(f"r.{name}" for name in fields)
    return f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.root,
               unnest([{names}]) AS field,
               unnest([{values}]) AS price
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()}
    """


@rule("VAL.NON_POSITIVE_PRICE")
def non_positive_price(ctx: RuleContext) -> list[Finding]:
    """A price at or below zero. A futures price can be negative in reality — CL settled at
    -37.63 in April 2020 — but not in this corpus's roots and horizons, and the `error`
    severity is what the calibration supports. A feed that carries negative settlements
    disables this rule in its row rather than in a code branch.
    """
    fields = _fields(ctx, PRICE_FIELDS)
    rows = ctx.con.execute(
        f"""
        SELECT record_id, contract_id, frequency, trade_date, ts_utc, field, price
        FROM ({_explode_prices(ctx, fields)})
        WHERE price IS NOT NULL AND price <= 0
        ORDER BY record_id, field
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
            details={"field": field, "value": price},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, field, price in rows
    ]


@rule("VAL.NEGATIVE_VOLUME")
def negative_volume(ctx: RuleContext) -> list[Finding]:
    """Volume below zero. A count of contracts traded has no negative value."""
    rows = ctx.con.execute(
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.volume
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()} AND r.volume < 0
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
            details={"field": "volume", "value": int(volume)},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, volume in rows
    ]


@rule("VAL.NON_INTEGER_VOLUME")
def non_integer_volume(ctx: RuleContext) -> list[Finding]:
    """The source volume label carries a fractional part.

    `stage.market_record.volume` is a `BIGINT`, so the fraction cannot survive the load —
    DuckDB rounds `'10.5'` to `11` and the defect would be invisible by the time any rule
    ran. Ingest therefore keeps the verbatim label in `volume_source`, and only when it is
    not an integer, so the column is null for every one of the 5.3 million clean rows.
    """
    rows = ctx.con.execute(
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               r.volume, r.volume_source
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()} AND r.volume_source IS NOT NULL
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
            details={
                "field": "volume",
                "source_value": source,
                "loaded_value": None if volume is None else int(volume),
            },
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, volume, source in rows
    ]


@rule("VAL.OFF_TICK_PRICE")
def off_tick_price(ctx: RuleContext) -> list[Finding]:
    """A price that is not a multiple of the tick for its `(root, frequency, field)`.

    Flag only, never exclude. A systematic off-tick pattern across a whole contract more
    likely means the tick reference is wrong than that the prices are, and the fix is to
    correct `ref.tick` — or mark the field settlement-bearing — not to discard 84% of a
    contract's prices. Fields marked `exempt`, and fields with a null tick, are not tested at
    all rather than given an invented lattice.
    """
    fields = _fields(ctx, PRICE_FIELDS)
    epsilon_ticks = float(ctx.param("epsilon_ticks", 1e-4))
    rows = ctx.con.execute(
        f"""
        SELECT e.record_id, e.contract_id, e.frequency, e.trade_date, e.ts_utc, e.field,
               e.price, t.tick_size
        FROM ({_explode_prices(ctx, fields)}) e
        JOIN ref.tick t
          ON t.root = e.root AND t.frequency = e.frequency AND t.field = e.field
        WHERE e.price IS NOT NULL
          AND t.tick_size IS NOT NULL
          AND t.tick_size > 0
          AND NOT t.exempt
          AND abs(e.price - round(e.price / t.tick_size) * t.tick_size) > t.tick_size * ?
        ORDER BY e.record_id, e.field
        """,
        [epsilon_ticks],
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
                "field": field,
                "value": price,
                "tick_size": tick,
                "residual": round(price - round(price / tick) * tick, 12),
            },
        )
        for (
            record_id,
            contract_id,
            frequency,
            trade_date,
            ts_utc,
            field,
            price,
            tick,
        ) in rows
    ]


@rule("VAL.ZERO_VOLUME_WITH_RANGE")
def zero_volume_with_range(ctx: RuleContext) -> list[Finding]:
    """Zero volume on a bar that nevertheless moved.

    Asked of `stage.ingest_batch.bar_interval`, so a five-minute file is judged the same way
    a one-minute file is. At daily the row is a settlement-only summary of a listed contract
    that did not trade, which is ordinary, so the severity drops to `params.daily_severity`;
    a null there disables the daily branch entirely.
    """
    wanted = list(ctx.param("frequencies", ["intraday"]))
    daily_severity = ctx.param("daily_severity")
    rows = ctx.con.execute(
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               r.high, r.low, r.bar_interval,
               r.bar_interval IS DISTINCT FROM '1 day' AS is_intraday
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()}
          AND r.volume = 0
          AND r.high IS NOT NULL AND r.low IS NOT NULL
          AND r.high > r.low
        ORDER BY r.record_id
        """
    ).fetchall()

    findings: list[Finding] = []
    for record_id, contract_id, freq, trade_date, ts_utc, high, low, interval, intraday in rows:
        if intraday:
            if "intraday" not in wanted:
                continue
            severity = ctx.severity
        else:
            if daily_severity is None:
                continue
            severity = str(daily_severity)
        findings.append(
            ctx.finding(
                severity=severity,
                contract_id=contract_id,
                frequency=freq,
                trade_date=trade_date,
                ts_start_utc=ts_utc,
                ts_end_utc=ts_utc,
                record_id=record_id,
                details={
                    "bar_interval": interval,
                    "range": round(high - low, 12),
                    "basis": "intraday" if intraday else "daily",
                },
            )
        )
    return findings


@rule("VAL.PRICE_MAGNITUDE")
def price_magnitude(ctx: RuleContext) -> list[Finding]:
    """A price outside the plausible band for its root — a decimal-shift detector.

    Bands are per root because one band cannot serve ES at ~6,000, ZC at ~475 (cents per
    bushel) and SR3 at ~97 at once. A root with no band is not evaluated: an invented band is
    worse than no test.
    """
    fields = _fields(ctx, PRICE_FIELDS)
    bands = dict(ctx.param("bands", {}))
    if not bands:
        return []

    placeholders = ", ".join(
        "(CAST(? AS VARCHAR), CAST(? AS DOUBLE), CAST(? AS DOUBLE))" for _ in bands
    )
    args: list[object] = []
    for root, (low, high) in sorted(bands.items()):
        args.extend([root, float(low), float(high)])

    rows = ctx.con.execute(
        f"""
        WITH bands(root, lo, hi) AS (VALUES {placeholders})
        SELECT e.record_id, e.contract_id, e.frequency, e.trade_date, e.ts_utc, e.field,
               e.price, b.lo, b.hi
        FROM ({_explode_prices(ctx, fields)}) e
        JOIN bands b ON b.root = e.root
        WHERE e.price IS NOT NULL AND (e.price < b.lo OR e.price > b.hi)
        ORDER BY e.record_id, e.field
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
            details={"field": field, "value": price, "plausible_range": [low, high]},
        )
        for (
            record_id,
            contract_id,
            frequency,
            trade_date,
            ts_utc,
            field,
            price,
            low,
            high,
        ) in rows
    ]


@rule("VAL.EXTREME_VOLUME")
def extreme_volume(ctx: RuleContext) -> list[Finding]:
    """Volume above the plausible ceiling for the granularity. Informational only.

    The ceiling is per granularity rather than per root: a daily volume is three orders of
    magnitude above a minute bar's for the same contract, so one number cannot serve both.
    """
    ceilings = dict(ctx.param("max_plausible", {}))
    if not ceilings:
        return []
    placeholders = ", ".join(
        "(CAST(? AS VARCHAR), CAST(? AS BIGINT))" for _ in ceilings
    )
    args: list[object] = []
    for frequency, ceiling in sorted(ceilings.items()):
        args.extend([frequency, int(ceiling)])

    rows = ctx.con.execute(
        f"""
        WITH ceilings(frequency, max_plausible) AS (VALUES {placeholders})
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.volume,
               c.max_plausible
        FROM {RECORDS} r
        JOIN ceilings c ON c.frequency = r.frequency
        WHERE {ctx.frequency_filter()} AND r.volume > c.max_plausible
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
            details={"field": "volume", "value": int(volume), "max_plausible": int(ceiling)},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, volume, ceiling in rows
    ]
