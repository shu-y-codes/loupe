"""Consistency — `CON.*`. Do values agree with each other, and with the calendar?

The load-bearing decision in this family is that `CON.WEEKEND_RECORD` is computed on the
**derived** session date and on nothing else. A vendor `trading_date` is an assertion, not a
fact: run against this corpus's column it reports 179,934 weekend records, every one of them
a Sunday-evening CME bar that belongs to Monday's session. On the derived date the count is
zero (`specs/sample-corpus.md` §7.1).

`CON.DERIVED_BAR_INVALID` is the one rule in this family that reads a mart rather than the
record set: the same violation means opposite things depending on where the bar came from, and
only `mart.bar_daily` knows that.
"""

from __future__ import annotations

from ..registry import RECORDS, Finding, RuleContext, RuleRefusal, rule
from .completeness import HALTS_CTE

# Where high < low the bar's range is inverted and "inside the range" means nothing, so the
# open/close tests stand down and let CON.HIGH_LT_LOW report the one real defect rather than
# emitting three findings for it.
RANGE_IS_MEANINGFUL = "r.high IS NOT NULL AND r.low IS NOT NULL AND r.high >= r.low"


def _record_findings(ctx: RuleContext, sql: str, args: list[object] | None = None) -> list[Finding]:
    """Run a query shaped `(record_id, contract_id, frequency, trade_date, ts_utc, details)`."""
    rows = ctx.con.execute(sql, args or []).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            ts_start_utc=ts_utc,
            ts_end_utc=ts_utc,
            record_id=record_id,
            details=details,
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, details in rows
    ]


@rule("CON.HIGH_LT_LOW")
def high_lt_low(ctx: RuleContext) -> list[Finding]:
    """`high < low`. The bar cannot be repaired from its own fields, so the record is excluded."""
    return _record_findings(
        ctx,
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               {{'high': r.high, 'low': r.low}} AS details
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()}
          AND r.high IS NOT NULL AND r.low IS NOT NULL AND r.high < r.low
        ORDER BY r.record_id
        """,
    )


@rule("CON.OPEN_OUT_OF_RANGE")
def open_out_of_range(ctx: RuleContext) -> list[Finding]:
    """`open` outside `[low, high]`, judged only where the range itself is coherent."""
    return _record_findings(
        ctx,
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               {{'field': 'open', 'value': r.open, 'low': r.low, 'high': r.high}} AS details
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()} AND {RANGE_IS_MEANINGFUL}
          AND r.open IS NOT NULL AND (r.open < r.low OR r.open > r.high)
        ORDER BY r.record_id
        """,
    )


@rule("CON.CLOSE_OUT_OF_RANGE")
def close_out_of_range(ctx: RuleContext) -> list[Finding]:
    """`close` outside `[low, high]`.

    On a vendor daily row this is often a settlement struck outside the traded range rather
    than a corrupt value — the 43 invalid-OHLC daily rows in this corpus are all of that kind.
    Distinguishing the two needs bar provenance, which arrives with `CON.DERIVED_BAR_INVALID`
    in slice 3; until then the record-scope check reports what it sees.
    """
    return _record_findings(
        ctx,
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               {{'field': 'close', 'value': r.close, 'low': r.low, 'high': r.high}} AS details
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()} AND {RANGE_IS_MEANINGFUL}
          AND r.close IS NOT NULL AND (r.close < r.low OR r.close > r.high)
        ORDER BY r.record_id
        """,
    )


@rule("CON.WEEKEND_RECORD")
def weekend_record(ctx: RuleContext) -> list[Finding]:
    """The **derived** session date falls on a Saturday or Sunday.

    `trade_date` is assigned at ingest from the timestamp and the root's session boundary, so
    a Sunday-evening bar carries Monday's date and does not fire here. That is the whole
    point of the rule: on the vendor's own date column the same corpus yields 179,934 false
    positives.
    """
    return _record_findings(
        ctx,
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               {{'trade_date': CAST(r.trade_date AS VARCHAR),
                 'weekday': dayname(r.trade_date)}} AS details
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()} AND dayofweek(r.trade_date) IN (0, 6)
        ORDER BY r.record_id
        """,
    )


@rule("CON.RECORD_IN_HALT")
def record_in_halt(ctx: RuleContext) -> list[Finding]:
    """The timestamp falls inside an intra-session halt or maintenance break.

    Only *intra*-session halts are in `ref.session_calendar`: the CME 16:00-17:00 break falls
    between two sessions and is expressed by the session bounds, so it is not a halt and a
    record there is off-session rather than halted.
    """
    return _record_findings(
        ctx,
        f"""
        WITH {HALTS_CTE}
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               {{'halt_start_utc': CAST(h.start_utc AS VARCHAR),
                 'halt_end_utc': CAST(h.end_utc AS VARCHAR)}} AS details
        FROM {RECORDS} r
        JOIN halts h ON h.root = r.root AND h.trade_date = r.trade_date
        WHERE {ctx.frequency_filter()}
          AND r.ts_utc >= h.start_utc AND r.ts_utc < h.end_utc
        ORDER BY r.record_id
        """,
    )


@rule("CON.RECORD_ON_HOLIDAY")
def record_on_holiday(ctx: RuleContext) -> list[Finding]:
    """The record's session is a full closure.

    Only New Year's Day and Christmas Day are full closures in this corpus; every other US
    market holiday carries rows because Globex runs a shortened session, and those are early
    closes rather than holidays (`specs/sample-corpus.md` §5.2).
    """
    return _record_findings(
        ctx,
        f"""
        SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
               {{'trade_date': CAST(r.trade_date AS VARCHAR)}} AS details
        FROM {RECORDS} r
        JOIN ref.session_calendar c ON c.root = r.root AND c.trade_date = r.trade_date
        WHERE {ctx.frequency_filter()} AND c.is_holiday
        ORDER BY r.record_id
        """,
    )


@rule("CON.STALE_REPEAT")
def stale_repeat(ctx: RuleContext) -> list[Finding]:
    """A run of `n` consecutive records with identical OHLC and non-zero volume.

    `n` is per root, and that is not a refinement: at `n = 10` this rule fires 14,830 times on
    the corpus and 13,285 of those are SR3, a rate contract in a three-point band where an
    unchanged price for 94 consecutive minutes is ordinary. ES and GC produce zero, which is
    the right answer for a liquid instrument and the evidence the rule is sound.

    A record with a null price or zero volume breaks the run rather than being skipped over,
    so two genuinely separate flat stretches are never joined into one finding.
    """
    default_n = int(ctx.param("n", 30))
    by_root = dict(ctx.param("n_by_root", {}))

    if by_root:
        placeholders = ", ".join("(CAST(? AS VARCHAR), CAST(? AS BIGINT))" for _ in by_root)
        args: list[object] = []
        for root, n in sorted(by_root.items()):
            args.extend([root, int(n)])
        overrides = f"n_by_root(root, n) AS (VALUES {placeholders})"
    else:
        args = []
        overrides = "n_by_root(root, n) AS (SELECT NULL, NULL WHERE FALSE)"

    rows = ctx.con.execute(
        f"""
        WITH {overrides},
        ordered AS (
          SELECT r.record_id, r.contract_id, r.frequency, r.root, r.trade_date, r.ts_utc,
                 r.open, r.high, r.low, r.close, r.volume,
                 row_number() OVER (PARTITION BY r.contract_id, r.frequency
                                    ORDER BY r.ts_utc, r.record_id) AS rn
          FROM {RECORDS} r
          WHERE {ctx.frequency_filter()}
        ),
        flagged AS (
          SELECT *,
                 CASE WHEN open IS NOT NULL
                       AND open  IS NOT DISTINCT FROM lag(open)  OVER w
                       AND high  IS NOT DISTINCT FROM lag(high)  OVER w
                       AND low   IS NOT DISTINCT FROM lag(low)   OVER w
                       AND close IS NOT DISTINCT FROM lag(close) OVER w
                       AND coalesce(volume, 0) <> 0
                       AND coalesce(lag(volume) OVER w, 0) <> 0
                      THEN 0 ELSE 1 END AS is_break
          FROM ordered
          WINDOW w AS (PARTITION BY contract_id, frequency ORDER BY rn)
        ),
        runs AS (
          SELECT *, sum(is_break) OVER (PARTITION BY contract_id, frequency ORDER BY rn) AS run_id
          FROM flagged
        ),
        collapsed AS (
          SELECT contract_id, frequency, root, run_id,
                 min(trade_date) AS trade_date,
                 min(ts_utc) AS first_ts, max(ts_utc) AS last_ts,
                 count(*) AS run_length,
                 any_value(close) AS repeated_close
          FROM runs
          GROUP BY contract_id, frequency, root, run_id
        )
        SELECT c.contract_id, c.frequency, c.trade_date, c.first_ts, c.last_ts, c.run_length,
               coalesce(o.n, ?) AS threshold, c.repeated_close
        FROM collapsed c
        LEFT JOIN n_by_root o ON o.root = c.root
        WHERE c.run_length >= coalesce(o.n, ?)
        ORDER BY 1, 2, 4
        """,
        [*args, default_n, default_n],
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            ts_start_utc=first_ts,
            ts_end_utc=last_ts,
            affected_rows=int(run_length),
            details={
                "run_length": int(run_length),
                "threshold_n": int(threshold),
                "repeated_close": close,
            },
        )
        for (
            contract_id,
            frequency,
            trade_date,
            first_ts,
            last_ts,
            run_length,
            threshold,
            close,
        ) in rows
    ]


@rule("CON.PRICE_JUMP")
def price_jump(ctx: RuleContext) -> list[Finding]:
    """An absolute log return between consecutive records above the threshold.

    Informational: a jump is evidence, not a verdict. Thresholds are per granularity because a
    5% move is remarkable in one minute and unremarkable across a session.
    """
    thresholds = ctx.param("threshold", {})
    if not isinstance(thresholds, dict) or not thresholds:
        return []
    placeholders = ", ".join("(CAST(? AS VARCHAR), CAST(? AS DOUBLE))" for _ in thresholds)
    args: list[object] = []
    for frequency, threshold in sorted(thresholds.items()):
        args.extend([frequency, float(threshold)])

    rows = ctx.con.execute(
        f"""
        WITH thresholds(frequency, threshold) AS (VALUES {placeholders}),
        ordered AS (
          SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc, r.close,
                 lag(r.close) OVER (PARTITION BY r.contract_id, r.frequency
                                    ORDER BY r.ts_utc, r.record_id) AS prev_close
          FROM {RECORDS} r
          WHERE {ctx.frequency_filter()} AND r.close IS NOT NULL AND r.close > 0
        )
        SELECT o.record_id, o.contract_id, o.frequency, o.trade_date, o.ts_utc,
               {{'log_return': ln(o.close / o.prev_close),
                 'previous_close': o.prev_close,
                 'close': o.close,
                 'threshold': t.threshold}} AS details
        FROM ordered o
        JOIN thresholds t ON t.frequency = o.frequency
        WHERE o.prev_close IS NOT NULL AND o.prev_close > 0
          AND abs(ln(o.close / o.prev_close)) > t.threshold
        ORDER BY o.record_id
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
            details=details,
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, details in rows
    ]


@rule("CON.DERIVED_BAR_INVALID")
def derived_bar_invalid(ctx: RuleContext) -> list[Finding]:
    """A daily bar violates `low <= open, close <= high`.

    **Severity follows provenance**, and the two branches mean opposite things. On a derived
    bar it is critical: Loupe built this from records it had already validated, so a defect
    escaped record-level validation and the series is not safe to publish. On a vendor bar it
    is a warning: the vendor's close is a settlement struck near 15:00 local, which is not
    obliged to sit inside the traded range and does not on 43 rows of this corpus
    (`specs/sample-corpus.md` §7.5). Blocking those would be accurate about the arithmetic and
    wrong about the data.

    Both severities are read from the seeded row — the vendor branch from
    `params.vendor_severity` — so a deployment can change either without a code change. The
    precedent is `VAL.ZERO_VOLUME_WITH_RANGE`, which varies the same way on `daily_severity`.

    Evaluated on the published basis (`params.basis`, `clean` by default). A bar the cleaning
    policy already repaired is not a defect that escaped validation; it is validation working.
    """
    basis = str(ctx.param("basis", "clean"))
    vendor_severity = str(ctx.param("vendor_severity", "warning"))

    scoped = ctx.con.execute(
        f"SELECT count(*) FROM mart.bar_daily b "
        f"WHERE b.basis = ? AND b.contract_id IN (SELECT DISTINCT contract_id FROM {RECORDS})",
        [basis],
    ).fetchone()
    if not scoped or scoped[0] == 0:
        # Distinct from "evaluated and found nothing": with no bars materialised there is
        # nothing to check, and reporting a clean result would be a claim we cannot make.
        raise RuleRefusal(
            f"no {basis} bars in mart.bar_daily for the contracts in scope; "
            "run loupe.insights.build_bars first"
        )

    rows = ctx.con.execute(
        f"""
        SELECT b.contract_id, b.source_frequency, b.trade_date, b.first_ts_utc, b.last_ts_utc,
               b.source, b.open, b.high, b.low, b.close, b.record_count
        FROM mart.bar_daily b
        WHERE b.basis = ?
          AND b.contract_id IN (SELECT DISTINCT contract_id FROM {RECORDS})
          AND b.high IS NOT NULL AND b.low IS NOT NULL
          AND (b.high < b.low
               OR (b.open IS NOT NULL AND (b.open < b.low OR b.open > b.high))
               OR (b.close IS NOT NULL AND (b.close < b.low OR b.close > b.high)))
        ORDER BY b.contract_id, b.trade_date, b.source
        """,
        [basis],
    ).fetchall()

    findings: list[Finding] = []
    for contract_id, frequency, trade_date, first_ts, last_ts, source, o, h, low, c, n in rows:
        vendor = source == "vendor"
        findings.append(
            ctx.finding(
                severity=vendor_severity if vendor else ctx.severity,
                contract_id=contract_id,
                frequency=frequency,
                trade_date=trade_date,
                ts_start_utc=first_ts,
                ts_end_utc=last_ts,
                affected_rows=n,
                details={
                    "basis": basis,
                    "source": source,
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "explanation": (
                        "vendor settlement close outside the traded range; expected on an "
                        "untraded or thinly traded session, see REC.CLOSE_CONVENTION"
                        if vendor
                        else "derived bar violates its own OHLC invariants; a defect escaped "
                        "record-level validation"
                    ),
                },
            )
        )
    return findings
