"""Preview, batches, rejects and purge (`specs/api-contract.md` §4).

Uploads are the only way records enter the store; no request path fetches a third-party
dataset. Every write here blocks until the load and its validation finish and returns the
completed result, never a poll handle — §4.4 settles why.

The upload is spooled to a temporary file because `data.preview_file` and `data.load_file`
work on paths: ingest reads a Parquet file with DuckDB's own scanner, which needs a file to
point at. The temporary file is removed on the way out whatever happened.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from loupe.data import (
    BatchAlreadyPurged,
    BatchNotFound,
    DuplicateFileError,
    LoadResult,
    Preview,
    load_file,
    preview_file,
    purge_batch,
)
from loupe.data.errors import MissingRequiredColumn, PreviewError, UnsupportedFileFormat
from loupe.quality import assess

from ..deps import Con, FrequencyParam, LimitParam, OffsetParam
from ..errors import ProblemError
from ..models import (
    BatchesResponse,
    BatchSummary,
    Capability,
    Inference,
    PreviewResponse,
    PurgeResponse,
    RejectRow,
    RejectsResponse,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

#: The multipart field every write on this router reads. Spelled once so `preview` and
#: `batches` cannot drift apart on the field name a client has to send.
Upload = Annotated[UploadFile, File(description="The CSV or Parquet file to ingest.")]


def _spooled(upload: UploadFile) -> Path:
    """Write the upload to a temp file under its own name and return the path."""
    directory = Path(tempfile.mkdtemp(prefix="loupe-upload-"))
    target = directory / (upload.filename or "upload")
    with target.open("wb") as handle:
        while chunk := upload.file.read(1 << 20):
            handle.write(chunk)
    return target


def _discard(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.parent.rmdir()


def _preview_or_problem(con, path: Path) -> Preview:
    """Translate the data layer's refusals into the contract's `STR.*` vocabulary."""
    try:
        return preview_file(con, path)
    except UnsupportedFileFormat as exc:
        raise ProblemError(
            status=415,
            title="Unsupported file format",
            detail=str(exc),
            code="STR.UNSUPPORTED_FORMAT",
            type_="/errors/unsupported-file-format",
        ) from exc
    except MissingRequiredColumn as exc:
        raise ProblemError(
            status=422,
            title="Missing required column",
            detail=str(exc),
            code="STR.MISSING_REQUIRED_COLUMN",
            type_="/errors/missing-required-column",
            meta={"missing": exc.missing, "seen": exc.seen},
        ) from exc
    except PreviewError as exc:
        raise ProblemError(
            status=422,
            title="File could not be inspected",
            detail=str(exc),
            code="STR.UNREADABLE_FILE",
            type_="/errors/unreadable-file",
        ) from exc


def _as_preview_response(preview: Preview) -> PreviewResponse:
    return PreviewResponse(
        filename=preview.filename,
        file_format=preview.file_format,
        file_bytes=preview.file_bytes,
        rows_total=preview.row_count,
        detected_columns=[name for name, _ in preview.detected_columns],
        column_mapping=preview.column_mapping,
        unmapped_columns=preview.unmapped_columns,
        inferred_frequency=Inference(
            value=preview.frequency,
            method=preview.inferred_interval.method,
            confidence=preview.interval_confidence,
        ),
        inferred_timezone=Inference(
            value=preview.source_timezone.value,
            method=preview.source_timezone.method,
            confidence=preview.source_timezone.confidence,
        ),
        inferred_interval=Inference(
            value=preview.inferred_interval.value,
            method=preview.inferred_interval.method,
            confidence=preview.inferred_interval.confidence,
        ),
        ts_convention=preview.ts_convention,
        session_boundary=preview.session_boundary,
        contracts_detected=list(preview.contracts),
        verdict="duplicate" if preview.is_duplicate else "accept",
        already_ingested=preview.already_ingested,
        enables={
            name: Capability(
                available=cap.available,
                reason=cap.reason or None,
                substitute_offered=None if cap.available else False,
            )
            for name, cap in preview.capabilities.items()
        },
        warnings=list(preview.warnings),
    )


@router.post("/preview", response_model=PreviewResponse, summary="Dry run an upload")
def preview(con: Con, file: Upload) -> PreviewResponse:
    """Answer acceptance, inferences and capability *before* anything is written."""
    path = _spooled(file)
    try:
        return _as_preview_response(_preview_or_problem(con, path))
    finally:
        _discard(path)


def _batch_row(con, batch_id: str) -> tuple[Any, ...] | None:
    return con.execute(
        """
        SELECT b.batch_id, b.status, b.filename, b.file_format, b.file_hash, b.frequency,
               b.source_timezone, b.ts_convention, b.session_boundary,
               b.rows_read, b.rows_accepted, b.rows_rejected,
               b.started_at, b.finished_at
        FROM stage.ingest_batch b WHERE b.batch_id = ?
        """,
        [batch_id],
    ).fetchone()


def _summary(con, batch_id: str, *, dq_run_id: str | None = None) -> BatchSummary:
    """Read a batch back as the contract's summary, whatever wrote it."""
    row = _batch_row(con, batch_id)
    if row is None:
        raise ProblemError(
            status=404,
            title="Batch not found",
            detail=f"No ingest batch {batch_id}.",
            code="STR.UNKNOWN_BATCH",
            type_="/errors/batch-not-found",
        )
    contracts, sessions, first, last = con.execute(
        """
        SELECT list(DISTINCT contract_id), count(DISTINCT (contract_id, trade_date)),
               min(trade_date), max(trade_date)
        FROM stage.market_record WHERE batch_id = ?
        """,
        [batch_id],
    ).fetchone()
    elapsed = None
    if row[12] is not None and row[13] is not None:
        elapsed = int((row[13] - row[12]).total_seconds() * 1000)
    return BatchSummary(
        batch_id=str(row[0]),
        status=row[1],
        filename=row[2],
        file_format=row[3],
        file_hash=row[4],
        frequency=row[5],
        source_timezone=row[6],
        ts_convention=row[7],
        session_boundary=row[8],
        rows_read=int(row[9] or 0),
        rows_accepted=int(row[10] or 0),
        rows_rejected=int(row[11] or 0),
        contracts_detected=sorted(contracts or []),
        sessions_detected=int(sessions or 0),
        trade_date_range=[first, last],
        dq_run_id=dq_run_id,
        elapsed_ms=elapsed,
    )


@router.post(
    "/batches",
    response_model=BatchSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and load a file",
    responses={409: {"description": "These bytes are already loaded; the existing batch."}},
)
def create_batch(
    con: Con,
    response: Response,
    file: Upload,
    validate: Annotated[
        bool,
        Query(
            description="Run the rule engine over the new batch before returning. The "
            "finished run id comes back on the summary; the write is still synchronous "
            "either way.",
        ),
    ] = True,
) -> BatchSummary:
    """Load one file and return **201** with the finished batch.

    A re-upload of bytes already held is **409 with the existing batch**, not a silent second
    copy: `stage.ingest_batch.file_hash` is unique, which is what makes ingest idempotent
    rather than doubling every volume figure.
    """
    path = _spooled(file)
    try:
        preview = _preview_or_problem(con, path)
        try:
            result: LoadResult = load_file(con, path, preview=preview)
        except DuplicateFileError as exc:
            existing = _summary(con, exc.existing_batch_id)
            response.status_code = status.HTTP_409_CONFLICT
            return existing

        run_id = None
        if validate:
            run, _scores = assess(con, batch_id=result.batch_id)
            run_id = run.run_id
        return _summary(con, result.batch_id, dq_run_id=run_id)
    finally:
        _discard(path)


@router.get("/batches", response_model=BatchesResponse, summary="List batches")
def list_batches(
    con: Con,
    frequency: FrequencyParam = None,
    include_purged: bool = Query(
        False, description="Purged batches are soft-deleted; ingest history stays intact."
    ),
) -> BatchesResponse:
    clauses = ["TRUE"]
    args: list[object] = []
    if frequency is not None:
        clauses.append("frequency = ?")
        args.append(frequency)
    if not include_purged:
        clauses.append("status <> 'purged'")
    ids = con.execute(
        f"SELECT batch_id FROM stage.ingest_batch WHERE {' AND '.join(clauses)} "
        "ORDER BY started_at DESC",
        args,
    ).fetchall()
    data = [_summary(con, str(row[0])) for row in ids]
    return BatchesResponse(data=data, total=len(data))


@router.get("/batches/{batch_id}", response_model=BatchSummary, summary="Batch detail")
def get_batch(con: Con, batch_id: str) -> BatchSummary:
    return _summary(con, batch_id)


@router.get(
    "/batches/{batch_id}/rejects",
    response_model=RejectsResponse,
    summary="Rows this batch rejected",
)
def batch_rejects(
    con: Con, batch_id: str, limit: LimitParam = 100, offset: OffsetParam = 0
) -> RejectsResponse:
    """Paginated: a corrupt file can reject tens of thousands of rows."""
    _summary(con, batch_id)
    total = con.execute(
        "SELECT count(*) FROM stage.record_reject WHERE batch_id = ?", [batch_id]
    ).fetchone()[0]
    rows = con.execute(
        "SELECT source_row, reason_code, reason_detail, raw_payload "
        "FROM stage.record_reject WHERE batch_id = ? ORDER BY source_row LIMIT ? OFFSET ?",
        [batch_id, limit, offset],
    ).fetchall()
    return RejectsResponse(
        data=[
            RejectRow(
                source_row=int(r[0]), reason_code=r[1], reason_detail=r[2], raw_payload=r[3]
            )
            for r in rows
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/batches/{batch_id}", response_model=PurgeResponse, summary="Purge a batch"
)
def delete_batch(con: Con, batch_id: str) -> PurgeResponse:
    """Cascade to records, rejects, findings and mart rows; soft-delete the batch itself.

    Which tables that touches is `loupe.data.purge`'s to know, not this handler's.
    """
    try:
        result = purge_batch(con, batch_id)
    except BatchNotFound as exc:
        raise ProblemError(
            status=404,
            title="Batch not found",
            detail=str(exc),
            code="STR.UNKNOWN_BATCH",
            type_="/errors/batch-not-found",
        ) from exc
    except BatchAlreadyPurged as exc:
        raise ProblemError(
            status=409,
            title="Batch already purged",
            detail=str(exc),
            code="STR.ALREADY_PURGED",
            type_="/errors/batch-already-purged",
        ) from exc
    return PurgeResponse(
        batch_id=result.batch_id,
        status="purged",
        records_deleted=result.records_deleted,
        rejects_deleted=result.rejects_deleted,
        findings_deleted=result.findings_deleted,
        bars_deleted=result.bars_deleted,
        sessions_affected=result.sessions_affected,
    )
