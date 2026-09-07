"""Synchronous ingest.

Load is a single request that returns a finished result (locked decision 7). It writes one
`stage.ingest_batch` row carrying every ingestion decision, appends records to
`stage.market_record`, and routes rows that cannot be *parsed* to `stage.record_reject`.

The line between the two tables is deliberate and load-bearing: **a null price is a quality
finding, not a load failure.** Only rows that cannot be parsed are rejected. If the loader
dropped nulls, the user could never see them, and "detect missing values" would be
impossible to demonstrate.

Everything is read as text and cast with `TRY_CAST`, for both formats. That costs a
conversion the Parquet path does not strictly need, and it buys one reject path instead of
two — the reject row has to show the value that failed to parse, not the null the reader
would have substituted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

from .errors import DuplicateFileError
from .preview import Preview, preview_file, scan_sql
from .profiles import KNOWN_ROOTS, PRODUCTS_BY_ROOT
from .reference import ensure_contract, seed_calendar
from .sessions import roll_sql
from .symbols import parse_symbol

PRICE_TARGETS = ("open", "high", "low", "close")
DEFAULT_SESSION_OPEN = "17:00:00"

# `stage.market_record.volume` is a BIGINT because volume is a count of contracts, and DuckDB
# casts '10.5' to 11 rather than refusing it — so a fractional volume loads and its fraction is
# gone before any rule could see it. It is also not STR.NON_NUMERIC_VOLUME: that code is for a
# value that is not a number at all, and rejecting the row would lose its OHLC too. The verbatim
# label is kept only when it does not parse as an integer, which is null for every clean row and
# is what VAL.NON_INTEGER_VOLUME reads (`specs/data-model.md` §3.1).
_FRACTIONAL_VOLUME = """
  CASE WHEN TRY_CAST(volume_txt AS DOUBLE) IS NOT NULL
        AND TRY_CAST(volume_txt AS DOUBLE)
            <> floor(TRY_CAST(volume_txt AS DOUBLE))
       THEN volume_txt END
"""


@dataclass(frozen=True)
class LoadResult:
    """The finished summary a synchronous ingest returns."""

    batch_id: str
    filename: str
    file_hash: str
    frequency: str
    status: str
    rows_read: int
    rows_accepted: int
    rows_rejected: int
    contracts: list[str]
    trade_date_range: tuple[date | None, date | None]
    elapsed_seconds: float
    reject_reasons: dict[str, int]


def load_file(
    con: duckdb.DuckDBPyConnection,
    path: str | Path,
    *,
    preview: Preview | None = None,
    origin: str = "upload",
) -> LoadResult:
    """Ingest one file. Raises `DuplicateFileError` when these bytes are already loaded.

    `origin` records where the batch came from — an ordinary `upload`, the `demo` corpus, or
    `injected` demo defects. It is a declaration by the caller and changes nothing about how
    the file is read; it exists so that a manufactured defect can never be mistaken for a
    vendor one downstream, which is the whole point of labelling the injection at all.
    """
    path = Path(path)
    preview = preview or preview_file(con, path)

    if preview.already_ingested is not None:
        raise DuplicateFileError(preview.file_hash, preview.already_ingested, preview.filename)

    started = datetime.now()
    batch_id = _open_batch(con, preview, origin=origin)

    try:
        _clear_reject_log(con)
        accepted, structural = _insert_records(con, preview, batch_id)
        parse_rejects = _insert_parse_rejects(con, preview, batch_id)
        structural_rejects = _insert_structural_rejects(con, batch_id, structural)
    except Exception:
        con.execute(
            "UPDATE stage.ingest_batch SET status = 'failed', finished_at = now() "
            "WHERE batch_id = ?",
            [batch_id],
        )
        raise

    rejected = parse_rejects + structural_rejects
    rows_read = accepted + rejected
    status = "succeeded" if rejected == 0 else "partial"

    for contract_id in preview.contracts:
        ensure_contract(con, contract_id)
    _extend_calendar(con, batch_id, preview)

    reasons = dict(
        con.execute(
            "SELECT reason_code, count(*) FROM stage.record_reject WHERE batch_id = ? "
            "GROUP BY 1 ORDER BY 2 DESC",
            [batch_id],
        ).fetchall()
    )
    first_date, last_date = con.execute(
        "SELECT min(trade_date), max(trade_date) FROM stage.market_record WHERE batch_id = ?",
        [batch_id],
    ).fetchone()

    con.execute(
        """
        UPDATE stage.ingest_batch
           SET status = ?, rows_read = ?, rows_accepted = ?, rows_rejected = ?,
               error_summary = ?, finished_at = now()
         WHERE batch_id = ?
        """,
        [status, rows_read, accepted, rejected, json.dumps(reasons), batch_id],
    )

    return LoadResult(
        batch_id=batch_id,
        filename=preview.filename,
        file_hash=preview.file_hash,
        frequency=preview.frequency,
        status=status,
        rows_read=rows_read,
        rows_accepted=accepted,
        rows_rejected=rejected,
        contracts=list(preview.contracts),
        trade_date_range=(first_date, last_date),
        elapsed_seconds=(datetime.now() - started).total_seconds(),
        reject_reasons=reasons,
    )


# ------------------------------------------------------------------ batch lifecycle


def _open_batch(
    con: duckdb.DuckDBPyConnection, preview: Preview, *, origin: str = "upload"
) -> str:
    """Write the batch row, `running`, with every ingestion decision recorded.

    `running` is a transient state inside one request rather than something a client polls.
    It exists so that a load which dies part-way leaves a row with a null `finished_at` —
    the signal that it happened, and the handle for cleaning up the rows it wrote.
    """
    row = con.execute(
        """
        INSERT INTO stage.ingest_batch
          (filename, file_hash, file_bytes, file_format, origin, status, column_mapping,
           frequency, bar_interval, source_timezone, ts_convention, session_boundary,
           inferred_interval, interval_confidence)
        VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING batch_id
        """,
        [
            preview.filename,
            preview.file_hash,
            preview.file_bytes,
            preview.file_format,
            origin,
            json.dumps(preview.column_mapping, default=str),
            preview.frequency,
            preview.bar_interval,
            preview.source_timezone.value,
            preview.ts_convention,
            preview.session_boundary,
            preview.inferred_interval.value,
            preview.interval_confidence,
        ],
    ).fetchone()
    return str(row[0])


# ----------------------------------------------------------------------- projection


def _source_for(preview: Preview, target: str) -> str | None:
    mapping = preview.column_mapping
    if preview.profile is not None:
        for source, mapped in mapping.items():
            if mapped is None:
                continue
            targets = mapped if isinstance(mapped, list) else [mapped]
            if target in targets:
                return source
        return None
    for source, mapped in mapping.items():
        if mapped == target:
            return source
    return None


def _ts_source_column(preview: Preview) -> str:
    """The column holding the timestamp label we preserve verbatim.

    `ts_utc` is a conclusion about the data and can be wrong; `ts_source` is what the file
    actually said, so a corrected timezone is a query over `stage` rather than a re-read of
    a file that may no longer exist.
    """
    explicit = _source_for(preview, "ts_source")
    if explicit and explicit in {name for name, _ in preview.detected_columns}:
        return explicit
    return _ts_column(preview)


def _ts_column(preview: Preview) -> str:
    if preview.profile is not None:
        for source, mapped in preview.column_mapping.items():
            if isinstance(mapped, list) and "ts_exchange" in mapped:
                return source
    for source, mapped in preview.column_mapping.items():
        if mapped == "ts":
            return source
    raise ValueError(f"{preview.filename}: no timestamp column resolved")


def _contract_column(preview: Preview) -> str:
    for source, mapped in preview.column_mapping.items():
        if mapped == "contract_id" or mapped == ["contract_id"]:
            return source
    raise ValueError(f"{preview.filename}: no contract column resolved")


def _text(column: str) -> str:
    return f'CAST("{column}" AS VARCHAR)'


def _optional_text(preview: Preview, target: str) -> str:
    source = _source_for(preview, target)
    if source is None:
        return "NULL"
    if source not in {name for name, _ in preview.detected_columns}:
        return "NULL"
    return _text(source)


# ------------------------------------------------------------------------- records


def _session_open_case(preview: Preview) -> str:
    """A per-contract session open, as SQL.

    A file may carry more than one root, and the roll is a per-root property: ZC opens at
    19:00, and SB stays inside one calendar day and never rolls at all. A NULL boundary is
    how "never rolls" is expressed, because a NULL comparison sends the row down the
    no-roll branch. Roots with no profile fall back to the CME-family 17:00, which is
    recorded on the batch as an assumption.
    """
    branches: list[str] = []
    for contract_id in preview.contracts:
        parsed = parse_symbol(contract_id, KNOWN_ROOTS)
        product = PRODUCTS_BY_ROOT.get(parsed.root) if parsed.parsed else None
        if product is None:
            continue
        session = product.session
        boundary = (
            f"TIME '{session.open_local.strftime('%H:%M:%S')}'"
            if session.spans_midnight
            else "CAST(NULL AS TIME)"
        )
        escaped = contract_id.replace("'", "''")
        branches.append(f"WHEN '{escaped}' THEN {boundary}")
    if not branches:
        return f"TIME '{DEFAULT_SESSION_OPEN}'"
    return (
        "CASE contract_txt " + " ".join(branches) + f" ELSE TIME '{DEFAULT_SESSION_OPEN}' END"
    )


def _projection(preview: Preview) -> str:
    """One text-typed row per source row, with the reject reason already decided."""
    contract_col = _text(_contract_column(preview))
    ts_col = _text(_ts_column(preview))
    ts_source_col = _text(_ts_source_column(preview))

    price_exprs = {t: _optional_text(preview, t) for t in PRICE_TARGETS}
    volume_expr = _optional_text(preview, "volume")
    oi_expr = _optional_text(preview, "open_interest")

    # A value that is present but does not parse is a reject; a value that is absent is a
    # null, and a null is a finding for the quality engine rather than a load failure.
    bad_price = " OR ".join(
        f"(nullif(trim({expr}), '') IS NOT NULL AND TRY_CAST({expr} AS DOUBLE) IS NULL)"
        for expr in price_exprs.values()
        if expr != "NULL"
    ) or "FALSE"
    bad_volume = (
        f"(nullif(trim({volume_expr}), '') IS NOT NULL "
        f"AND TRY_CAST({volume_expr} AS BIGINT) IS NULL)"
        if volume_expr != "NULL"
        else "FALSE"
    )

    columns = ", ".join(f'"{name}"' for name, _ in preview.detected_columns)
    return f"""
        SELECT
          row_number() OVER () AS scan_row,
          {contract_col} AS contract_txt,
          {ts_col}       AS ts_txt,
          {ts_source_col} AS ts_source_txt,
          {price_exprs['open']}  AS open_txt,
          {price_exprs['high']}  AS high_txt,
          {price_exprs['low']}   AS low_txt,
          {price_exprs['close']} AS close_txt,
          {volume_expr} AS volume_txt,
          {oi_expr}     AS oi_txt,
          CASE
            WHEN nullif(trim({contract_col}), '') IS NULL THEN 'STR.UNPARSEABLE_ROW'
            WHEN TRY_CAST({ts_col} AS TIMESTAMP) IS NULL  THEN 'STR.BAD_TIMESTAMP'
            WHEN {bad_price}                              THEN 'STR.NON_NUMERIC_PRICE'
            WHEN {bad_volume}                             THEN 'STR.NON_NUMERIC_VOLUME'
            ELSE NULL
          END AS reject_reason,
          to_json(struct_pack({columns})) AS raw_payload
        FROM {scan_sql(preview.file_format, all_varchar=preview.file_format == 'csv')}
    """


def _source_row_expr(con: duckdb.DuckDBPyConnection, preview: Preview) -> str:
    """Map scan order onto the row number in the source file.

    The CSV reader skips structurally broken lines, so scan order and file order diverge as
    soon as one is present. `source_row` is the traceability spine — every finding must be
    able to say "row 41,207 of ESZ25.parquet" — so it is corrected rather than approximated.
    """
    skipped = _structural_reject_rows(con)
    if not skipped:
        return "scan_row"
    con.execute("DROP TABLE IF EXISTS _loupe_row_map")
    con.execute(
        """
        CREATE TEMP TABLE _loupe_row_map AS
        SELECT row_number() OVER (ORDER BY i) AS scan_row, i AS source_row
        FROM (SELECT unnest(generate_series(1, ?)) AS i) t
        WHERE i NOT IN (SELECT unnest(?))
        """,
        [preview.row_count + len(skipped), [r for r, _ in skipped]],
    )
    return "source_row"


def _insert_records(
    con: duckdb.DuckDBPyConnection, preview: Preview, batch_id: str
) -> tuple[int, list[tuple[int, str]]]:
    """Append the parseable rows, deriving `ts_utc` and the trade date as we go."""
    projection = _projection(preview)
    timezone = preview.source_timezone.value or "America/Chicago"

    # Trade date: a session is attributed to the date it closes. A daily row is already a
    # session date in this corpus, so no roll is applied to it.
    if preview.frequency == "daily":
        trade_date = "CAST(ts_exchange AS DATE)"
    else:
        trade_date = roll_sql("ts_exchange", _session_open_case(preview))

    # The scan has to run before the reject log can be read, so it is materialised once.
    con.execute("DROP TABLE IF EXISTS _loupe_scan")
    con.execute(f"CREATE TEMP TABLE _loupe_scan AS {projection}", [str(preview.path)])
    structural = _structural_reject_rows(con)
    source_row = _source_row_expr(con, preview)

    join = (
        "JOIN _loupe_row_map m USING (scan_row)" if source_row == "source_row" else ""
    )
    inserted = con.execute(
        f"""
        INSERT INTO stage.market_record
          (batch_id, source_row, contract_id, frequency, ts_source, ts_exchange, ts_utc,
           trade_date, open, high, low, close, volume, volume_source, open_interest)
        SELECT ?, {source_row}, contract_txt, ?, ts_source_txt, ts_exchange,
               ts_exchange AT TIME ZONE ?, {trade_date},
               TRY_CAST(open_txt AS DOUBLE), TRY_CAST(high_txt AS DOUBLE),
               TRY_CAST(low_txt AS DOUBLE),  TRY_CAST(close_txt AS DOUBLE),
               TRY_CAST(volume_txt AS BIGINT), {_FRACTIONAL_VOLUME},
               TRY_CAST(oi_txt AS BIGINT)
        FROM (
          SELECT *, TRY_CAST(ts_txt AS TIMESTAMP) AS ts_exchange FROM _loupe_scan
        ) s {join}
        WHERE reject_reason IS NULL
        RETURNING 1
        """,
        [batch_id, preview.frequency, timezone],
    ).fetchall()
    return len(inserted), structural


def _insert_parse_rejects(
    con: duckdb.DuckDBPyConnection, preview: Preview, batch_id: str
) -> int:
    """Rows the reader could read but we could not parse."""
    source_row = "source_row" if _has_row_map(con) else "scan_row"
    join = "JOIN _loupe_row_map m USING (scan_row)" if source_row == "source_row" else ""
    rows = con.execute(
        f"""
        INSERT INTO stage.record_reject
          (batch_id, source_row, reason_code, reason_detail, raw_payload)
        SELECT ?, {source_row}, reject_reason,
               CASE reject_reason
                 WHEN 'STR.BAD_TIMESTAMP' THEN 'timestamp ' || coalesce(ts_txt, '<null>')
                      || ' does not parse'
                 WHEN 'STR.UNPARSEABLE_ROW' THEN 'no contract identifier on the row'
                 WHEN 'STR.NON_NUMERIC_PRICE' THEN 'a price field is present but not numeric'
                 WHEN 'STR.NON_NUMERIC_VOLUME' THEN 'volume is present but not numeric'
               END,
               raw_payload
        FROM _loupe_scan s {join}
        WHERE reject_reason IS NOT NULL
        RETURNING 1
        """,
        [batch_id],
    ).fetchall()
    return len(rows)


def _insert_structural_rejects(
    con: duckdb.DuckDBPyConnection, batch_id: str, structural: list[tuple[int, str]]
) -> int:
    """Lines the CSV reader could not split into the expected field count."""
    if not structural:
        return 0
    con.executemany(
        """
        INSERT INTO stage.record_reject
          (batch_id, source_row, reason_code, reason_detail, raw_payload)
        VALUES (?, ?, 'STR.UNPARSEABLE_ROW', 'row does not split into the expected field count', ?)
        """,
        [(batch_id, source_row, line) for source_row, line in structural],
    )
    return len(structural)


# ------------------------------------------------------------------- reject plumbing


def _clear_reject_log(con: duckdb.DuckDBPyConnection) -> None:
    """Empty DuckDB's CSV reject tables so this load only sees its own failures."""
    for table in ("reject_errors", "reject_scans"):
        try:
            con.execute(f"DELETE FROM {table}")
        except duckdb.Error:
            return


def _structural_reject_rows(con: duckdb.DuckDBPyConnection) -> list[tuple[int, str]]:
    """`(source_row, raw_line)` for every line the reader skipped, de-duplicated."""
    try:
        rows = con.execute(
            "SELECT DISTINCT line, csv_line FROM reject_errors "
            "WHERE error_type = 'MISSING COLUMNS' ORDER BY line"
        ).fetchall()
    except duckdb.Error:
        return []
    # `line` counts the header; a data row is one less.
    return [(int(line) - 1, csv_line) for line, csv_line in rows]


def _has_row_map(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM duckdb_tables() WHERE table_name = '_loupe_row_map'"
        ).fetchone()
    )


def _extend_calendar(
    con: duckdb.DuckDBPyConnection, batch_id: str, preview: Preview
) -> None:
    """Generate session-calendar rows covering what this batch actually loaded."""
    spans = con.execute(
        """
        SELECT c.root, min(r.trade_date), max(r.trade_date)
        FROM stage.market_record r
        JOIN ref.contract c USING (contract_id)
        WHERE r.batch_id = ? AND c.root IS NOT NULL
        GROUP BY c.root
        """,
        [batch_id],
    ).fetchall()
    for root, start, end in spans:
        seed_calendar(con, root, start, end)
