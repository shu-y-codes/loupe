"""Which findings touch a session, and whether that session may be published.

One resolver, two callers. `mart.bar_daily.finding_count` / `max_severity` and the publish
gate ask the same question — which findings intersect this slice — and must not answer it
differently: a bar reading `max_severity = 'warning'` while the gate refuses to publish it is
a contradiction the UI cannot render (`specs/analytics-semantics.md` §3.3).

**Count narrow, escalate wide.** A `series`- or `file`-scope finding is one statement about
many sessions. Adding it to every bar's `finding_count` shifts a whole trend by a constant and
says nothing about which session is worse, so it is not counted — but it still raises
`max_severity`, because a bar sitting inside a broken series is not trustworthy just because
the breakage was described once. `TIM.TIMEZONE_MISALIGNED` is the case that settles it: the
only non-record `critical` in the catalogue is `file`-scope, so a gate that ignored file scope
could never fire on the one rule slice 2 built for it (`plans/02-quality.md` done-when 11).

`basis` identifies the bar being published; it does not filter findings. Whether a defect was
acted on is what `basis` means, not whether it happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

#: Ordering for `max_severity`. `dq.dq_finding.severity` is a string, and "worst" has to mean
#: something before a bar can carry it.
SEVERITY_RANK: dict[str, int] = {"info": 1, "warning": 2, "error": 3, "critical": 4}

#: The severity that blocks publication (`specs/dq-rules-and-scoring.md` §1).
BLOCKING_SEVERITY = "critical"

#: Scopes whose findings are *about* one session, and so are counted on its bar.
COUNTED_SCOPES = ("record", "session")

#: A finding is live until someone dispositions it. An accepted or overridden finding has been
#: looked at and judged; it no longer blocks.
OPEN_STATUS = "open"

# The intersection rule, per `dq.dq_rule.scope`. Fields the finding leaves null are wildcards:
# a rule that names no contract is about every contract in its span.
#
#   record / session : contract, frequency and trade_date must match.
#   series           : contract and frequency match; trade_date is ignored, because the claim
#                      is about the whole series even though the finding is stamped on one
#                      session of it (`ROL.NO_SUCCESSOR` carries the last trade date).
#   file             : the finding's timestamp span overlaps the session's own span. The spec
#                      writes this as "the batch contributed a record to that session";
#                      `dq.dq_finding` carries no `batch_id`, and `details` is evidence and
#                      never grouped on (`specs/data-model.md` §4), so the span is the join.
_INTERSECTS = """
      (f.contract_id IS NULL OR f.contract_id = s.contract_id)
  AND (f.frequency   IS NULL OR f.frequency   = s.frequency)
  AND CASE f.scope
        WHEN 'series' THEN TRUE
        WHEN 'file'   THEN f.ts_start_utc IS NULL
                        OR (f.ts_start_utc <= s.last_ts_utc
                            AND f.ts_end_utc >= s.first_ts_utc)
        ELSE f.trade_date IS NULL OR f.trade_date = s.trade_date
      END
"""


def session_quality_sql(sessions: str) -> str:
    """SQL summarising the findings that intersect each session in `sessions`.

    `sessions` is any relation with `(contract_id, frequency, trade_date, first_ts_utc,
    last_ts_utc)`. Returned as SQL rather than as rows so the bar writer can join it in the
    same statement that aggregates the bar, and still be running the one resolver.
    """
    counted = ", ".join(f"'{scope}'" for scope in COUNTED_SCOPES)
    return f"""
    WITH sess AS ({sessions}),
    open_findings AS (
      SELECT f.finding_id, f.rule_id, f.contract_id, f.frequency, f.trade_date,
             f.ts_start_utc, f.ts_end_utc, f.severity, r.scope
      FROM dq.dq_finding f
      JOIN dq.dq_rule r USING (rule_id)
      WHERE f.status = '{OPEN_STATUS}'
    ),
    matched AS (
      SELECT s.contract_id, s.frequency, s.trade_date,
             f.rule_id, f.severity, f.scope
      FROM sess s
      JOIN open_findings f ON {_INTERSECTS}
    )
    SELECT
      s.contract_id,
      s.frequency,
      s.trade_date,
      count(m.rule_id) FILTER (WHERE m.scope IN ({counted}))          AS finding_count,
      max(CASE m.severity
            WHEN 'critical' THEN 4 WHEN 'error' THEN 3
            WHEN 'warning'  THEN 2 WHEN 'info'  THEN 1 END)           AS max_severity_rank,
      count(m.rule_id) FILTER (WHERE m.severity = '{BLOCKING_SEVERITY}') AS blocking_count,
      list(DISTINCT m.rule_id) FILTER (WHERE m.severity = '{BLOCKING_SEVERITY}')
                                                                      AS blocking_rule_ids
    FROM sess s
    LEFT JOIN matched m
      ON  m.contract_id = s.contract_id
      AND m.frequency   = s.frequency
      AND m.trade_date  = s.trade_date
    GROUP BY 1, 2, 3
    """


#: Every session that has records, as the resolver's default input.
RECORD_SESSIONS = """
    SELECT contract_id, frequency, trade_date,
           min(ts_utc) AS first_ts_utc, max(ts_utc) AS last_ts_utc
    FROM stage.market_record
    GROUP BY 1, 2, 3
"""


@dataclass(frozen=True)
class SessionQuality:
    """The quality of one `(contract, frequency, session)`, as a bar carries it."""

    contract_id: str
    frequency: str
    trade_date: date
    finding_count: int
    max_severity: str | None
    blocking_rule_ids: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        """An open `critical` finding intersects this session, so nothing may be published."""
        return bool(self.blocking_rule_ids)


def _severity_from_rank(rank: int | None) -> str | None:
    if rank is None:
        return None
    for name, value in SEVERITY_RANK.items():
        if value == rank:
            return name
    raise ValueError(f"unknown severity rank {rank!r}")


def session_quality(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    frequency: str | None = None,
    trade_date: date | None = None,
) -> dict[tuple[str, str, date], SessionQuality]:
    """Resolve every session's findings, keyed by `(contract_id, frequency, trade_date)`."""
    clauses = ["TRUE"]
    args: list[object] = []
    if contract_id is not None:
        clauses.append("contract_id = ?")
        args.append(contract_id)
    if frequency is not None:
        clauses.append("frequency = ?")
        args.append(frequency)
    if trade_date is not None:
        clauses.append("trade_date = ?")
        args.append(trade_date)

    sessions = f"""
        SELECT contract_id, frequency, trade_date,
               min(ts_utc) AS first_ts_utc, max(ts_utc) AS last_ts_utc
        FROM stage.market_record
        WHERE {" AND ".join(clauses)}
        GROUP BY 1, 2, 3
    """
    rows = con.execute(session_quality_sql(sessions), args).fetchall()
    return {
        (row[0], row[1], row[2]): SessionQuality(
            contract_id=row[0],
            frequency=row[1],
            trade_date=row[2],
            finding_count=int(row[3] or 0),
            max_severity=_severity_from_rank(row[4]),
            blocking_rule_ids=tuple(sorted(row[6] or ())),
        )
        for row in rows
    }


@dataclass(frozen=True)
class PublishedSeries:
    """Analytics for a slice, and the reason any of it is missing.

    Three states, and the caller must be able to tell them apart. `rows` present is the
    ordinary case. `blocked_sessions` non-empty means a `critical` finding blocked the slice —
    the series is withheld, not absent. Both empty means there is genuinely nothing there.
    An empty list would collapse the last two into "no data", which is the failure this type
    exists to prevent (`plans/03-insights.md` done-when 9).
    """

    rows: tuple = ()
    blocked_sessions: tuple[SessionQuality, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_sessions)

    @property
    def unavailable(self) -> bool:
        """Nothing to publish and nothing blocking it — the slice simply has no data."""
        return not self.rows and not self.blocked_sessions

    @property
    def blocking_rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted({rid for s in self.blocked_sessions for rid in s.blocking_rule_ids}))


def blocked_sessions(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    frequency: str | None = None,
    trade_date: date | None = None,
) -> tuple[SessionQuality, ...]:
    """The sessions in scope that an open `critical` finding blocks from publication."""
    resolved = session_quality(
        con, contract_id=contract_id, frequency=frequency, trade_date=trade_date
    )
    return tuple(
        sorted(
            (q for q in resolved.values() if q.blocked),
            key=lambda q: (q.contract_id, q.frequency, q.trade_date),
        )
    )
