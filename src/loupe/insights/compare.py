"""Raw against clean — the comparison that makes cleaning visible.

VWAP is volume-weighted, so a single fat-finger print with meaningful volume corrupts the
line for a full fifteen minutes (`specs/analytics-semantics.md` §4.9). Computing both bases
and overlaying them is what turns "we cleaned your data" into a number the analyst can see.

On this corpus the two bases often agree on the minute tape: slice 2 measured that every one
of the 43 excluded records is a vendor **daily** row, and no minute record is excluded at all
(`plans/02-quality.md`). A flat comparison here is a true statement about the sample, not a
broken helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import duckdb

from .bars import DailyBar, read_bars
from .vwap import vwap_15m


@dataclass(frozen=True)
class VwapDelta:
    """One timestamp, both bases, and the difference between them."""

    contract_id: str
    trade_date: date
    ts_utc: datetime
    raw_vwap: float | None
    clean_vwap: float | None

    @property
    def delta(self) -> float | None:
        """`None` where either side is undefined — a break in one line is not a difference."""
        if self.raw_vwap is None or self.clean_vwap is None:
            return None
        return self.clean_vwap - self.raw_vwap

    @property
    def differs(self) -> bool:
        return self.delta is not None and self.delta != 0.0


@dataclass(frozen=True)
class BarDelta:
    """One session's bar under both bases. Either side may be absent."""

    contract_id: str
    trade_date: date
    raw: DailyBar | None
    clean: DailyBar | None

    @property
    def differs(self) -> bool:
        if self.raw is None or self.clean is None:
            return True
        return (self.raw.open, self.raw.high, self.raw.low, self.raw.close, self.raw.volume) != (
            self.clean.open,
            self.clean.high,
            self.clean.low,
            self.clean.close,
            self.clean.volume,
        )


def compare_vwap(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    trade_date: date | None = None,
    price_basis: str = "typical",
) -> list[VwapDelta]:
    """The two lines aligned on timestamp. A point present in one basis only still appears."""
    raw = {
        (p.contract_id, p.trade_date, p.ts_utc): p.vwap_15m
        for p in vwap_15m(
            con,
            contract_id=contract_id,
            trade_date=trade_date,
            basis="raw",
            price_basis=price_basis,
        )
    }
    clean = {
        (p.contract_id, p.trade_date, p.ts_utc): p.vwap_15m
        for p in vwap_15m(
            con,
            contract_id=contract_id,
            trade_date=trade_date,
            basis="clean",
            price_basis=price_basis,
        )
    }
    return [
        VwapDelta(
            contract_id=key[0],
            trade_date=key[1],
            ts_utc=key[2],
            raw_vwap=raw.get(key),
            clean_vwap=clean.get(key),
        )
        for key in sorted(set(raw) | set(clean))
    ]


def compare_bars(
    con: duckdb.DuckDBPyConnection,
    *,
    contract_id: str | None = None,
    trade_date: date | None = None,
    source: str = "derived",
) -> list[BarDelta]:
    """Each session's bar under both bases, including sessions that exist in only one."""
    raw = {
        (b.contract_id, b.trade_date): b
        for b in read_bars(
            con, contract_id=contract_id, trade_date=trade_date, basis="raw", source=source
        )
    }
    clean = {
        (b.contract_id, b.trade_date): b
        for b in read_bars(
            con, contract_id=contract_id, trade_date=trade_date, basis="clean", source=source
        )
    }
    return [
        BarDelta(contract_id=key[0], trade_date=key[1], raw=raw.get(key), clean=clean.get(key))
        for key in sorted(set(raw) | set(clean))
    ]
