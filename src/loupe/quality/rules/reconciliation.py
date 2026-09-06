"""Reconciliation — `REC.*`. Does the tape agree with the file that claims to summarise it?

The only family that can catch data which is internally perfect and still wrong, and the only
one that cannot run at all unless both granularities were supplied. Everything here reads the
shared frame in `..reconciliation`, so the sessions these rules judge are exactly the sessions
the scorer counts and `..corroboration` reads back.

Three properties are load-bearing rather than tidy.

**`frequency` is the side the finding is a statement about**, `compare_frequency` the side it
was checked against (§8). `REC.OHLC_DISAGREE` says the vendor's stated high is wrong, so it is
`daily`; `REC.VOLUME_SHORTFALL` says the *tape* is short, so it is `minute`. This is not
presentation: the Risk closing-day callout filters at `frequency = 'daily'` (§11.6), so a
finding written on the wrong side is dropped silently instead of failing.

**Coverage gates the range comparison and nothing else.** A session holding half its tape
cannot reproduce a high or a low, and the invariant that the vendor range is never the narrower
one holds only on complete sessions (`specs/sample-corpus.md` §6.5). Volume is not gated: the
shortfall is measured against what the vendor claims, and an incomplete tape *is* short.

**The close is a settlement until the mark says otherwise.** §8.4 splits one difference two
ways — nearer the settlement mark than the session end is `REC.CLOSE_CONVENTION` and `info`,
anything else is `REC.OHLC_DISAGREE` on `close` and an error. Where the mark cannot be resolved
for a root, *neither* fires. That under-reports an info rule rather than accusing a settlement
of being wrong for behaving like a settlement, which is the error §8.4 exists to prevent.
"""

from __future__ import annotations

from typing import Any

from ..reconciliation import session_frame_sql, settlement_marks
from ..registry import RECORDS, Finding, RuleContext, rule

#: The fields `REC.OHLC_DISAGREE` may be asked to compare. `close` is not in the seeded
#: default: it arrives only through §8.4's branch, which needs the settlement mark to decide
#: whether a difference is a defect at all.
COMPARABLE_FIELDS = ("open", "high", "low")


def _tick_join(field: str) -> str:
    """The tick for `(root, 'daily', field)`, or nothing.

    Tolerances are expressed in ticks and never in absolute price (§8.2), so the lattice is a
    property of the field rather than a global. Where no tick is known the comparison is exact
    and the finding says so, rather than inventing one.
    """
    return f"""
      LEFT JOIN ref.tick t
        ON t.root = f.root AND t.frequency = 'daily' AND t.field = '{field}'
    """


def _session_finding(
    ctx: RuleContext,
    row: Any,
    *,
    frequency: str,
    compare_frequency: str,
    details: dict[str, Any],
    severity: str | None = None,
) -> Finding:
    """One session-scoped finding. No `record_id`: the subject is the session, not a row."""
    contract_id, trade_date, ts_start, ts_end = row
    kwargs: dict[str, Any] = {}
    if severity is not None:
        kwargs["severity"] = severity
    return ctx.finding(
        contract_id=contract_id,
        frequency=frequency,
        compare_frequency=compare_frequency,
        trade_date=trade_date,
        ts_start_utc=ts_start,
        ts_end_utc=ts_end,
        details=details,
        **kwargs,
    )


@rule("REC.OHLC_DISAGREE")
def ohlc_disagree(ctx: RuleContext) -> list[Finding]:
    """A field of the vendor's daily row differs from the same field derived from the tape.

    `frequency = 'daily'`, because the claim is that the vendor's stated number is wrong; the
    tape is the evidence and travels in `compare_frequency`.

    Coverage-gated on the **calendar's** expected slots rather than on a maximum inferred from
    the upload (§8.1). A file that is short everywhere would otherwise define its own gate away
    and report 126 disagreements that are really 126 incomplete sessions.
    """
    tolerance_ticks = float(ctx.param("tolerance_ticks", 0))
    min_coverage = float(ctx.param("min_coverage_pct", 0.98))
    fields = list(ctx.param("fields", list(COMPARABLE_FIELDS)))
    unknown = [f for f in fields if f not in COMPARABLE_FIELDS]
    if unknown:
        raise ValueError(f"{ctx.rule.rule_id}: params.fields names unknown columns {unknown}")

    findings: list[Finding] = []
    for field in fields:
        rows = ctx.con.execute(
            f"""
            SELECT f.contract_id, f.trade_date, f.first_ts_utc, f.last_ts_utc,
                   f.derived_{field}, f.vendor_{field}, t.tick_size,
                   f.coverage_pct, f.minute_records, f.expected_slots
            FROM ({session_frame_sql()}) f
            {_tick_join(field)}
            WHERE f.has_minute AND f.has_daily AND f.in_window
              AND f.coverage_pct IS NOT NULL AND f.coverage_pct >= ?
              AND f.derived_{field} IS NOT NULL AND f.vendor_{field} IS NOT NULL
              AND abs(f.vendor_{field} - f.derived_{field})
                  > coalesce(t.tick_size, 0) * ?
            ORDER BY f.contract_id, f.trade_date
            """,
            [min_coverage, tolerance_ticks],
        ).fetchall()
        for row in rows:
            derived, vendor, tick = row[4], row[5], row[6]
            difference = round(vendor - derived, 12)
            findings.append(
                _session_finding(
                    ctx,
                    row[:4],
                    frequency="daily",
                    compare_frequency="minute",
                    details={
                        "field": field,
                        "vendor": vendor,
                        "derived": derived,
                        "difference": difference,
                        "tick_size": tick,
                        # Named rather than implied: a reader of the finding has to be able
                        # to tell a one-tick tolerance from an exact comparison made because
                        # no tick is known for this field (§8.2).
                        "comparison": "exact" if tick is None else f"{tolerance_ticks} tick(s)",
                        "difference_ticks": (
                            None if not tick else round(difference / tick, 6)
                        ),
                        "minute_coverage_pct": (
                            None if row[7] is None else round(100.0 * row[7], 4)
                        ),
                        "minute_records": row[8],
                        "expected_slots": row[9],
                    },
                )
            )

    findings.extend(_close_disagreements(ctx, min_coverage))
    return findings


def _close_side_sql(ctx: RuleContext) -> tuple[str, list[object]] | None:
    """The §8.4 comparison: each session's close beside the bar nearest the settlement mark.

    Returns `None` when no mark is configured at all, which stands the close comparison down
    everywhere rather than falling back to a time nobody chose.
    """
    marks = settlement_marks(ctx.con)
    if not marks:
        return None
    tolerance_minutes = _mark_tolerance_minutes(ctx)
    per_root = {root: value for root, value in marks.items() if root != "default"}
    default_mark = marks.get("default")

    if per_root:
        values = ", ".join("(?, ?)" for _ in per_root)
        mark_cte = f"marks(root, mark_local) AS (SELECT * FROM (VALUES {values}) v(a, b))"
        args: list[object] = []
        for root, value in per_root.items():
            args.extend([root, value])
    else:
        mark_cte = "marks(root, mark_local) AS (SELECT NULL, NULL WHERE FALSE)"
        args = []

    sql = f"""
    WITH frame AS ({session_frame_sql()}),
    {mark_cte},
    resolved AS (
      SELECT f.*, coalesce(m.mark_local, ?)::TIME AS mark_local
      FROM frame f
      LEFT JOIN marks m ON m.root = f.root
    ),
    nearest AS (
      SELECT s.contract_id, s.trade_date,
             arg_min({{'close': r.close,
                      'gap': abs(epoch(r.ts_exchange::TIME) - epoch(s.mark_local)) / 60.0}},
                     abs(epoch(r.ts_exchange::TIME) - epoch(s.mark_local))) AS bar
      FROM resolved s
      JOIN {RECORDS} r
        ON r.contract_id = s.contract_id AND r.trade_date = s.trade_date
       AND r.frequency = 'minute' AND r.close IS NOT NULL
      WHERE s.mark_local IS NOT NULL
      GROUP BY 1, 2
    )
    SELECT s.contract_id, s.trade_date, s.first_ts_utc, s.last_ts_utc,
           s.derived_close, s.vendor_close, t.tick_size, s.coverage_pct,
           n.bar.close AS mark_close, n.bar.gap AS mark_gap_minutes,
           s.mark_local,
           n.bar.gap IS NOT NULL AND n.bar.gap <= {tolerance_minutes} AS mark_resolved,
           abs(s.vendor_close - n.bar.close) < abs(s.vendor_close - s.derived_close)
             AS settlement_signature
    FROM resolved s
    LEFT JOIN nearest n
      ON n.contract_id = s.contract_id AND n.trade_date = s.trade_date
    LEFT JOIN ref.tick t
      ON t.root = s.root AND t.frequency = 'daily' AND t.field = 'close'
    WHERE s.has_minute AND s.has_daily AND s.in_window
      AND s.derived_close IS NOT NULL AND s.vendor_close IS NOT NULL
    """
    return sql, [*args, default_mark]


def _mark_tolerance_minutes(ctx: RuleContext) -> int:
    """How near a bar must fall to the mark for the mark to count as resolved.

    Read from `REC.CLOSE_CONVENTION`'s row for the same reason the mark itself is: the two
    rules split one decision and must not disagree about where the line is.
    """
    row = ctx.con.execute(
        "SELECT params->>'mark_tolerance_minutes' FROM dq.dq_rule "
        "WHERE rule_id = 'REC.CLOSE_CONVENTION'"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 60


def _close_disagreements(ctx: RuleContext, min_coverage: float) -> list[Finding]:
    """`REC.OHLC_DISAGREE` on `close` — only where the settlement signature is **absent**.

    A settlement is under no obligation to equal the last trade, so a difference that looks
    like a settlement is `REC.CLOSE_CONVENTION`'s to report at `info`. This branch is the other
    half: the closes differ, the vendor's is no nearer the mark than the session end, and there
    is no convention to explain it.
    """
    prepared = _close_side_sql(ctx)
    if prepared is None:
        return []
    sql, args = prepared
    tolerance_ticks = float(ctx.param("tolerance_ticks", 0))
    rows = ctx.con.execute(
        f"""
        SELECT contract_id, trade_date, first_ts_utc, last_ts_utc,
               derived_close, vendor_close, tick_size, coverage_pct, mark_close, mark_local
        FROM ({sql})
        WHERE coverage_pct IS NOT NULL AND coverage_pct >= ?
          AND mark_resolved AND NOT settlement_signature
          AND abs(vendor_close - derived_close) > coalesce(tick_size, 0) * ?
        ORDER BY contract_id, trade_date
        """,
        [*args, min_coverage, tolerance_ticks],
    ).fetchall()
    return [
        _session_finding(
            ctx,
            row[:4],
            frequency="daily",
            compare_frequency="minute",
            details={
                "field": "close",
                "vendor": row[5],
                "derived": row[4],
                "difference": round(row[5] - row[4], 12),
                "tick_size": row[6],
                "comparison": "exact" if row[6] is None else f"{tolerance_ticks} tick(s)",
                "settlement_mark_local": str(row[9]),
                "close_at_mark": row[8],
                # The discriminator, recorded so a reader can check the verdict rather than
                # take it: the vendor close is no nearer the mark than the session end, so
                # the settlement explanation of §8.4 does not apply.
                "settlement_signature": False,
                "minute_coverage_pct": (
                    None if row[7] is None else round(100.0 * row[7], 4)
                ),
            },
        )
        for row in rows
    ]


@rule("REC.CLOSE_CONVENTION")
def close_convention(ctx: RuleContext) -> list[Finding]:
    """The two closes differ in the manner expected of a settlement versus a last trade.

    `info`, and it must stay `info`: it fires on the *expected* difference between a settlement
    struck near the mark and the last print of the session (§8.4). Auto-excluding on it would
    discard the daily config for a convention difference that is not an error, and putting it
    in the closing-day column would fill the one column that must not have noise (§11.6).

    Not coverage-gated. The bar nearest the mark is a single print, not a reconstruction of the
    session, so a sparse tape can still say where the market was at 15:00 — unlike a high or a
    low, which need the whole session to be meaningful.
    """
    prepared = _close_side_sql(ctx)
    if prepared is None:
        return []
    sql, args = prepared
    convention_ticks = float(ctx.param("close_convention_ticks", 1))
    rows = ctx.con.execute(
        f"""
        SELECT contract_id, trade_date, first_ts_utc, last_ts_utc,
               derived_close, vendor_close, tick_size, mark_close, mark_gap_minutes,
               mark_local
        FROM ({sql})
        WHERE mark_resolved AND settlement_signature
          AND abs(vendor_close - derived_close) > coalesce(tick_size, 0) * ?
        ORDER BY contract_id, trade_date
        """,
        [*args, convention_ticks],
    ).fetchall()
    return [
        _session_finding(
            ctx,
            row[:4],
            frequency="daily",
            compare_frequency="minute",
            details={
                "field": "close",
                "vendor": row[5],
                "derived": row[4],
                "difference": round(row[5] - row[4], 12),
                "tick_size": row[6],
                "close_gap_ticks": (
                    None if not row[6] else round(abs(row[5] - row[4]) / row[6], 6)
                ),
                "close_at_mark": row[7],
                "settlement_mark_local": str(row[9]),
                "mark_gap_minutes": None if row[8] is None else round(float(row[8]), 2),
                "settlement_signature": True,
                "reading": (
                    "the vendor close sits nearer the settlement mark than the session end, "
                    "which is what a settlement looks like beside a last trade"
                ),
            },
        )
        for row in rows
    ]


@rule("REC.VOLUME_SHORTFALL")
def volume_shortfall(ctx: RuleContext) -> list[Finding]:
    """The minute sum falls short of the vendor's daily volume by more than the threshold.

    `frequency = 'minute'`, because the claim is about the **tape** — which is also why §8.3
    fires in one direction only. Vendor volume legitimately exceeds the tape: block and
    privately negotiated trades are reported to the exchange without ever crossing the
    continuous market, and on roll dates much of the volume trades as calendar spreads
    (`specs/sample-corpus.md` §6.4). Excess is a statistic, not a finding.
    """
    max_shortfall = float(ctx.param("max_shortfall_pct", 0.10))
    rows = ctx.con.execute(
        f"""
        SELECT f.contract_id, f.trade_date, f.first_ts_utc, f.last_ts_utc,
               f.derived_volume, f.vendor_volume, f.coverage_pct, f.minute_records
        FROM ({session_frame_sql()}) f
        WHERE f.has_minute AND f.has_daily AND f.in_window
          AND f.vendor_volume IS NOT NULL AND f.vendor_volume > 0
          AND f.derived_volume IS NOT NULL
          AND f.derived_volume < f.vendor_volume * (1 - ?)
        ORDER BY f.contract_id, f.trade_date
        """,
        [max_shortfall],
    ).fetchall()
    return [
        _session_finding(
            ctx,
            row[:4],
            frequency="minute",
            compare_frequency="daily",
            details={
                "field": "volume",
                "minute_sum": int(row[4]),
                "vendor": int(row[5]),
                "ratio": round(float(row[4]) / float(row[5]), 6),
                "shortfall": int(row[5]) - int(row[4]),
                "max_shortfall_pct": max_shortfall,
                "minute_coverage_pct": (
                    None if row[6] is None else round(100.0 * row[6], 4)
                ),
                "minute_records": row[7],
            },
        )
        for row in rows
    ]


@rule("REC.SESSION_ONLY_IN_ONE")
def session_only_in_one(ctx: RuleContext) -> list[Finding]:
    """A session held at one granularity and not the other, inside the reconcilable window.

    Two directions, and they are not the same claim.

    A **minute session with no daily row** is the interesting one: the tape says the contract
    traded and the daily file has no settlement for it. `warning`, on the minute side, because
    that is the side making the claim.

    A **daily row with no minute session** is the deferred-contract case — a listed contract
    that publishes a settlement every day and barely trades. It drops to
    `params.absent_daily_severity` and is suppressed entirely inside a suppression window,
    where absence is already explained by the roll or by the coverage bound. Reporting it at
    warning would bury the first direction under normal market behaviour.

    Outside the reconcilable window absence at one frequency is not a finding at all (§8.5),
    which the frame's `in_window` flag decides once for every rule here.
    """
    absent_daily_severity = ctx.param("absent_daily_severity", "info")
    rows = ctx.con.execute(
        f"""
        SELECT f.contract_id, f.trade_date, f.has_minute, f.has_daily,
               f.first_ts_utc, f.last_ts_utc, f.vendor_ts_utc, f.minute_records,
               f.vendor_rows
        FROM ({session_frame_sql()}) f
        WHERE f.in_window AND (f.has_minute <> f.has_daily)
        ORDER BY f.contract_id, f.trade_date
        """
    ).fetchall()

    findings: list[Finding] = []
    for row in rows:
        contract_id, trade_date, has_minute, has_daily = row[0], row[1], row[2], row[3]
        present = "minute" if has_minute else "daily"
        absent = "daily" if has_minute else "minute"
        if has_daily:
            suppressed = ctx.inputs.suppressed(contract_id, "minute", trade_date)
            if suppressed is not None:
                continue
        ts_start = row[4] if has_minute else row[6]
        ts_end = row[5] if has_minute else row[6]
        findings.append(
            _session_finding(
                ctx,
                (contract_id, trade_date, ts_start, ts_end),
                # The side that *holds* the session is the side the finding is about (§8).
                frequency=present,
                compare_frequency=absent,
                severity=None if has_minute else absent_daily_severity,
                details={
                    "present_frequency": present,
                    "absent_frequency": absent,
                    "records": int(row[7] or 0) if has_minute else int(row[8] or 0),
                    "reading": (
                        "the tape traded this session and the daily file carries no "
                        "settlement for it"
                        if has_minute
                        else "a settlement was published for a session with no tape behind "
                        "it, which is ordinary for a deferred contract"
                    ),
                },
            )
        )
    return findings
