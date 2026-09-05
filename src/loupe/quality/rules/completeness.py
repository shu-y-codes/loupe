"""Completeness — `CMP.*`. Is anything missing?

Suppressions are a **precondition** of this family, not a refinement (spec §3). Every
session-grained rule here is bounded by the coverage window, skips holidays and early
closes, skips halted minutes, and skips the roll window. Without those, `CMP.SESSION_MISSING`
alone emits 278 `error` findings for one contract describing entirely normal deferred-contract
behaviour (`specs/sample-corpus.md` §7.4).

When the calendar is unavailable these rules **refuse to evaluate**. A session with no
calendar row looks exactly like a session that is missing, and reporting the second when the
truth is the first is worse than reporting nothing.
"""

from __future__ import annotations

from typing import Any

from ..registry import RECORDS, Finding, RuleContext, RuleRefusal, rule
from ..windows import missing_calendar_sessions, unrooted_contracts

# The grid, the halts and the holidays arrive together on `ref.session_calendar`, and the
# halt expansion is identical in every rule that needs it.
HALTS_CTE = """
halts AS (
  SELECT c.root, c.trade_date, h.start_utc, h.end_utc
  FROM ref.session_calendar c,
       unnest(json_transform(c.halt_windows_utc,
              '[{"start_utc":"TIMESTAMPTZ","end_utc":"TIMESTAMPTZ"}]')) AS t(h)
)
"""

OHLCV_FIELDS = ("open", "high", "low", "close", "volume")


def _fields(ctx: RuleContext, allowed: tuple[str, ...]) -> list[str]:
    """The field list from the seeded params, checked against the columns that exist.

    Params are data, and data reaches SQL by name here rather than by value, so the whitelist
    is the thing standing between a mistyped param and a broken query.
    """
    names = list(ctx.param("fields", list(allowed)))
    unknown = [name for name in names if name not in allowed]
    if unknown:
        raise ValueError(f"{ctx.rule.rule_id}: params.fields names unknown columns {unknown}")
    return names


def require_calendar(ctx: RuleContext) -> None:
    """Refuse unless every scoped session has calendar, halt and holiday inputs."""
    unrooted = unrooted_contracts(ctx.con)
    if unrooted:
        raise RuleRefusal(
            f"{unrooted} scoped contract(s) have no resolved root, so no session calendar "
            "can exist for them"
        )
    missing = missing_calendar_sessions(ctx.con)
    if missing:
        raise RuleRefusal(
            f"{missing} scoped session(s) have no ref.session_calendar row; calendar, halt "
            "and holiday inputs are unavailable"
        )


def _window_details(basis: str, **extra: Any) -> dict[str, Any]:
    """Every completeness finding records which window bounded it (plan done-when 5)."""
    return {"window_basis": basis, **extra}


@rule("CMP.NULL_FIELD")
def null_field(ctx: RuleContext) -> list[Finding]:
    """Any of open/high/low/close/volume is null, one finding per field per record.

    An empty cell parses, so ingest loads it and this rule reports it. A non-numeric string
    does not parse and is a `STR.*` reject instead — conflating the two makes the null case
    unreportable (spec §2).
    """
    fields = _fields(ctx, OHLCV_FIELDS)
    names = ", ".join(f"'{name}'" for name in fields)
    tests = ", ".join(f"r.{name} IS NULL" for name in fields)
    rows = ctx.con.execute(
        f"""
        SELECT record_id, contract_id, frequency, trade_date, ts_utc, field
        FROM (
          SELECT r.record_id, r.contract_id, r.frequency, r.trade_date, r.ts_utc,
                 unnest([{names}]) AS field,
                 unnest([{tests}]) AS is_null
          FROM {RECORDS} r
          WHERE {ctx.frequency_filter()}
        )
        WHERE is_null
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
            details={"field": field},
        )
        for record_id, contract_id, frequency, trade_date, ts_utc, field in rows
    ]


@rule("CMP.SESSION_MISSING")
def session_missing(ctx: RuleContext) -> list[Finding]:
    """A non-holiday session inside the coverage window with no records at all.

    `affected_rows` is the number of records the session should have held — the calendar's
    slot count at minute granularity, one at daily — rather than "one session". That is what
    the score's dry-run adds back, and what puts an absent session in the same units as a gap
    inside a session on the worklist.
    """
    require_calendar(ctx)
    rows = ctx.con.execute(
        f"""
        WITH slices AS (
          SELECT DISTINCT r.contract_id, r.frequency, r.root
          FROM {RECORDS} r
          WHERE r.root IS NOT NULL AND {ctx.frequency_filter()}
        ),
        expected AS (
          SELECT s.contract_id, s.frequency, c.trade_date, w.basis,
                 CASE WHEN s.frequency = 'minute' THEN c.expected_slots_1m ELSE 1 END
                   AS expected_records
          FROM slices s
          JOIN dq_scope_windows w
            ON w.contract_id = s.contract_id AND w.frequency = s.frequency
          JOIN ref.session_calendar c
            ON c.root = s.root AND c.trade_date BETWEEN w.start_date AND w.end_date
          WHERE NOT c.is_holiday
            AND (w.roll_start IS NULL
                 OR c.trade_date NOT BETWEEN w.roll_start AND w.roll_end)
        )
        SELECT e.contract_id, e.frequency, e.trade_date, e.basis,
               coalesce(e.expected_records, 0) AS expected_records
        FROM expected e
        WHERE NOT EXISTS (
          SELECT 1 FROM {RECORDS} r
          WHERE r.contract_id = e.contract_id
            AND r.frequency = e.frequency
            AND r.trade_date = e.trade_date
        )
        ORDER BY 1, 2, 3
        """
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            affected_rows=int(expected),
            details=_window_details(basis, expected_records=int(expected)),
        )
        for contract_id, frequency, trade_date, basis, expected in rows
    ]


@rule("CMP.MISSING_TIMESTAMP")
def missing_timestamp(ctx: RuleContext) -> list[Finding]:
    """Contiguous runs of expected grid slots with no record — one finding per run.

    A run rather than a slot is the whole point: a session that lost its afternoon is one
    finding with `affected_rows = 240`, not 240 findings. Early closes are skipped because
    their truncated grid is unknown (`expected_slots_1m` is null, which is the honest way to
    say the denominator is not known rather than zero).
    """
    require_calendar(ctx)
    min_run = int(ctx.param("min_run_slots", 1))
    rows = ctx.con.execute(
        f"""
        WITH {HALTS_CTE},
        sessions AS (
          SELECT DISTINCT r.contract_id, r.frequency, r.root, r.trade_date
          FROM {RECORDS} r
          WHERE r.root IS NOT NULL AND {ctx.frequency_filter()}
        ),
        cal AS (
          SELECT s.contract_id, s.frequency, s.root, s.trade_date,
                 c.session_open_utc, c.session_close_utc
          FROM sessions s
          JOIN dq_scope_windows w
            ON w.contract_id = s.contract_id AND w.frequency = s.frequency
          JOIN ref.session_calendar c
            ON c.root = s.root AND c.trade_date = s.trade_date
          WHERE NOT c.is_holiday
            AND NOT c.is_early_close
            AND c.expected_slots_1m IS NOT NULL
            AND c.session_open_utc IS NOT NULL
            AND s.trade_date BETWEEN w.start_date AND w.end_date
            AND (w.roll_start IS NULL
                 OR s.trade_date NOT BETWEEN w.roll_start AND w.roll_end)
        ),
        slots AS (
          SELECT contract_id, frequency, root, trade_date,
                 unnest(generate_series(session_open_utc,
                                        session_close_utc - INTERVAL 1 MINUTE,
                                        INTERVAL 1 MINUTE)) AS slot
          FROM cal
        ),
        open_slots AS (
          SELECT s.* FROM slots s
          WHERE NOT EXISTS (
            SELECT 1 FROM halts h
            WHERE h.root = s.root AND h.trade_date = s.trade_date
              AND s.slot >= h.start_utc AND s.slot < h.end_utc
          )
        ),
        present AS (
          SELECT DISTINCT contract_id, frequency, trade_date,
                 date_trunc('minute', ts_utc) AS slot
          FROM {RECORDS} r
          WHERE {ctx.frequency_filter()}
        ),
        numbered AS (
          SELECT o.contract_id, o.frequency, o.trade_date, o.slot,
                 row_number() OVER (PARTITION BY o.contract_id, o.frequency, o.trade_date
                                    ORDER BY o.slot) AS slot_no,
                 p.slot IS NULL AS is_missing
          FROM open_slots o
          LEFT JOIN present p
            ON p.contract_id = o.contract_id AND p.frequency = o.frequency
           AND p.trade_date = o.trade_date AND p.slot = o.slot
        ),
        islands AS (
          SELECT contract_id, frequency, trade_date, slot,
                 slot_no - row_number() OVER (PARTITION BY contract_id, frequency, trade_date
                                              ORDER BY slot_no) AS island
          FROM numbered
          WHERE is_missing
        )
        SELECT contract_id, frequency, trade_date,
               min(slot) AS first_missing, max(slot) AS last_missing, count(*) AS slots
        FROM islands
        GROUP BY contract_id, frequency, trade_date, island
        HAVING count(*) >= ?
        ORDER BY 1, 2, 3, 4
        """,
        [min_run],
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            ts_start_utc=first_missing,
            ts_end_utc=last_missing,
            affected_rows=int(slots),
            details={"missing_slots": int(slots)},
        )
        for contract_id, frequency, trade_date, first_missing, last_missing, slots in rows
    ]


@rule("CMP.PARTIAL_SESSION")
def partial_session(ctx: RuleContext) -> list[Finding]:
    """Session completeness below the threshold share of the calendar's expected slots."""
    require_calendar(ctx)
    threshold = float(ctx.param("threshold", 0.95))
    rows = ctx.con.execute(
        f"""
        WITH present AS (
          SELECT r.contract_id, r.frequency, r.root, r.trade_date,
                 count(DISTINCT date_trunc('minute', r.ts_utc)) AS slots
          FROM {RECORDS} r
          WHERE r.root IS NOT NULL AND {ctx.frequency_filter()}
          GROUP BY 1, 2, 3, 4
        )
        SELECT p.contract_id, p.frequency, p.trade_date, p.slots, c.expected_slots_1m,
               w.basis
        FROM present p
        JOIN dq_scope_windows w
          ON w.contract_id = p.contract_id AND w.frequency = p.frequency
        JOIN ref.session_calendar c
          ON c.root = p.root AND c.trade_date = p.trade_date
        WHERE NOT c.is_holiday
          AND NOT c.is_early_close
          AND c.expected_slots_1m IS NOT NULL
          AND c.expected_slots_1m > 0
          AND p.trade_date BETWEEN w.start_date AND w.end_date
          AND (w.roll_start IS NULL
               OR p.trade_date NOT BETWEEN w.roll_start AND w.roll_end)
          AND CAST(p.slots AS DOUBLE) / c.expected_slots_1m < ?
        ORDER BY 1, 2, 3
        """,
        [threshold],
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=trade_date,
            affected_rows=int(expected - slots),
            details=_window_details(
                basis,
                completeness_pct=round(slots / expected, 6),
                threshold=threshold,
                actual_slots=int(slots),
                expected_slots=int(expected),
            ),
        )
        for contract_id, frequency, trade_date, slots, expected, basis in rows
    ]


@rule("CMP.SPARSE_SERIES")
def sparse_series(ctx: RuleContext) -> list[Finding]:
    """The contract carries too few sessions to say much about it. Informational only."""
    min_sessions = int(ctx.param("min_sessions", 20))
    rows = ctx.con.execute(
        f"""
        SELECT contract_id, frequency, count(DISTINCT trade_date) AS sessions,
               min(trade_date) AS first_session, max(trade_date) AS last_session
        FROM {RECORDS} r
        WHERE {ctx.frequency_filter()}
        GROUP BY 1, 2
        HAVING count(DISTINCT trade_date) < ?
        ORDER BY 1, 2
        """,
        [min_sessions],
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=last_session,
            affected_rows=int(sessions),
            details={
                "sessions": int(sessions),
                "min_sessions": min_sessions,
                "first_session": str(first_session),
                "last_session": str(last_session),
            },
        )
        for contract_id, frequency, sessions, first_session, last_session in rows
    ]
