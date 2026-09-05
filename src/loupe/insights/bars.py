"""Daily OHLCV bars, and the provenance that travels with them.

`open` and `close` are **positional** — the value of the earliest and latest record — while
`high` and `low` are extremal. `min(open)` and `max(close)` are the canonical bug
(`specs/analytics-semantics.md` §3.1). Ties on `ts_utc` break on `source_row`, so a bar is a
pure function of the input file.

Bars are materialised under **both** bases and for **both** sources. `basis` says whether the
quality findings were acted on; `source` says where the bar came from. A vendor daily row is a
record in `stage.market_record` like any other, so it has a raw and a clean form too — the
corpus contains 43 daily rows whose settlement close falls outside the traded range, exactly
the kind of row a cleaning policy excludes (`plans/02-quality.md`).

Vendor bars are not this aggregation and must never be tuned to match it: the vendor's close
is a settlement struck near 15:00 local, and its volume includes block and privately
negotiated trades that never crossed the tape (`specs/sample-corpus.md` §6.3, §6.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

from .gate import PublishedSeries, blocked_sessions, session_quality_sql

#: `basis` to the relation that expresses it. Raw records are immutable; the clean basis is
#: derived from the cleaning decision log (`specs/data-model.md` §4.1).
BASIS_RELATION: dict[str, str] = {
    "raw": "stage.market_record",
    "clean": "dq.market_record_clean",
}

#: `source` to the granularity it is built from, and what its `close` column means.
SOURCE_FREQUENCY: dict[str, str] = {"derived": "minute", "vendor": "daily"}
CLOSE_CONVENTION: dict[str, str] = {"derived": "last_trade", "vendor": "settlement"}

# DuckDB's arg_min / arg_max skip rows whose *value* is null, which is not the definition:
# §3.1 asks for the value of the earliest record, and that value may legitimately be null.
# Wrapping it in a struct makes the value itself non-null, so the row is considered and the
# null is returned. Verified to agree with the row_number() reference form, which the tests
# assert directly.
_FIRST = "arg_min({{'v': r.{col}}}, {{'t': r.ts_utc, 'r': r.source_row}}).v"
_LAST = "arg_max({{'v': r.{col}}}, {{'t': r.ts_utc, 'r': r.source_row}}).v"

_SEVERITY_LABEL = """
  CASE q.max_severity_rank
    WHEN 4 THEN 'critical' WHEN 3 THEN 'error'
    WHEN 2 THEN 'warning'  WHEN 1 THEN 'info' END
"""


@dataclass(frozen=True)
class BarBuildReport:
    """What one build wrote, returned rather than logged so tests can assert on it."""

    rows_by_basis_source: dict[tuple[str, str], int]

    @property
    def total(self) -> int:
        return sum(self.rows_by_basis_source.values())

    def count(self, basis: str, source: str) -> int:
        return self.rows_by_basis_source.get((basis, source), 0)


def _scope_clauses(
    contract_ids: tuple[str, ...] | None, trade_date: date | None, alias: str = "r"
) -> tuple[str, list[object]]:
    """The scope narrowing, as SQL plus its arguments. `alias=""` yields bare column names."""
    prefix = f"{alias}." if alias else ""
    clauses = ["TRUE"]
    args: list[object] = []
    if contract_ids:
        placeholders = ", ".join("?" for _ in contract_ids)
        clauses.append(f"{prefix}contract_id IN ({placeholders})")
        args.extend(contract_ids)
    if trade_date is not None:
        clauses.append(f"{prefix}trade_date = ?")
        args.append(trade_date)
    return " AND ".join(clauses), args


def build_bars(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_ids: tuple[str, ...] | None = None,
    trade_date: date | None = None,
    bases: tuple[str, ...] = ("raw", "clean"),
    sources: tuple[str, ...] = ("derived", "vendor"),
) -> BarBuildReport:
    """Materialise `mart.bar_daily` for every basis and source asked for.

    Idempotent: the rows in scope are replaced, so a rebuild after a cleaning run reflects the
    new decisions rather than doubling the table.
    """
    written: dict[tuple[str, str], int] = {}
    for basis in bases:
        if basis not in BASIS_RELATION:
            raise ValueError(f"unknown basis {basis!r}")
        for source in sources:
            if source not in SOURCE_FREQUENCY:
                raise ValueError(f"unknown source {source!r}")
            written[(basis, source)] = _build_one(
                con, basis=basis, source=source, contract_ids=contract_ids, trade_date=trade_date
            )
    return BarBuildReport(rows_by_basis_source=written)


def _build_one(
    con: duckdb.DuckDBPyConnection,
    *,
    basis: str,
    source: str,
    contract_ids: tuple[str, ...] | None,
    trade_date: date | None,
) -> int:
    relation = BASIS_RELATION[basis]
    frequency = SOURCE_FREQUENCY[source]
    where, args = _scope_clauses(contract_ids, trade_date)
    # The same narrowing without the alias, for statements that address mart.bar_daily.
    bare_where, _ = _scope_clauses(contract_ids, trade_date, alias="")

    # Sessions with no records produce no row at all: a zero-filled bar would assert a
    # session traded flat when in fact nothing arrived. `CMP.SESSION_MISSING` is what reports
    # the absence (`specs/analytics-semantics.md` §3.4).
    aggregate = f"""
      SELECT r.contract_id, r.trade_date,
             {_FIRST.format(col="open")}                                  AS open,
             max(r.high)                                                  AS high,
             min(r.low)                                                   AS low,
             {_LAST.format(col="close")}                                  AS close,
             sum(r.volume)                                                AS volume,
             arg_max(r.open_interest, {{'t': r.ts_utc, 'r': r.source_row}})
               FILTER (WHERE r.open_interest IS NOT NULL)                 AS open_interest,
             min(r.ts_utc)                                                AS first_ts_utc,
             max(r.ts_utc)                                                AS last_ts_utc,
             count(*)                                                     AS record_count,
             count(*) FILTER (WHERE r.volume IS NULL)                     AS volume_null_count
      FROM {relation} r
      WHERE r.frequency = '{frequency}' AND {where}
      GROUP BY 1, 2
    """

    sessions = f"""
      SELECT contract_id, '{frequency}' AS frequency, trade_date, first_ts_utc, last_ts_utc
      FROM ({aggregate})
    """

    # Only a derived bar has a one-minute grid behind it. One supplied daily row is not a
    # sample of 1,380 slots, so its completeness is null rather than 1/1380 or 100%.
    if source == "derived":
        expected = "sc.expected_slots_1m"
        completeness = """
          CASE WHEN sc.expected_slots_1m IS NULL OR sc.expected_slots_1m = 0 THEN NULL
               ELSE a.record_count * 100.0 / sc.expected_slots_1m END
        """
        # The resolved boundary, in the form ref.session_calendar holds it. A bare 'CME'
        # would not distinguish two bars that differ only because the boundary moved (§2.2.1).
        boundary = """
          coalesce(c.exchange, '?') || ':' || coalesce(c.root, '?') || ':' ||
          coalesce(
            strftime(sc.session_open_utc,  '%Y-%m-%dT%H:%M:%SZ') || '/' ||
            strftime(sc.session_close_utc, '%Y-%m-%dT%H:%M:%SZ'),
            'unresolved')
        """
    else:
        expected = "NULL"
        completeness = "NULL"
        # The vendor asserted this date on the 17:00 roll; Loupe did not derive it
        # (`specs/sample-corpus.md` §6.1). Recording that is the honest answer to "which
        # definition produced this bar".
        boundary = """
          coalesce(c.exchange, '?') || ':' || coalesce(c.root, '?') || ':vendor-date-column'
        """

    con.execute(
        f"""
        DELETE FROM mart.bar_daily
        WHERE basis = '{basis}' AND source = '{source}' AND {bare_where}
        """,
        args,
    )
    con.execute(
        f"""
        INSERT INTO mart.bar_daily (
          contract_id, trade_date, basis, source, source_frequency, session_boundary,
          close_convention, open, high, low, close, volume, open_interest,
          first_ts_utc, last_ts_utc, record_count, expected_count, completeness_pct,
          volume_null_count, finding_count, max_severity)
        WITH agg AS ({aggregate}),
        quality AS ({session_quality_sql(sessions)})
        SELECT
          a.contract_id, a.trade_date, '{basis}', '{source}', '{frequency}',
          {boundary}, '{CLOSE_CONVENTION[source]}',
          a.open, a.high, a.low, a.close, a.volume, a.open_interest,
          a.first_ts_utc, a.last_ts_utc, a.record_count,
          {expected}, {completeness},
          a.volume_null_count,
          coalesce(q.finding_count, 0), {_SEVERITY_LABEL}
        FROM agg a
        LEFT JOIN ref.contract c ON c.contract_id = a.contract_id
        LEFT JOIN ref.session_calendar sc
          ON sc.exchange = c.exchange AND sc.root = c.root AND sc.trade_date = a.trade_date
        LEFT JOIN quality q
          ON q.contract_id = a.contract_id AND q.trade_date = a.trade_date
        """,
        args + args,
    )
    row = con.execute(
        f"SELECT count(*) FROM mart.bar_daily "
        f"WHERE basis = ? AND source = ? AND {bare_where}",
        [basis, source, *args],
    ).fetchone()
    return int(row[0]) if row else 0


@dataclass(frozen=True)
class DailyBar:
    """One `mart.bar_daily` row, as a reader gets it back."""

    contract_id: str
    trade_date: date
    basis: str
    source: str
    source_frequency: str
    session_boundary: str | None
    close_convention: str | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    open_interest: int | None
    record_count: int
    expected_count: int | None
    completeness_pct: float | None
    volume_null_count: int
    finding_count: int
    max_severity: str | None


_BAR_COLUMNS = """
  contract_id, trade_date, basis, source, source_frequency, session_boundary,
  close_convention, open, high, low, close, volume, open_interest, record_count,
  expected_count, completeness_pct, volume_null_count, finding_count, max_severity
"""


def read_bars(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    trade_date: date | None = None,
    basis: str = "clean",
    source: str = "derived",
) -> list[DailyBar]:
    """Bars as stored, with no gate applied. `published_bars` is the publishing path."""
    clauses = ["basis = ?", "source = ?"]
    args: list[object] = [basis, source]
    if contract_id is not None:
        clauses.append("contract_id = ?")
        args.append(contract_id)
    if trade_date is not None:
        clauses.append("trade_date = ?")
        args.append(trade_date)
    rows = con.execute(
        f"SELECT {_BAR_COLUMNS} FROM mart.bar_daily WHERE {' AND '.join(clauses)}"
        " ORDER BY contract_id, trade_date",
        args,
    ).fetchall()
    return [DailyBar(*row) for row in rows]


def published_bars(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    trade_date: date | None = None,
    basis: str = "clean",
    source: str = "derived",
) -> PublishedSeries:
    """Bars with the publish gate applied: blocked sessions are withheld and named.

    A blocked session is not silently dropped. It comes back in `blocked_sessions` with the
    rule that blocked it, so the caller can say *why* the candle is missing.
    """
    frequency = SOURCE_FREQUENCY[source]
    blocked = blocked_sessions(
        con, contract_id=contract_id, frequency=frequency, trade_date=trade_date
    )
    withheld = {(q.contract_id, q.trade_date) for q in blocked}
    rows = tuple(
        bar
        for bar in read_bars(
            con, contract_id=contract_id, trade_date=trade_date, basis=basis, source=source
        )
        if (bar.contract_id, bar.trade_date) not in withheld
    )
    return PublishedSeries(rows=rows, blocked_sessions=blocked)
