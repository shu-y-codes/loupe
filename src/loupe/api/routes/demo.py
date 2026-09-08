"""Demo chrome: load the sample corpus, plant labelled defects, take them out again.

**Why these are routes at all.** Locked decision 9 permits a "Load demo data" button and
forbids the thing that would be wrong — fetching *during ingest*. That has not changed. What
changed is where the button's code runs. The two demo actions read the local filesystem, write
derived files, and reach Hugging Face on an explicit press; a browser can do none of those, so
the work moved to the process that can. `POST /v1/demo/load` is the same consent-then-fetch
sequence the Streamlit panel ran, with the reviewer's click on the other side of an HTTP call.

**They are not a second ingest pipeline.** Every file loaded here goes through
`routes.ingest.ingest_path` — the same preview, loader, validation and bar rebuild that
`POST /v1/ingest/batches` uses. Arbitrary file ingest stays multipart on that route; what this
router skips is only the hop of a server posting bytes to itself. Ingest still reaches the
filesystem and the database and nothing else.

**Progress streams as NDJSON.** The Streamlit panel could say "Fetching 3/48 · filename"
because it was the process doing the fetching. A browser needs telling, and a minute of silence
after a button press reads as a hang. One JSON object per line, flushed as it happens.

That is **UI telemetry, not a job table**: nothing is persisted, no handle is returned, and
there is nothing to poll. Locked decision 7 stands — every write here blocks until it is done,
and the stream ends with the finished result (`specs/api-contract.md` §4.4).
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from loupe.data import BatchNotFound, forget_batch
from loupe.demo.corpus import (
    DEMO_DIR,
    DEMO_ORIGIN,
    INJECTED_ORIGIN,
    prepare_demo_corpus,
    prepare_injection,
)
from loupe.demo.fetch import FetchFailed, describe_corpus
from loupe.quality import assess
from loupe.quality.catalogue import strip_family
from loupe.quality.errors import RulesNotSeeded

from ..deps import Database
from ..models import (
    CorpusDescription,
    InjectionResponse,
    PlantedDefect,
    PlantedGroup,
)
from .ingest import ingest_path

router = APIRouter(prefix="/demo", tags=["demo"])

#: One JSON object per line. Not SSE: there is exactly one consumer, it is a `fetch()` reading
#: the body, and `text/event-stream` would add a framing nobody here needs.
MEDIA_TYPE = "application/x-ndjson"

#: Planted-defect groups. Recurring patterns is not a planted family: it is an insight over
#: findings, so nothing can be injected *as* one (`specs/loupe-ui-design.md`).
PLANTED_FAMILY_ORDER = ("gaps", "duplicates", "invalid", "off_strip")
PLANTED_FAMILY_LABEL = {
    "gaps": "Gaps",
    "duplicates": "Duplicates",
    "invalid": "Invalid values",
    "off_strip": "Other (off the strip)",
}


# ------------------------------------------------------------------------------- events


def _event(kind: str, message: str, **fields: Any) -> str:
    return json.dumps({"event": kind, "message": message, **fields}) + "\n"


def _progress(phase: str, done: int, total: int, file: str, message: str) -> str:
    return _event("progress", message, phase=phase, done=done, total=total, file=file)


def _error(title: str, message: str, **fields: Any) -> str:
    """A refusal the reader can act on, not a traceback.

    Offline is an answer: the corpus lives on someone else's server and a reviewer's laptop is
    allowed to have no route to it. The stream has already begun by the time this is known, so
    it is an event rather than a problem response — the status line went out at byte zero.
    """
    return _event("error", message, title=title, **fields)


def _stream(events: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(events, media_type=MEDIA_TYPE)


def _pump(work: Callable[[Callable[[str], None]], None]) -> Iterator[str]:
    """Run `work` on a thread and yield the lines it emits, in order, as they happen.

    `fetch_corpus` reports progress by calling back, and a callback cannot be yielded from.
    The thread is what turns one into the other: `work` is handed an `emit`, and this
    generator drains the queue until the thread is finished and the queue is empty.
    """
    lines: queue.Queue[str | None] = queue.Queue()

    def run() -> None:
        try:
            work(lines.put)
        except Exception as exc:  # noqa: BLE001 - the stream is the only place to say it
            lines.put(_error("Demo step failed", str(exc)))
        finally:
            lines.put(None)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    while True:
        line = lines.get()
        if line is None:
            return
        yield line


# ----------------------------------------------------------------------------- describe


@router.get(
    "/corpus",
    response_model=CorpusDescription,
    summary="What a demo load would download",
)
def corpus() -> CorpusDescription:
    """Said **before** the button, not after it: a reader cannot consent to an unnamed fetch.

    `specs/sample-corpus.md` §1 found no licence grant anywhere in the vendor package — public
    and ungated, so downloading for evaluation is plainly intended, but nothing authorises
    redistribution. This route touches no network; it describes what a load would do.
    """
    described = describe_corpus()
    return CorpusDescription(
        repo=described.repo,
        revision=described.revision,
        url=described.url,
        approx_mb=described.approx_mb,
        minute_files=described.minute_files,
        licence_note=described.licence_note,
    )


# --------------------------------------------------------------------------------- load


@router.post(
    "/load",
    summary="Fetch the sample corpus and ingest it",
    response_class=StreamingResponse,
    responses={200: {"content": {MEDIA_TYPE: {}}, "description": "NDJSON progress events."}},
)
def load(
    request: Request,
    all_minute: Annotated[
        bool,
        Query(
            description="Fetch every minute file rather than the curated eight. ~104 MB "
            "instead of ~16 (`specs/sample-corpus.md` §8)."
        ),
    ] = False,
) -> StreamingResponse:
    """Fetch, ingest with `origin=demo`, then one corpus-wide validation run.

    Real vendor data and real findings; nothing here is manufactured. The separation from
    `/demo/inject` is the whole design — a reviewer has to be able to see findings on real data
    *and know that is what they are looking at* before anything synthetic exists in the store.
    """
    database: Database = request.app.state.database
    return _stream(_pump(lambda emit: _load(database, emit, all_minute=all_minute)))


def _load(database: Database, emit: Callable[[str], None], *, all_minute: bool) -> None:
    emit(_event("started", "Fetching the sample corpus…", phase="fetch"))
    try:
        prepared = prepare_demo_corpus(
            all_minute=all_minute,
            on_progress=lambda rel, done, total: emit(
                _progress("fetch", done, total, rel.split("/")[-1],
                          f"Fetching {done}/{total} · {rel.split('/')[-1]}")
            ),
        )
    except FetchFailed as exc:
        emit(
            _error(
                "Could not fetch the corpus",
                str(exc),
                hint="The app is fully usable without the sample corpus. Try Load demo data "
                "again when you have a network.",
            )
        )
        return

    for name in prepared.fetch.checksum_failures:
        emit(
            _event(
                "warning",
                f"Checksum mismatch on {name}; it was fetched but does not verify.",
                file=name,
            )
        )

    total = len(prepared.files)
    loaded = 0
    for index, demo_file in enumerate(prepared.files, start=1):
        emit(
            _progress(
                "ingest", index, total, demo_file.path.name,
                f"Loading {index}/{total} · {demo_file.path.name}",
            )
        )
        # `validate=False` on every file because the corpus-wide run below supersedes them:
        # running the rules 48 times over one batch each, then again over everything, is
        # slower and answers a narrower question each time.
        try:
            with database.session() as con:
                _summary, duplicate = ingest_path(
                    con, demo_file.path, validate=False, origin=demo_file.origin
                )
        except Exception as exc:  # noqa: BLE001 - reported in the stream, not raised
            emit(_error(f"Failed on {demo_file.path.name}", str(exc)))
            return
        # A duplicate is not a failure. Re-pressing the button on a half-loaded store should
        # finish the job, which is the same idempotence the fetch already has.
        loaded += 0 if duplicate else 1

    emit(_event("started", "Validating the whole corpus…", phase="validate"))
    if not _revalidate(database, emit, failure="Loaded, but the corpus-wide run failed"):
        return

    formats = f"{prepared.parquet_files} Parquet, {prepared.csv_files} CSV"
    emit(
        _event(
            "done",
            f"Loaded {loaded} files ({formats})",
            loaded=loaded,
            files=total,
            parquet_files=prepared.parquet_files,
            csv_files=prepared.csv_files,
        )
    )


def _revalidate(database: Database, emit: Callable[[str], None], *, failure: str) -> bool:
    """One corpus-wide run. Unscoped on purpose (`specs/api-contract.md` §6.4).

    An upload validates its own batch only, so cross-frequency reconciliation cannot be in
    scope at that moment — the run has not seen the other grain yet.
    """
    try:
        with database.session() as con:
            assess(con)
    except RulesNotSeeded as exc:
        emit(_error(failure, str(exc)))
        return False
    except Exception as exc:  # noqa: BLE001 - reported in the stream, not raised
        emit(_error(failure, str(exc)))
        return False
    return True


# ------------------------------------------------------------------------------- inject


@router.post(
    "/inject",
    summary="Plant labelled defects",
    response_class=StreamingResponse,
    responses={200: {"content": {MEDIA_TYPE: {}}, "description": "NDJSON progress events."}},
)
def inject(request: Request) -> StreamingResponse:
    """Swap one clean minute file for a copy carrying nine labelled defects.

    **Swap, do not add.** The injected copy is the same contract and the same sessions, so
    loading it alongside the clean one would make almost every row an exact duplicate and bury
    the planted defects under `UNQ.*` findings nobody planted. It is also the better demo: the
    same tape before and after, so the reviewer sees exactly what the defects cost.

    Every defect is labelled in a manifest naming the rule it should trip, and the store says
    it is synthetic for as long as the batch is loaded. The vendor files on disk are never
    modified — `loupe.demo.injection` refuses to write over its source.
    """
    database: Database = request.app.state.database
    return _stream(_pump(lambda emit: _inject(database, emit)))


def _inject(database: Database, emit: Callable[[str], None]) -> None:
    emit(_event("started", "Planting labelled defects…", phase="stage"))
    try:
        plan = prepare_injection()
    except (FileNotFoundError, RuntimeError) as exc:
        emit(_error("Could not stage the injection", str(exc)))
        return

    emit(_event("progress", f"Removing the clean {plan.replaces_filename}…", phase="purge"))
    failure = _purge_where(database, lambda b: b["filename"] == plan.replaces_filename)
    if failure is not None:
        emit(_error("Could not remove the clean copy", failure))
        return

    emit(_event("progress", "Loading the defective copy…", phase="ingest"))
    try:
        with database.session() as con:
            ingest_path(con, plan.path, validate=False, origin=INJECTED_ORIGIN)
    except Exception as exc:  # noqa: BLE001 - reported in the stream, not raised
        emit(_error("Could not load the defective copy", str(exc)))
        return

    emit(_event("started", "Re-validating…", phase="validate"))
    if not _revalidate(database, emit, failure="Planted, but the re-run failed"):
        return

    planted = len(plan.report.manifest.defects)
    emit(
        _event(
            "done",
            f"{planted} labelled defects loaded",
            planted=planted,
            filename=plan.path.name,
        )
    )


@router.post(
    "/remove",
    summary="Remove planted defects and restore the clean file",
    response_class=StreamingResponse,
    responses={200: {"content": {MEDIA_TYPE: {}}, "description": "NDJSON progress events."}},
)
def remove(request: Request) -> StreamingResponse:
    """The way back. A demo that can only be undone with `rm` is one nobody presses."""
    database: Database = request.app.state.database
    return _stream(_pump(lambda emit: _remove(database, emit)))


def _remove(database: Database, emit: Callable[[str], None]) -> None:
    emit(_event("started", "Removing planted defects…", phase="purge"))
    failure = _purge_where(database, lambda b: b["origin"] == INJECTED_ORIGIN)
    if failure is not None:
        emit(_error("Could not remove them", failure))
        return

    # Put the clean copy back, so removing the defects returns the store to what the demo
    # button produced rather than to a hole where one contract used to be.
    restored = _restore_clean(database, emit)

    emit(_event("started", "Re-validating…", phase="validate"))
    if not _revalidate(database, emit, failure="Removed, but the re-run failed"):
        return
    emit(
        _event(
            "done",
            "Removed" + (" and the clean file restored" if restored else ""),
            restored=restored,
        )
    )


def _restore_clean(database: Database, emit: Callable[[str], None]) -> bool:
    try:
        plan = prepare_injection()
    except (FileNotFoundError, RuntimeError):
        return False
    clean = plan.path.parent / plan.replaces_filename
    if not clean.exists():
        return False
    emit(_event("progress", f"Restoring {clean.name}…", phase="ingest"))
    try:
        with database.session() as con:
            ingest_path(con, clean, validate=False, origin=DEMO_ORIGIN)
    except Exception as exc:  # noqa: BLE001 - a failed restore is reported, not fatal
        emit(_event("warning", f"Could not restore {clean.name}. {exc}", file=clean.name))
        return False
    return True


def _purge_where(
    database: Database, predicate: Callable[[dict[str, Any]], bool]
) -> str | None:
    """Purge every live batch matching `predicate`, **and forget it**. `None` when it worked.

    `forget_batch` rather than `purge_batch` because both callers are swapping a file, not
    deleting one: inject stands the defective copy in for the clean tape, and remove puts the
    clean tape back. Soft delete keeps the purged `file_hash`, which would refuse the second
    half of that round trip as a duplicate of a batch holding no records — the demo would say
    it had restored the file and would not have. `DELETE /v1/ingest/batches/{id}` is unchanged
    and still soft-deletes.
    """
    try:
        with database.session() as con:
            batches = [
                {"batch_id": str(row[0]), "filename": row[1], "origin": row[2]}
                for row in con.execute(
                    "SELECT batch_id, filename, origin FROM stage.ingest_batch "
                    "WHERE status <> 'purged'"
                ).fetchall()
            ]
            for batch in batches:
                if not predicate(batch):
                    continue
                try:
                    forget_batch(con, batch["batch_id"])
                except BatchNotFound:
                    # Already gone is the outcome we wanted.
                    continue
    except Exception as exc:  # noqa: BLE001 - the caller names the step; this is the reason
        return str(exc)
    return None


# ---------------------------------------------------------------------------- injection


@router.get(
    "/injection",
    response_model=InjectionResponse,
    summary="The planted manifest, grouped by strip family",
)
def injection(request: Request) -> InjectionResponse:
    """What was planted, grouped the way the cards are — so no client re-implements the map.

    `strip_family` is the same catalogue function the family cards use
    (`src/loupe/quality/catalogue.py`). Grouping here rather than in a widget is the layer
    boundary `specs/loupe-solution-design.md` §6 draws: a client that imported the map would be
    a second, quietly different one.

    The manifest is read from disk beside the file the store says is loaded, so a store with
    planted defects and no manifest reports `manifest_available: false` rather than pretending
    the disclosure is complete.
    """
    database: Database = request.app.state.database
    with database.session() as con:
        rows = con.execute(
            "SELECT filename FROM stage.ingest_batch "
            "WHERE origin = ? AND status <> 'purged' ORDER BY started_at DESC",
            [INJECTED_ORIGIN],
        ).fetchall()
    if not rows:
        return InjectionResponse(loaded=False, manifest_available=False)

    filename = str(rows[0][0])
    manifest_path = DEMO_DIR / f"{filename}.manifest.json"
    if not manifest_path.exists():
        return InjectionResponse(loaded=True, filename=filename, manifest_available=False)

    payload = json.loads(Path(manifest_path).read_text())
    return InjectionResponse(
        loaded=True,
        filename=filename,
        manifest_available=True,
        source=payload.get("source"),
        output=payload.get("output"),
        rows_in=payload.get("rows_in"),
        rows_out=payload.get("rows_out"),
        seed=payload.get("seed"),
        groups=group_planted(list(payload.get("defects") or [])),
    )


def group_planted(defects: list[dict[str, Any]]) -> list[PlantedGroup]:
    """Group manifest rows with the same catalogue map as the cards.

    Off-strip injectables (e.g. `TIM.*`) land in **Other (off the strip)**, not a fifth card
    and not the floor.
    """
    buckets: dict[str, list[PlantedDefect]] = {name: [] for name in PLANTED_FAMILY_ORDER}
    for row in defects:
        family = strip_family(str(row.get("rule_id") or ""))
        if family not in buckets:
            family = "off_strip"
        buckets[family].append(
            PlantedDefect(
                source_row=row.get("source_row"),
                rule_id=str(row.get("rule_id") or ""),
                kind=str(row.get("kind") or ""),
                original=row.get("original"),
                injected=row.get("injected"),
            )
        )
    return [
        PlantedGroup(family=name, label=PLANTED_FAMILY_LABEL[name], defects=rows)
        for name, rows in buckets.items()
        if rows
    ]
