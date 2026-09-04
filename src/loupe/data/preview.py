"""Inspect a file and disclose what loading it would unlock, before anything is committed.

Preview is where the ingestion *decisions* are made and shown: which vendor layout this is,
which column carries the instant we trust, what timezone the labels are in, what the bar
interval is, and which trade-date boundary will be applied. Those decisions are then
persisted on the batch, because none of them is recoverable from the loaded rows once the
wrong one has been applied.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

from .errors import MissingRequiredColumn, PreviewError, UnsupportedFileFormat
from .profiles import (
    CHICAGO,
    HF_SAMPLE_DAILY,
    HF_SAMPLE_MINUTE,
    KNOWN_ROOTS,
    PRODUCTS_BY_ROOT,
    VendorProfile,
)
from .symbols import parse_symbol

READ_CHUNK = 1 << 20

# Intervals we will name. The label is what goes on the batch; the seconds are what the
# multiple-of test uses.
RECOGNISED_INTERVALS: dict[int, tuple[str, str]] = {
    60: ("1 minute", "minute"),
    300: ("5 minutes", "minute"),
    900: ("15 minutes", "minute"),
    3600: ("1 hour", "minute"),
    86400: ("1 day", "daily"),
}

# Generic column aliases, so a hand-made CSV that follows the exercise's naming loads without
# a vendor profile. Vendor profiles take precedence when their required columns are present.
GENERIC_ALIASES: dict[str, tuple[str, ...]] = {
    "contract_id": ("contract_id", "contract", "contract_symbol", "symbol"),
    "ts": ("timestamp", "ts", "datetime", "date_time", "timestamp_chicago_wall", "date"),
    "open": ("open",),
    "high": ("high",),
    "low": ("low",),
    "close": ("close",),
    "volume": ("volume",),
    "open_interest": ("open_interest", "openinterest", "oi"),
}


@dataclass(frozen=True)
class Inference:
    """A conclusion about the file, with how it was reached.

    Recording the method is the point: `ts_utc` is derived rather than read, so a user must
    be able to see *why* we believe the labels are in a given zone.
    """

    value: str | None
    method: str
    confidence: float


@dataclass(frozen=True)
class Capability:
    available: bool
    reason: str


@dataclass(frozen=True)
class Preview:
    """Everything the user is shown before committing to a load."""

    path: Path
    filename: str
    file_format: str
    file_bytes: int
    file_hash: str
    row_count: int
    detected_columns: list[tuple[str, str]]
    contracts: list[str]
    frequency: str
    bar_interval: str
    inferred_interval: Inference
    interval_confidence: float
    source_timezone: Inference
    ts_convention: str
    session_boundary: str
    column_mapping: dict[str, object]
    unmapped_columns: list[str]
    ts_range: tuple[datetime | None, datetime | None]
    capabilities: dict[str, Capability]
    profile: VendorProfile | None = None
    already_ingested: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_duplicate(self) -> bool:
        return self.already_ingested is not None


def file_hash(path: Path) -> str:
    """sha256 of the file bytes. This is the idempotency key for ingest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def detect_format(path: Path) -> str:
    """CSV or Parquet, by magic number first and extension second.

    Gating is on file format only, never on granularity (locked decision 8).
    """
    with path.open("rb") as handle:
        if handle.read(4) == b"PAR1":
            return "parquet"
    if path.suffix.lower() in {".csv", ".txt"}:
        return "csv"
    if path.suffix.lower() == ".parquet":
        raise UnsupportedFileFormat(f"{path.name} has a .parquet suffix but no PAR1 header")
    raise UnsupportedFileFormat(
        f"{path.name}: expected a CSV or Parquet file (got suffix {path.suffix!r})"
    )


def scan_sql(file_format: str, *, all_varchar: bool) -> str:
    """The table function for a file, as a parameterised expression.

    Everything is read as text when `all_varchar` is set, because the reject path has to see
    the value that failed to parse rather than a null the reader substituted.
    """
    if file_format == "parquet":
        return "read_parquet(?)"
    # store_rejects keeps a structurally broken line from derailing the sniffer — without it
    # a single short line makes the reader decide the file has one column — and it is also
    # how the loader recovers those lines as STR.UNPARSEABLE_ROW.
    flags = "header = true, store_rejects = true"
    if all_varchar:
        flags += ", all_varchar = true"
    return f"read_csv(?, {flags})"


def _columns(con: duckdb.DuckDBPyConnection, path: Path, file_format: str) -> list[tuple[str, str]]:
    rows = con.execute(
        f"DESCRIBE SELECT * FROM {scan_sql(file_format, all_varchar=False)}", [str(path)]
    ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


def _match_profile(columns: set[str]) -> VendorProfile | None:
    for profile in (HF_SAMPLE_MINUTE, HF_SAMPLE_DAILY):
        if set(profile.required_columns) <= columns:
            return profile
    return None


def _generic_mapping(columns: list[str]) -> dict[str, str]:
    """Map source column -> target field for a file that matches no vendor profile."""
    lowered = {c.lower(): c for c in columns}
    mapping: dict[str, str] = {}
    for target, aliases in GENERIC_ALIASES.items():
        for alias in aliases:
            if alias in lowered and lowered[alias] not in mapping:
                mapping[lowered[alias]] = target
                break
    return mapping


def resolve_columns(columns: list[str]) -> tuple[VendorProfile | None, dict[str, str]]:
    """Decide which layout this is, and which source column feeds each target field.

    Returns the vendor profile (or None) and a source-column -> target-field mapping in the
    flat form the loader needs. `ts` is the single label we trust; the derived pair
    `ts_exchange` / `ts_utc` is produced from it at load time.
    """
    profile = _match_profile(set(columns))
    if profile is None:
        mapping = _generic_mapping(columns)
        missing = [
            field_name
            for field_name in ("contract_id", "ts", "open", "high", "low", "close")
            if field_name not in mapping.values()
        ]
        if missing:
            raise MissingRequiredColumn(missing, columns)
        return None, mapping

    mapping = {}
    for source, target in profile.column_mapping.items():
        if source not in columns:
            continue
        if isinstance(target, list):
            mapping[source] = "ts"
        elif target == "contract_id":
            mapping[source] = "contract_id"
        elif target == "ts_source":
            mapping[source] = "ts_source"
        elif target in {"trade_date", "ts_exchange", "ts_utc"}:
            mapping[source] = "ts"
        else:
            mapping[source] = target
    return profile, mapping


def _source_column(mapping: dict[str, str], target: str) -> str | None:
    for source, mapped in mapping.items():
        if mapped == target:
            return source
    return None


def infer_frequency(
    con: duckdb.DuckDBPyConnection, path: Path, file_format: str, ts_column: str
) -> tuple[str, Inference, float]:
    """Infer granularity and bar interval from the observed timestamps.

    The modal share of consecutive deltas is a *diagnostic*, not a gate: it reads 67.8%-91.0%
    across the eight roots in the corpus because illiquid minutes are simply absent, so a 0.8
    threshold would reject the correct one-minute inference for six of them. The acceptance
    test is that the modal delta is a recognised interval **and** every delta is an exact
    integer multiple of it, which holds at 100% for all eight roots
    (`specs/sample-corpus.md` §4.4).
    """
    scan = scan_sql(file_format, all_varchar=False)
    row = con.execute(
        f"""
        WITH src AS (
            SELECT TRY_CAST("{ts_column}" AS TIMESTAMP) AS ts
            FROM {scan} WHERE "{ts_column}" IS NOT NULL
        ),
        d AS (
            SELECT datediff('second', lag(ts) OVER (ORDER BY ts), ts) AS dsec FROM src
        ),
        nz AS (SELECT dsec FROM d WHERE dsec IS NOT NULL AND dsec > 0)
        SELECT
          (SELECT mode(dsec) FROM nz)                                        AS modal,
          (SELECT count(*) FROM nz)                                          AS n,
          (SELECT count(*) FROM nz WHERE dsec = (SELECT mode(dsec) FROM nz)) AS at_mode,
          (SELECT count(*) FROM nz
             WHERE dsec % nullif((SELECT mode(dsec) FROM nz), 0) <> 0)       AS off_grid,
          (SELECT count(*) FROM src WHERE CAST(ts AS TIME) <> TIME '00:00:00') AS intraday
        """,
        [str(path)],
    ).fetchone()

    modal, total, at_mode, off_grid, intraday = row or (None, 0, 0, 0, 0)
    modal_share = (at_mode / total) if total else 0.0

    # A single-row file has no delta to inspect; fall back to whether a time of day exists.
    if not modal:
        frequency = "minute" if intraday else "daily"
        label = "1 minute" if intraday else "1 day"
        method = "no consecutive rows; used time-of-day presence"
        return frequency, Inference(label, method, 0.3), 0.0

    known = RECOGNISED_INTERVALS.get(int(modal))
    if known and off_grid == 0:
        label, frequency = known
        method = (
            f"modal delta {int(modal)}s is a recognised interval and all {total} deltas "
            f"are exact multiples of it"
        )
        confidence = 1.0
    elif known:
        label, frequency = known
        method = (
            f"modal delta {int(modal)}s is a recognised interval but {off_grid} of {total} "
            f"deltas are not multiples of it; the file may be mixed"
        )
        confidence = 0.5
    else:
        frequency = "minute" if intraday else "daily"
        label = f"{int(modal)} seconds"
        method = f"modal delta {int(modal)}s is not a recognised interval"
        confidence = 0.2

    # Time of day is the stronger signal for granularity: a daily file has none at all.
    if not intraday:
        frequency = "daily"
    return frequency, Inference(label, method, confidence), modal_share


def infer_timezone(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    file_format: str,
    ts_column: str,
    profile: VendorProfile | None,
    frequency: str,
) -> Inference:
    """Determine the zone the labels are in, preferring a declaration over an inference.

    Preference order for this corpus: declared by the publisher in package metadata, then
    declared at upload, then inferred from the maintenance-break histogram. The trap the
    inference exists to catch is that `timestamp_ms` looks like epoch milliseconds and is not
    an instant; reading it as one shifts every record by five or six hours.
    """
    if profile is not None:
        return Inference(
            profile.source_timezone,
            f"declared by the vendor profile {profile.name}, confirmed by the "
            "maintenance-break histogram",
            1.0,
        )
    if frequency == "daily":
        return Inference(
            CHICAGO,
            "daily rows carry no time of day; the zone cannot be inferred and does not "
            "affect the session date",
            0.3,
        )

    scan = scan_sql(file_format, all_varchar=False)
    rows = con.execute(
        f"""
        SELECT hour(TRY_CAST("{ts_column}" AS TIMESTAMP)) AS hh, count(*) AS bars
        FROM {scan} GROUP BY 1 ORDER BY 1
        """,
        [str(path)],
    ).fetchall()
    seen = {int(hh): int(bars) for hh, bars in rows if hh is not None}
    empty = [hour for hour in range(24) if seen.get(hour, 0) == 0]

    if len(empty) == 1 and empty[0] == 16:
        return Inference(
            CHICAGO,
            "single empty hour at 16:00 local matches the CME maintenance break",
            0.9,
        )
    if len(empty) == 1:
        return Inference(
            CHICAGO,
            f"single empty hour at {empty[0]:02d}:00; if these are CME-family products the "
            "labels may not be Chicago wall clock",
            0.4,
        )
    return Inference(
        CHICAGO,
        "no single empty hour found; falling back to the vendor default. A smeared pair of "
        "partial dips rather than one clean hole is the fingerprint of a double conversion",
        0.2,
    )


def _capabilities(frequency: str, other_frequency_present: bool) -> dict[str, Capability]:
    """What this upload unlocks. Capability follows from input; the upload is never refused."""
    has_minute = frequency == "minute" or (frequency == "daily" and other_frequency_present)
    has_daily = frequency == "daily" or (frequency == "minute" and other_frequency_present)

    return {
        "daily_bars": Capability(
            True,
            "derived from the minute tape" if has_minute else "ingested as supplied",
        ),
        "vwap_15m": Capability(
            has_minute,
            "available"
            if has_minute
            else "unavailable: the uploaded file has no intraday rows to weight",
        ),
        "reconciliation": Capability(
            has_minute and has_daily,
            "available: both granularities are present for this contract"
            if has_minute and has_daily
            else "not possible: only one granularity is present for this contract",
        ),
    }


def preview_file(
    con: duckdb.DuckDBPyConnection, path: str | Path
) -> Preview:
    """Inspect a file and return everything the user needs before committing to a load."""
    path = Path(path)
    if not path.exists():
        raise PreviewError(f"{path} does not exist")

    file_format = detect_format(path)
    columns = _columns(con, path, file_format)
    profile, mapping = resolve_columns([name for name, _ in columns])

    ts_column = _source_column(mapping, "ts")
    contract_column = _source_column(mapping, "contract_id")
    if ts_column is None or contract_column is None:  # pragma: no cover - resolve_columns guards
        raise PreviewError(f"{path.name}: could not locate a timestamp or contract column")

    frequency, interval, modal_share = infer_frequency(con, path, file_format, ts_column)
    if profile is not None:
        frequency = profile.frequency

    timezone = infer_timezone(con, path, file_format, ts_column, profile, frequency)

    scan = scan_sql(file_format, all_varchar=False)
    row_count, first_ts, last_ts = con.execute(
        f"""
        SELECT count(*), min(TRY_CAST("{ts_column}" AS TIMESTAMP)),
               max(TRY_CAST("{ts_column}" AS TIMESTAMP))
        FROM {scan}
        """,
        [str(path)],
    ).fetchone()
    contracts = [
        r[0]
        for r in con.execute(
            f'SELECT DISTINCT "{contract_column}" FROM {scan} ORDER BY 1', [str(path)]
        ).fetchall()
        if r[0] is not None
    ]

    digest = file_hash(path)
    existing = con.execute(
        "SELECT batch_id FROM stage.ingest_batch WHERE file_hash = ?", [digest]
    ).fetchone()

    other_frequency = "daily" if frequency == "minute" else "minute"
    other_present = bool(
        contracts
        and con.execute(
            """
            SELECT 1 FROM stage.market_record
            WHERE frequency = ? AND contract_id IN (SELECT unnest(?))
            LIMIT 1
            """,
            [other_frequency, contracts],
        ).fetchone()
    )

    warnings: list[str] = []
    for contract_id in contracts:
        parsed = parse_symbol(contract_id, KNOWN_ROOTS)
        if not parsed.parsed:
            warnings.append(
                f"STR.UNKNOWN_CONTRACT_FORMAT: {contract_id!r} does not parse as a contract "
                "symbol; it will load, with no reference data attached"
            )
    if profile is None:
        warnings.append(
            "No vendor profile matched; columns were mapped by name and the timestamp "
            "convention is assumed to be interval_start."
        )

    session_boundary = _session_boundary(profile, frequency, contracts)

    return Preview(
        path=path,
        filename=path.name,
        file_format=file_format,
        file_bytes=path.stat().st_size,
        file_hash=digest,
        row_count=int(row_count or 0),
        detected_columns=columns,
        contracts=contracts,
        frequency=frequency,
        bar_interval=profile.bar_interval if profile else (interval.value or "unknown"),
        inferred_interval=interval,
        interval_confidence=modal_share,
        source_timezone=timezone,
        ts_convention=profile.ts_convention if profile else "interval_start",
        session_boundary=session_boundary,
        column_mapping=profile.mapping_document() if profile else dict(mapping),
        unmapped_columns=[
            name for name, _ in columns if name not in mapping
        ],
        ts_range=(first_ts, last_ts),
        capabilities=_capabilities(frequency, other_present),
        profile=profile,
        already_ingested=str(existing[0]) if existing else None,
        warnings=warnings,
    )


def _session_boundary(
    profile: VendorProfile | None, frequency: str, contracts: list[str]
) -> str:
    """Name the trade-date boundary that will be applied, in words a user can check.

    This is persisted because it is not recoverable from the loaded rows: a calendar-date
    boundary produces exactly the right expected slot count for a CME-family session with
    entirely the wrong membership.
    """
    if frequency == "daily":
        if profile is not None:
            return profile.session_boundary
        return "column:date (taken as the session date as supplied)"

    roots = {
        parse_symbol(c, KNOWN_ROOTS).root
        for c in contracts
        if parse_symbol(c, KNOWN_ROOTS).parsed
    }
    opens = {
        PRODUCTS_BY_ROOT[root].session.open_local.strftime("%H:%M")
        for root in roots
        if root in PRODUCTS_BY_ROOT
    }
    if len(opens) == 1:
        return f"session_close {opens.pop()} {CHICAGO}"
    if opens:
        return f"session_close per root ({', '.join(sorted(opens))}) {CHICAGO}"
    return f"session_close 17:00 {CHICAGO} (no product profile; CME-family assumed)"
