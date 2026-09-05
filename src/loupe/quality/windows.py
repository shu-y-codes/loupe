"""Coverage windows: the bounds inside which absence is a defect.

The listed span is the wrong bound. ES minute volume rises by six orders of magnitude
between 120 and 90 days to expiry, and 278 of `ESZ25`'s 502 in-span weekdays carry no minute
data at all (`specs/sample-corpus.md` §7.4). Driving completeness off the listed span reports
that contract as 45% complete when nothing is missing.

So completeness is bounded by a derived **liquidity** window — the first and last session
whose volume clears a floor — falling back to `[first_trade_date, last_trade_date]` and then
to the observed span. Which one was used is recorded on every finding, because a window
chosen three different ways is three different claims.

The roll window is computed here too, and used twice: `ROL.THIN_NEAR_EXPIRY` reports it, and
the session-grained completeness rules suppress inside it. One definition, two consumers, so
the suppression cannot drift from the finding that explains it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from .registry import RECORDS

Slice = tuple[str, str]


@dataclass(frozen=True)
class CoverageWindow:
    """The dates over which a contract's data is expected to be present."""

    contract_id: str
    frequency: str
    start: date
    end: date
    basis: str  # 'liquidity' | 'listed' | 'observed'

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class RollWindow:
    """The tail of a contract's life, where volume has migrated to the next month."""

    contract_id: str
    frequency: str
    start: date
    end: date
    median_volume_inside: float
    median_volume_before: float
    expiry_basis: str  # 'listed' | 'observed'

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class RunInputs:
    """Shared inputs computed once per run and handed to every runner."""

    windows: dict[Slice, CoverageWindow]
    roll_windows: dict[Slice, RollWindow]

    def window(self, contract_id: str, frequency: str) -> CoverageWindow | None:
        return self.windows.get((contract_id, frequency))

    def suppressed(self, contract_id: str, frequency: str, day: date) -> str | None:
        """Why this session is exempt from completeness checks, or None.

        Outside the coverage window and inside the roll window are the two reasons a session
        can be absent without anything being wrong.
        """
        window = self.windows.get((contract_id, frequency))
        if window is not None and not window.contains(day):
            return f"outside the {window.basis} window"
        roll = self.roll_windows.get((contract_id, frequency))
        if roll is not None and roll.contains(day):
            return "inside the roll window (ROL.THIN_NEAR_EXPIRY)"
        return None


def resolve_windows(
    con: duckdb.DuckDBPyConnection, *, volume_floor: float
) -> dict[Slice, CoverageWindow]:
    """One coverage window per `(contract_id, frequency)` in the scoped record set."""
    rows = con.execute(
        f"""
        WITH per_session AS (
          SELECT contract_id, frequency, trade_date, sum(coalesce(volume, 0)) AS session_volume
          FROM {RECORDS}
          GROUP BY 1, 2, 3
        ),
        liquid AS (
          SELECT contract_id, frequency, min(trade_date) AS lo, max(trade_date) AS hi
          FROM per_session
          WHERE session_volume > ?
          GROUP BY 1, 2
        ),
        observed AS (
          SELECT contract_id, frequency, min(trade_date) AS lo, max(trade_date) AS hi
          FROM per_session
          GROUP BY 1, 2
        )
        SELECT o.contract_id,
               o.frequency,
               CASE WHEN l.lo IS NOT NULL THEN l.lo
                    WHEN c.first_trade_date IS NOT NULL AND c.last_trade_date IS NOT NULL
                         THEN c.first_trade_date
                    ELSE o.lo END AS start_date,
               CASE WHEN l.lo IS NOT NULL THEN l.hi
                    WHEN c.first_trade_date IS NOT NULL AND c.last_trade_date IS NOT NULL
                         THEN c.last_trade_date
                    ELSE o.hi END AS end_date,
               CASE WHEN l.lo IS NOT NULL THEN 'liquidity'
                    WHEN c.first_trade_date IS NOT NULL AND c.last_trade_date IS NOT NULL
                         THEN 'listed'
                    ELSE 'observed' END AS basis
        FROM observed o
        LEFT JOIN liquid l USING (contract_id, frequency)
        LEFT JOIN ref.contract c ON c.contract_id = o.contract_id
        """,
        [volume_floor],
    ).fetchall()
    return {
        (contract_id, frequency): CoverageWindow(
            contract_id, frequency, start, end, basis
        )
        for contract_id, frequency, start, end, basis in rows
    }


def resolve_roll_windows(
    con: duckdb.DuckDBPyConnection, *, days: int, collapse_ratio: float
) -> dict[Slice, RollWindow]:
    """The final sessions of each contract, where volume has collapsed.

    Expiry is `ref.contract.last_trade_date` where reference data has it, and the last
    observed session otherwise — dates are inferred for every contract in this corpus, so the
    basis is recorded rather than assumed. Collapse is judged on medians rather than means: a
    single large print in the tail would otherwise hide a series that has stopped trading.
    """
    rows = con.execute(
        f"""
        SELECT r.contract_id, r.frequency, r.trade_date,
               sum(coalesce(r.volume, 0)) AS session_volume,
               max(coalesce(c.last_trade_date, DATE '0001-01-01')) AS listed_expiry
        FROM {RECORDS} r
        LEFT JOIN ref.contract c ON c.contract_id = r.contract_id
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """
    ).fetchall()

    by_slice: dict[Slice, list[tuple[date, float]]] = {}
    expiry: dict[Slice, date] = {}
    for contract_id, frequency, trade_date, session_volume, listed in rows:
        key = (contract_id, frequency)
        by_slice.setdefault(key, []).append((trade_date, float(session_volume)))
        if listed and listed.year > 1:
            expiry[key] = listed

    windows: dict[Slice, RollWindow] = {}
    for (contract_id, frequency), sessions in by_slice.items():
        key = (contract_id, frequency)
        listed_expiry = expiry.get(key)
        end = listed_expiry or max(day for day, _ in sessions)
        start = end - timedelta(days=days)
        inside = [vol for day, vol in sessions if start <= day <= end]
        before = [vol for day, vol in sessions if day < start]
        if not inside or not before:
            continue
        median_inside = statistics.median(inside)
        median_before = statistics.median(before)
        if median_inside < collapse_ratio * median_before:
            windows[key] = RollWindow(
                contract_id=contract_id,
                frequency=frequency,
                start=start,
                end=end,
                median_volume_inside=median_inside,
                median_volume_before=median_before,
                expiry_basis="listed" if listed_expiry else "observed",
            )
    return windows


def missing_calendar_sessions(con: duckdb.DuckDBPyConnection) -> int:
    """Scoped sessions with no `ref.session_calendar` row.

    The calendar carries the grid, the halts and the holidays together, so its absence is the
    single check that stands for all three. A session with no calendar row is indistinguishable
    from a session that should not exist, which is why the completeness rules refuse rather
    than guess.
    """
    row = con.execute(
        f"""
        SELECT count(*)
        FROM (SELECT DISTINCT root, trade_date FROM {RECORDS} WHERE root IS NOT NULL) s
        WHERE NOT EXISTS (
          SELECT 1 FROM ref.session_calendar c
          WHERE c.root = s.root AND c.trade_date = s.trade_date
        )
        """
    ).fetchone()
    return int(row[0]) if row else 0


def unrooted_contracts(con: duckdb.DuckDBPyConnection) -> int:
    """Scoped contracts whose root could not be resolved, so no calendar can exist for them."""
    row = con.execute(
        f"SELECT count(DISTINCT contract_id) FROM {RECORDS} WHERE root IS NULL"
    ).fetchone()
    return int(row[0]) if row else 0
