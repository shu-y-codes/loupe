"""Fetching the vendor sample corpus — the pinned downloader, in one place.

This used to live in `tools/fetch_samples.py`, and the logic moved here when the UI grew a
"Load demo data" button. It is one implementation with two front doors: the tool still runs it
from a terminal, and the button calls the same functions. A second downloader would be free to
drift from this one on the revision, the checksum handling or the curated list — and the whole
value of a *pinned* fetch is that everyone gets the same bytes.

**Nothing here is a runtime dependency of ingest** (locked decision 9). The network is touched
when a person asks for the corpus, by script or by button, and never while a file is being read.
Ingest reaches the filesystem and the database and nothing else.

**The licence is why consent belongs to the caller.** `specs/sample-corpus.md` §1 is blunt:
there is no licence grant anywhere in the package, "other" with no text is not permission, and
downloading for evaluation is plainly intended while redistribution is not authorised. So the
data is never committed, and `describe_corpus()` exists to let a caller say what it is about to
download, and from where, *before* it downloads it.
"""

from __future__ import annotations

import csv
import hashlib
import pathlib
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

REPO = "lynx1231/historical-futures-data-sample"
#: Pinned revision, so a re-run fetches the same corpus the specs were measured against.
REVISION = "29efdfa21c5a5b2d7aa306397385cf116e011559"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEST = REPO_ROOT / "data" / "samples"

META = [
    "README.md",
    "SOURCE_NOTICE.md",
    "catalog.csv",
    "files.csv",
    "schema.json",
    "checksums.sha256",
    "dataset.json",
]

#: The vendor's own README.md and dataset.json were edited after the manifest was generated,
#: so their checksums are known-stale. Reporting a failure the user cannot act on is worse
#: than skipping them.
STALE_IN_MANIFEST = {"README.md", "dataset.json"}

#: One minute file per root: all six exchanges, all three session profiles, both odd tick
#: regimes, a contract expiring inside the window, and sizes from 345 to 139,406 rows.
#: Rationale per file, and the rule families the selection fires: `specs/sample-corpus.md` §8.
MINUTE = [
    "data/minute/CME/ES/ESZ25.parquet",     # the oracle pair; expires 2025-12-19 in window
    "data/minute/CFE/VX/VXZ25.parquet",     # CFE; the off-tick settlement case
    "data/minute/ICEUS/SB/SBK26.parquet",   # ICE; the 02:30-11:59 short session
    "data/minute/CBOT/ZC/ZCH26.parquet",    # CBOT grains; the two-window session
    "data/minute/CBOT/ZN/ZNZ25.parquet",    # the 1/64 tick lattice
    "data/minute/NYMEX/CL/CLG26.parquet",   # NYMEX; sparsest minute coverage
    "data/minute/COMEX/GC/GCH26.parquet",   # COMEX; smallest useful minute file
    "data/minute/CME/SR3/SR3G26.parquet",   # rate contract; 345 rows, for fast tests
]

#: Roughly what the curated fetch costs, for the sentence shown before anything downloads.
#: Approximate on purpose: an exact figure would have to be maintained against the vendor.
APPROX_MB = 16


class FetchFailed(RuntimeError):
    """The corpus could not be fetched, with a sentence saying why.

    Distinct from a programming error: no network, a moved revision and a proxy that blocks
    Hugging Face are all ordinary conditions on a reviewer's laptop, and each deserves an
    explanation in place rather than a traceback (`plans/07-demo-corpus.md` done-when 1).
    """


@dataclass(frozen=True)
class CorpusDescription:
    """What a fetch would download, for a caller that has to ask permission first."""

    repo: str
    revision: str
    url: str
    approx_mb: int
    minute_files: int
    licence_note: str


def describe_corpus(*, all_minute: bool = False) -> CorpusDescription:
    """The disclosure text's raw material. No network call — this is what we are *about* to do."""
    return CorpusDescription(
        repo=REPO,
        revision=REVISION,
        url=f"https://huggingface.co/datasets/{REPO}",
        approx_mb=104 if all_minute else APPROX_MB,
        minute_files=40 if all_minute else len(MINUTE),
        licence_note=(
            "The publisher grants no licence: the dataset is public and ungated, so "
            "downloading it for evaluation is plainly intended, but nothing authorises "
            "redistribution. Loupe never commits these files."
        ),
    )


@dataclass
class FetchReport:
    """What one fetch did, returned rather than printed so a UI can render it."""

    dest: pathlib.Path
    downloaded: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    checksum_failures: list[str] = field(default_factory=list)

    @property
    def files(self) -> int:
        return len(self.downloaded) + len(self.already_present)

    @property
    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.dest.rglob("*") if p.is_file())


def get(rel: str, *, dest: pathlib.Path = DEST) -> pathlib.Path:
    """Download one file if it is not already here. Idempotent: a partial run resumes."""
    out = dest / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    try:
        with urllib.request.urlopen(f"{BASE}/{rel}", timeout=120) as response:
            payload = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise FetchFailed(
            f"Could not download {rel} from {BASE}. {exc}. The corpus is fetched from "
            "Hugging Face on demand and is never bundled, so this needs a working connection "
            "once."
        ) from exc
    # Write whole rather than streaming: a half-written file that `get` would later treat as
    # present is worse than a failed download, because the next run skips it silently.
    out.write_bytes(payload)
    return out


def _paths_of(frequency: str, *, dest: pathlib.Path) -> list[str]:
    with get("files.csv", dest=dest).open(newline="") as handle:
        return [
            row["path"] for row in csv.DictReader(handle) if row["frequency"] == frequency
        ]


def daily_paths(*, dest: pathlib.Path = DEST) -> list[str]:
    """Every daily file. All 40 cost 1.02 MB and give the complete oracle."""
    return _paths_of("daily", dest=dest)


def all_minute_paths(*, dest: pathlib.Path = DEST) -> list[str]:
    return _paths_of("minute", dest=dest)


def verify(*, dest: pathlib.Path = DEST) -> list[str]:
    """Files on disk that disagree with the vendor's SHA-256 manifest, by name."""
    manifest = dest / "checksums.sha256"
    if not manifest.exists():
        return []
    want: dict[str, str] = {}
    for line in manifest.read_text().splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            want[name.strip()] = digest

    bad: list[str] = []
    for path in dest.rglob("*"):
        rel = str(path.relative_to(dest))
        if not path.is_file() or rel not in want or rel in STALE_IN_MANIFEST:
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != want[rel]:
            bad.append(rel)
    return bad


def fetch_corpus(
    *,
    dest: pathlib.Path = DEST,
    all_minute: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> FetchReport:
    """Fetch the metadata, every daily file and the curated (or every) minute file.

    `on_progress(path, done, total)` is called before each file so a caller can draw a bar.
    Nothing is printed here: a function that printed could not be used by the UI, and a
    function that returned nothing could not be used by the CLI.
    """
    report = FetchReport(dest=dest)
    for rel in META:
        (report.already_present if (dest / rel).exists() else report.downloaded).append(rel)
        get(rel, dest=dest)

    minute = all_minute_paths(dest=dest) if all_minute else MINUTE
    wanted: Iterable[str] = [*daily_paths(dest=dest), *minute]
    total = len(list(wanted))
    for index, rel in enumerate(wanted, start=1):
        if on_progress is not None:
            on_progress(rel, index, total)
        (report.already_present if (dest / rel).exists() else report.downloaded).append(rel)
        get(rel, dest=dest)

    report.checksum_failures = verify(dest=dest)
    return report
