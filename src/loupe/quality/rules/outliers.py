"""Outliers — `OUT.*`. Robust, on returns, and never a verdict.

Three decisions, all from `specs/analytics-semantics.md` §5:

**A modified z-score, not a z-score.** Financial returns have fat tails, so a 3-sigma
threshold flags too much in a genuinely volatile period — and a single extreme print inflates
the standard deviation enough to hide itself. The median absolute deviation is resistant to
both. Constants `0.6745` and `3.5` are the Iglewicz-Hoaglin choices and live in the seeded row.

**On log returns, not on prices.** Prices trend; returns do not. A rule computed on prices
would flag every day of a bull market and nothing on a crash.

**`info`, always.** An outlier is a *question*, never a verdict: any volatile window in this
corpus is full of legitimate extreme returns. These never auto-exclude — `info` is below the
excluding severities, so the cleaning policy needs no special case for them.

Computed on records that survive cleaning, so that hard invalids do not dominate the
distribution. On a first pass nothing has been excluded yet and the population is the raw
scope; on a re-run after cleaning it is the clean one, which is the intended reading.
"""

from __future__ import annotations

from ..registry import RECORDS, Finding, RuleContext, rule

#: Records the cleaning log has already removed. A negative outlier test run over a fat-finger
#: print measures the print, not the series.
_SURVIVING = f"""
  SELECT r.* FROM {RECORDS} r
  WHERE NOT EXISTS (
    SELECT 1 FROM dq.cleaning_action a
    WHERE a.record_id = r.record_id AND a.action IN ('exclude', 'dedupe_drop')
  )
"""


def _mad_findings(ctx: RuleContext, value_sql: str, guard: str, label: str) -> list[Finding]:
    """One modified z-score pass over `value_sql`, per contract and frequency.

    Three stages because a median cannot be nested inside another aggregate: the median of the
    series, the median of the absolute deviations from it, then the score itself.
    """
    threshold = float(ctx.param("threshold", 3.5))
    constant = float(ctx.param("constant", 0.6745))
    min_records = int(ctx.param("min_records", 30))

    rows = ctx.con.execute(
        f"""
        WITH surviving AS ({_SURVIVING}),
        valued AS (
          SELECT record_id, contract_id, frequency, trade_date, ts_utc, source_row,
                 {value_sql} AS v
          FROM surviving r
          WHERE {ctx.frequency_filter()} AND {guard}
        ),
        centre AS (
          SELECT contract_id, frequency, median(v) AS med, count(*) AS n
          FROM valued WHERE v IS NOT NULL
          GROUP BY 1, 2
          HAVING count(*) >= ?
        ),
        spread AS (
          SELECT c.contract_id, c.frequency, c.med,
                 median(abs(v.v - c.med)) AS mad
          FROM valued v
          JOIN centre c ON c.contract_id = v.contract_id AND c.frequency = v.frequency
          WHERE v.v IS NOT NULL
          GROUP BY 1, 2, 3
        )
        SELECT v.record_id, v.contract_id, v.frequency, v.trade_date, v.ts_utc,
               v.v, s.med, s.mad,
               ? * (v.v - s.med) / s.mad AS modified_z
        FROM valued v
        JOIN spread s ON s.contract_id = v.contract_id AND s.frequency = v.frequency
        WHERE v.v IS NOT NULL AND s.mad > 0
          AND abs(? * (v.v - s.med) / s.mad) > ?
        ORDER BY v.record_id
        """,
        [min_records, constant, constant, threshold],
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
                label: value,
                "median": median,
                "mad": mad,
                "modified_z": modified_z,
                "threshold": threshold,
            },
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, value, median, mad, modified_z
        in rows
    ]


@rule("OUT.RETURN_MAD")
def return_mad(ctx: RuleContext) -> list[Finding]:
    """Modified z-score on `ln(close_t / close_{t-1})` exceeds `params.threshold`.

    Ordered by `(ts_utc, source_row)` within a contract and frequency, so the return is
    between consecutive records of the same series and never across a contract boundary.
    """
    log_return = """
        ln(r.close / lag(r.close) OVER (
            PARTITION BY r.contract_id, r.frequency ORDER BY r.ts_utc, r.source_row))
    """
    return _mad_findings(
        ctx,
        log_return,
        guard="r.close IS NOT NULL AND r.close > 0",
        label="log_return",
    )


@rule("OUT.VOLUME_MAD")
def volume_mad(ctx: RuleContext) -> list[Finding]:
    """The same score on `ln(volume)`.

    Zero-volume records are outside the population rather than outliers within it: `ln(0)` is
    undefined, and a session that did not trade is `VAL.ZERO_VOLUME_WITH_RANGE`'s subject.
    """
    return _mad_findings(
        ctx,
        "ln(r.volume)",
        guard="r.volume IS NOT NULL AND r.volume > 0",
        label="log_volume",
    )
