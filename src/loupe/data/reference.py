"""Seed `ref` from the sample corpus.

Products, ticks and sessions are seeded from measured profiles; contracts come from the
vendor manifest (`files.csv`) where it is available, and otherwise from the symbols observed
in the loaded data. The session calendar is *generated* from the product rules across the
date range actually present, so it stays inspectable and testable rather than being a
hand-maintained list.

`dates_inferred` is true for every contract in this corpus: the publisher states that exact
expiration specifications are not in the source package (`specs/sample-corpus.md` §1).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from .profiles import KNOWN_ROOTS, PRODUCTS, PRODUCTS_BY_ROOT
from .sessions import generate_calendar
from .symbols import parse_symbol

PRICE_FIELDS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class SeedSummary:
    """What a seed run wrote. Returned rather than logged, so tests can assert on it."""

    products: int
    ticks: int
    contracts: int
    calendar_rows: int


def seed_products(con: duckdb.DuckDBPyConnection) -> int:
    """Write one `ref.product` row per measured profile."""
    rows = [
        (
            p.root,
            p.description,
            p.exchange,
            p.timezone,
            p.tick_size,
            p.multiplier,
            p.cycle,
            p.session.open_local,
            p.session.close_local,
            json.dumps(
                [
                    {"start_local": s.strftime("%H:%M"), "end_local": e.strftime("%H:%M")}
                    for s, e in p.session.halt_windows
                ]
            ),
        )
        for p in PRODUCTS
    ]
    con.executemany(
        """
        INSERT OR REPLACE INTO ref.product
          (root, description, exchange, timezone, tick_size, multiplier, cycle,
           session_open_local, session_close_local, halt_windows)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def seed_ticks(con: duckdb.DuckDBPyConnection) -> int:
    """Write `ref.tick` at `(root, frequency, field)` grain.

    Same root, same nominal tick, opposite verdicts across the two configs: VX minute prices
    are 0 off-tick in 373,886 rows while VX daily `close` is off-tick in 805 of 959, because
    that column is a settlement carried to four decimals. A settlement-bearing field is
    marked `exempt` with a null tick rather than given a fake lattice.
    """
    rows: list[tuple[str, str, str, float | None, bool]] = []
    for product in PRODUCTS:
        for field in PRICE_FIELDS:
            rows.append((product.root, "minute", field, product.tick_size, False))
        for field in PRICE_FIELDS:
            settlement = field == "close" and product.daily_close_is_settlement
            rows.append(
                (
                    product.root,
                    "daily",
                    field,
                    None if settlement else product.tick_size,
                    settlement,
                )
            )
    con.executemany(
        """
        INSERT OR REPLACE INTO ref.tick (root, frequency, field, tick_size, exempt)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def _ms_to_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC).date()


def seed_contracts_from_manifest(con: duckdb.DuckDBPyConnection, manifest: Path) -> int:
    """Seed `ref.contract` from the vendor `files.csv`.

    The manifest supplies `root`, `month_code`, `delivery_year` and `delivery_month`, so the
    symbol parse is *validated* against a reference rather than trusted. Where the parse and
    the manifest disagree the manifest wins and confidence drops, which is the signal that a
    publisher has changed its symbology.
    """
    with manifest.open(newline="") as handle:
        entries = list(csv.DictReader(handle))

    merged: dict[str, dict[str, object]] = {}
    for entry in entries:
        contract_id = entry["contract_symbol"]
        parsed = parse_symbol(contract_id, KNOWN_ROOTS)
        agrees = parsed.root == entry["root"] and parsed.month_code == entry["month_code"]
        first = _ms_to_date(entry.get("first_timestamp_ms"))
        last = _ms_to_date(entry.get("last_timestamp_ms"))

        record = merged.setdefault(
            contract_id,
            {
                "root": entry["root"],
                "root_id": entry.get("root_id"),
                "month_code": entry["month_code"],
                "contract_month": date(
                    int(entry["delivery_year"]), int(entry["delivery_month"]), 1
                ),
                "exchange": entry["exchange"],
                "first": first,
                "last": last,
                "confidence": 1.0 if agrees else 0.5,
            },
        )
        # A contract has one row per frequency; take the widest observed span.
        if first and (record["first"] is None or first < record["first"]):
            record["first"] = first
        if last and (record["last"] is None or last > record["last"]):
            record["last"] = last
        record["confidence"] = min(float(record["confidence"]), 1.0 if agrees else 0.5)

    rows = []
    for contract_id, record in merged.items():
        product = PRODUCTS_BY_ROOT.get(str(record["root"]))
        rows.append(
            (
                contract_id,
                record["root"],
                record["root_id"],
                record["month_code"],
                record["contract_month"],
                record["exchange"],
                product.timezone if product else None,
                product.tick_size if product else None,
                product.multiplier if product else None,
                record["first"],
                record["last"],
                record["confidence"],
            )
        )
    con.executemany(
        """
        INSERT OR REPLACE INTO ref.contract
          (contract_id, root, root_id, month_code, contract_month, exchange, timezone,
           tick_size, multiplier, first_trade_date, last_trade_date, parse_confidence,
           dates_inferred)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
        """,
        rows,
    )
    return len(rows)


def ensure_contract(con: duckdb.DuckDBPyConnection, contract_id: str) -> None:
    """Register a contract seen at ingest that reference data does not already carry.

    Ingest reads `contract_id` straight from the source column, so a file may legitimately
    introduce a symbol the manifest never mentioned. An unparseable symbol is recorded with
    confidence 0 rather than refused: that is `STR.UNKNOWN_CONTRACT_FORMAT`, which warns and
    continues.
    """
    exists = con.execute(
        "SELECT 1 FROM ref.contract WHERE contract_id = ?", [contract_id]
    ).fetchone()
    if exists:
        return

    parsed = parse_symbol(contract_id, KNOWN_ROOTS)
    product = PRODUCTS_BY_ROOT.get(parsed.root) if parsed.root else None
    con.execute(
        """
        INSERT INTO ref.contract
          (contract_id, root, month_code, contract_month, exchange, timezone, tick_size,
           multiplier, parse_confidence, dates_inferred)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
        """,
        [
            contract_id,
            parsed.root or contract_id,
            parsed.month_code,
            parsed.contract_month,
            product.exchange if product else None,
            product.timezone if product else None,
            product.tick_size if product else None,
            product.multiplier if product else None,
            parsed.parse_confidence,
        ],
    )


def seed_calendar(
    con: duckdb.DuckDBPyConnection,
    root: str,
    start: date,
    end: date,
    *,
    pad_days: int = 5,
) -> int:
    """Generate `ref.session_calendar` for one root across a date range."""
    product = PRODUCTS_BY_ROOT.get(root)
    if product is None:
        return 0

    rows = [
        (
            row.exchange,
            row.root,
            row.trade_date,
            row.session_open_utc,
            row.session_close_utc,
            row.is_holiday,
            row.is_early_close,
            json.dumps(row.halt_windows_utc),
            row.expected_slots_1m,
        )
        for row in generate_calendar(
            root, start - timedelta(days=pad_days), end + timedelta(days=pad_days)
        )
    ]
    con.executemany(
        """
        INSERT OR REPLACE INTO ref.session_calendar
          (exchange, root, trade_date, session_open_utc, session_close_utc, is_holiday,
           is_early_close, halt_windows_utc, expected_slots_1m)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def seed_calendar_for_loaded_data(con: duckdb.DuckDBPyConnection) -> int:
    """Extend the calendar to cover every root and date range now present in `stage`."""
    spans = con.execute(
        """
        SELECT c.root, min(r.trade_date), max(r.trade_date)
        FROM stage.market_record r
        JOIN ref.contract c USING (contract_id)
        WHERE c.root IS NOT NULL
        GROUP BY c.root
        """
    ).fetchall()
    return sum(seed_calendar(con, root, start, end) for root, start, end in spans)


def seed_reference(
    con: duckdb.DuckDBPyConnection,
    *,
    manifest: Path | None = None,
) -> SeedSummary:
    """Seed everything `ref` needs before the first load.

    Without a manifest, products, ticks and an empty contract set are seeded and the calendar
    is generated later, once loaded data says which dates matter.
    """
    products = seed_products(con)
    ticks = seed_ticks(con)
    contracts = 0
    calendar_rows = 0

    if manifest and manifest.exists():
        contracts = seed_contracts_from_manifest(con, manifest)
        spans = con.execute(
            """
            SELECT root, min(first_trade_date), max(last_trade_date)
            FROM ref.contract
            WHERE root IS NOT NULL AND first_trade_date IS NOT NULL
            GROUP BY root
            """
        ).fetchall()
        calendar_rows = sum(seed_calendar(con, root, start, end) for root, start, end in spans)

    return SeedSummary(products, ticks, contracts, calendar_rows)
