"""Preparing the demo: fetch the corpus, write a CSV copy, and stage the injected defects.

This module gets files onto disk and says what should be loaded. It does **not** touch the
database. That separation is the layer boundary `specs/loupe-solution-design.md` §6 draws and
slice 5 built the UI around: the pages talk to the API over HTTP and to nothing else, so the
demo buttons fetch here and then ingest through `POST /v1/ingest/batches` — the same HTTP
path any file ingest uses. A shortcut that wrote records directly would make
the demo a different code path from the one being demonstrated.

**Two files are converted to CSV, and the rules for picking them are stated rather than
chosen.** The exercise requires accepting CSV *and* Parquet, and `specs/api-contract.md` §9
carries that in the traceability table — but the vendor ships only Parquet, so without this a
reviewer following the walkthrough would never see the CSV path run at all.

- The **earliest** minute file by `first_timestamp_ms` is converted because the pick has to be
  reproducible from data rather than a filename somebody typed; `files.csv` already carries the
  column.
- The **smallest** minute file by `row_count` is converted because it is the injection source,
  and a button a reviewer presses twice should not cost them a minute of waiting.

If those are the same file, one conversion happens.

**A converted file replaces its Parquet in the load; it is never loaded alongside.** Two copies
of one contract's tape differ only in format, so ingesting both would make almost every row an
exact duplicate and bury the demo in `UNQ.*` findings nobody planted. The corpus is loaded once.

**Injection swaps a file rather than adding one, for the same reason.** The injected copy is the
smallest minute file with nine labelled defects in it, and staging it means purging the pristine
batch first. That is also the better demo: the same contract and the same sessions before and
after, so the reviewer can see exactly what the defects cost the score.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .fetch import DEST, FetchReport, fetch_corpus
from .injection import InjectionReport, inject

#: Where derived demo files are written. Never `data/samples/`: that directory holds vendor
#: bytes and a derived file sitting in it is one `rm` away from being mistaken for one.
DEMO_DIR = DEST.parent / "demo"

#: Loaded with this origin, so the batch says it came from the demo button rather than from a
#: person choosing a file. Real vendor data either way — only `injected` is manufactured.
DEMO_ORIGIN = "demo"
INJECTED_ORIGIN = "injected"


@dataclass(frozen=True)
class ConvertedFile:
    """One Parquet rendered as CSV, and what it was chosen for."""

    source_path: Path
    csv_path: Path
    rows: int
    reason: str


@dataclass(frozen=True)
class DemoFile:
    """A file the demo should ingest, and the origin it should be ingested under."""

    path: Path
    origin: str
    note: str = ""


@dataclass(frozen=True)
class DemoCorpus:
    """What a prepared demo consists of: what was fetched, converted, and what to load."""

    fetch: FetchReport
    converted: list[ConvertedFile]
    files: list[DemoFile]

    @property
    def csv_files(self) -> int:
        return sum(1 for f in self.files if f.path.suffix == ".csv")

    @property
    def parquet_files(self) -> int:
        return sum(1 for f in self.files if f.path.suffix == ".parquet")


@dataclass(frozen=True)
class InjectionPlan:
    """A staged injection: the file to load, and the pristine batch it stands in for."""

    report: InjectionReport
    replaces_filename: str

    @property
    def path(self) -> Path:
        return self.report.output_path

    @property
    def manifest_path(self) -> Path:
        return self.report.manifest_path


# --------------------------------------------------------------------------- the manifest


def _minute_rows(dest: Path = DEST) -> list[dict[str, str]]:
    """`files.csv` rows for the minute files actually on disk.

    On disk rather than declared: the curated fetch takes eight of forty, and a pick made from
    the full manifest could name a file nobody downloaded.
    """
    manifest = dest / "files.csv"
    if not manifest.exists():
        return []
    with manifest.open(newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row["frequency"] == "minute" and (dest / row["path"]).exists()
        ]


def earliest_minute(dest: Path = DEST) -> dict[str, str] | None:
    """The minute file that starts first. Reproducible from `first_timestamp_ms`."""
    rows = _minute_rows(dest)
    return min(rows, key=lambda r: int(r["first_timestamp_ms"])) if rows else None


def smallest_minute(dest: Path = DEST) -> dict[str, str] | None:
    """The minute file with the fewest rows — the one a demo can afford to reload."""
    rows = _minute_rows(dest)
    return min(rows, key=lambda r: int(r["row_count"])) if rows else None


# -------------------------------------------------------------------------- conversion


def convert_to_csv(source: Path, target: Path) -> ConvertedFile:
    """Render one Parquet as CSV, losslessly enough that the loader cannot tell.

    Explicit `TIMESTAMPFORMAT` and `DATEFORMAT` rather than DuckDB's defaults, because the
    whole claim being made is that the two formats *mean the same thing*: the vendor's
    `timestamp_chicago_wall` is a wall-clock label (`specs/sample-corpus.md` §4.1), and a
    writer that emitted an ISO `T` separator or a zone suffix would be asserting something the
    Parquet does not. `tests/integration/` holds the two side by side and compares the loaded
    records, which is the only way to know this held.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        # `COPY ... TO` takes no bound parameter for its destination, so that one path is
        # inlined with its quotes doubled. The *source* stays a parameter, which is the half a
        # caller could point anywhere.
        destination = str(target).replace("'", "''")
        con.execute(
            f"COPY (SELECT * FROM read_parquet(?)) TO '{destination}' "
            "(FORMAT CSV, HEADER, DATEFORMAT '%Y-%m-%d', TIMESTAMPFORMAT '%Y-%m-%d %H:%M:%S')",
            [str(source)],
        )
        rows = con.execute("SELECT count(*) FROM read_parquet(?)", [str(source)]).fetchone()[0]
    finally:
        con.close()
    return ConvertedFile(source_path=source, csv_path=target, rows=int(rows), reason="")


def convert_earliest_to_csv(
    dest: Path = DEST, out_dir: Path = DEMO_DIR
) -> ConvertedFile:
    """The CLI's `--csv`: one CSV example on disk, picked the same way the button picks it."""
    row = earliest_minute(dest)
    if row is None:
        raise FileNotFoundError(
            f"No minute files under {dest}. Fetch the corpus before converting one."
        )
    source = dest / row["path"]
    converted = convert_to_csv(source, out_dir / f"{source.stem}.csv")
    return ConvertedFile(
        source_path=converted.source_path,
        csv_path=converted.csv_path,
        rows=converted.rows,
        reason="earliest minute file by first_timestamp_ms",
    )


# ------------------------------------------------------------------------ orchestration


def prepare_demo_corpus(
    *,
    dest: Path = DEST,
    out_dir: Path = DEMO_DIR,
    all_minute: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> DemoCorpus:
    """Fetch the corpus, write the CSV copies, and return the files to ingest, in order.

    Daily files first. Reconciliation needs both grains for a contract and the score object
    says which dimensions were in scope, so loading daily before minute means the inventory is
    never briefly showing a book that looks minute-only — and it matches the order
    load-both-grains recommends (`specs/loupe-solution-design.md` §2).
    """
    from .fetch import daily_paths

    report = fetch_corpus(dest=dest, all_minute=all_minute, on_progress=on_progress)

    converted: list[ConvertedFile] = []
    replaced: dict[str, Path] = {}
    for row, reason in (
        (earliest_minute(dest), "earliest minute file by first_timestamp_ms"),
        (smallest_minute(dest), "smallest minute file; the injection source"),
    ):
        if row is None or row["path"] in replaced:
            continue
        source = dest / row["path"]
        result = convert_to_csv(source, out_dir / f"{source.stem}.csv")
        converted.append(
            ConvertedFile(
                source_path=source,
                csv_path=result.csv_path,
                rows=result.rows,
                reason=reason,
            )
        )
        replaced[row["path"]] = result.csv_path

    files = [
        DemoFile(path=dest / rel, origin=DEMO_ORIGIN) for rel in daily_paths(dest=dest)
    ]
    for row in _minute_rows(dest):
        rel = row["path"]
        if rel in replaced:
            files.append(
                DemoFile(
                    path=replaced[rel],
                    origin=DEMO_ORIGIN,
                    note="converted from Parquet, so both accepted formats are exercised",
                )
            )
        else:
            files.append(DemoFile(path=dest / rel, origin=DEMO_ORIGIN))

    return DemoCorpus(fetch=report, converted=converted, files=files)


def prepare_injection(
    *, dest: Path = DEST, out_dir: Path = DEMO_DIR, seed: int = 20260906
) -> InjectionPlan:
    """Write the labelled defective copy, and name the pristine file it stands in for.

    The source is the CSV copy of the smallest minute file, which `prepare_demo_corpus` has
    already written — the injector reads CSV, and reusing the file the demo actually loaded is
    what makes the swap a before-and-after of the same contract rather than a new one appearing.

    Nothing is ingested here and nothing under `data/samples/` is touched: `inject` refuses to
    write over its source, and that refusal is load-bearing rather than defensive now that a
    button can reach it.
    """
    row = smallest_minute(dest)
    if row is None:
        raise FileNotFoundError(
            f"No minute files under {dest}. Load the demo data before injecting defects."
        )
    source_parquet = dest / row["path"]
    source_csv = out_dir / f"{source_parquet.stem}.csv"
    if not source_csv.exists():
        convert_to_csv(source_parquet, source_csv)

    report = inject(
        source_csv, out_dir / f"{source_parquet.stem}_with_defects.csv", seed=seed
    )
    return InjectionPlan(report=report, replaces_filename=source_csv.name)
