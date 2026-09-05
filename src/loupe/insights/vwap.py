"""Rolling 15-minute VWAP.

Four decisions, locked by `specs/analytics-semantics.md` §4 and not re-litigated here:

**A trailing time window, not a row count.** `ROWS BETWEEN 14 PRECEDING` takes the last 15
*records*, which on a series with missing minutes silently stretches the window over the gap —
wrong precisely where the data is worst. `RANGE BETWEEN INTERVAL 15 MINUTES PRECEDING` is
inclusive at both ends, so a record exactly fifteen minutes old is still in the window.

**Partitioned by `(contract_id, trade_date)`.** Never across contracts, and never across
sessions: without `trade_date` the first morning window reaches back through the maintenance
break and mixes in stale pre-break prices.

**A zero denominator is NULL.** `nullif` makes it so, and the chart shows a break in the line.
Returning 0, carrying the previous value forward, or interpolating would all be the
application lying about data it does not have.

**Warm-up is marked, not hidden.** The first fifteen minutes of a session have an incomplete
window; the value is computed anyway and flagged, because nulling it loses information while
presenting it unmarked overstates confidence.

`mart.vwap_15m` is the shipped default (typical price, clean basis). This module is the same
window with the basis and price basis as parameters, so raw and clean can be overlaid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import duckdb

from .bars import BASIS_RELATION
from .gate import PublishedSeries, blocked_sessions, capability_gap

#: `price_basis` to the expression it means. Typical price is the default for bar data: using
#: `close` alone discards the intra-bar range and is more sensitive to a single bad print.
PRICE_BASIS_SQL: dict[str, str] = {
    "typical": "(high + low + close) / 3.0",
    "close": "close",
}

WINDOW_MINUTES = 15


@dataclass(frozen=True)
class VwapPoint:
    """One output record. There is one per input record — a continuously updating line."""

    contract_id: str
    trade_date: date
    ts_utc: datetime
    vwap_15m: float | None
    window_volume: int | None
    window_records: int
    is_warmup: bool


def vwap_sql(basis: str, price_basis: str, *, where: str = "TRUE") -> str:
    """The window, against one basis and one price basis.

    Both parameters are looked up rather than interpolated: they reach this layer from an API
    query string (slice 4), and a lookup is what keeps that from being a SQL injection.
    """
    if basis not in BASIS_RELATION:
        raise ValueError(f"unknown basis {basis!r}")
    if price_basis not in PRICE_BASIS_SQL:
        raise ValueError(f"unknown price_basis {price_basis!r}")
    return f"""
    SELECT
      contract_id,
      trade_date,
      ts_utc,
      sum(px * volume) OVER w / nullif(sum(volume) OVER w, 0) AS vwap_15m,
      sum(volume)      OVER w                                 AS window_volume,
      count(*)         OVER w                                 AS window_records,
      ts_utc - first_value(ts_utc) OVER (
          PARTITION BY contract_id, trade_date ORDER BY ts_utc
      ) < INTERVAL {WINDOW_MINUTES} MINUTES                   AS is_warmup
    FROM (
      SELECT *, {PRICE_BASIS_SQL[price_basis]} AS px
      FROM {BASIS_RELATION[basis]}
      WHERE frequency = 'minute'
        AND high IS NOT NULL AND low IS NOT NULL
        AND close IS NOT NULL AND volume IS NOT NULL
        AND {where}
    )
    WINDOW w AS (
      PARTITION BY contract_id, trade_date
      ORDER BY ts_utc
      RANGE BETWEEN INTERVAL {WINDOW_MINUTES} MINUTES PRECEDING AND CURRENT ROW
    )
    ORDER BY contract_id, trade_date, ts_utc
    """


def vwap_15m(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    trade_date: date | None = None,
    basis: str = "clean",
    price_basis: str = "typical",
) -> list[VwapPoint]:
    """The rolling line for one contract, or for everything in the store.

    Reads intraday records only. A daily-only corpus yields an empty list, which the API
    reports as *unavailable* rather than as an empty series (`specs/data-model.md` §5).
    """
    clauses = ["TRUE"]
    args: list[object] = []
    if contract_id is not None:
        clauses.append("contract_id = ?")
        args.append(contract_id)
    if trade_date is not None:
        clauses.append("trade_date = ?")
        args.append(trade_date)

    rows = con.execute(vwap_sql(basis, price_basis, where=" AND ".join(clauses)), args).fetchall()
    return [
        VwapPoint(
            contract_id=row[0],
            trade_date=row[1],
            ts_utc=row[2],
            vwap_15m=row[3],
            window_volume=int(row[4]) if row[4] is not None else None,
            window_records=int(row[5]),
            is_warmup=bool(row[6]),
        )
        for row in rows
    ]


def published_vwap(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    trade_date: date | None = None,
    basis: str = "clean",
    price_basis: str = "typical",
) -> PublishedSeries:
    """The rolling line with the publish gate applied.

    Blocked sessions are withheld and named rather than dropped: a misread timezone moves
    every session boundary, so a VWAP computed over it is wrong in a way no per-point check
    would notice.

    A daily-only contract gets a refusal, not an empty line. The check belongs here rather
    than in the caller: `insights` owns what may be published, and a handler that asked the
    store which frequencies a contract holds would have taken that decision away from it
    (`plans/04-api.md` done-when 7).
    """
    gap = capability_gap(con, requested_frequency="minute", contract_id=contract_id)
    if gap is not None:
        return PublishedSeries(unsupported=gap)

    blocked = blocked_sessions(
        con, contract_id=contract_id, frequency="minute", trade_date=trade_date
    )
    withheld = {(q.contract_id, q.trade_date) for q in blocked}
    points = tuple(
        point
        for point in vwap_15m(
            con,
            contract_id=contract_id,
            trade_date=trade_date,
            basis=basis,
            price_basis=price_basis,
        )
        if (point.contract_id, point.trade_date) not in withheld
    )
    return PublishedSeries(rows=points, blocked_sessions=blocked)
