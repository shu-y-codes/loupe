#!/usr/bin/env python3
"""Fetch the development sample corpus into the gitignored `data/samples/`.

The data is **not** redistributed with this repository: the publisher grants no licence
(`specs/sample-corpus.md` §1). Run this once for local development; nothing in the
application fetches at runtime.

Pinned to a revision and verified against the vendor's own SHA-256 manifest. The list of
wanted files is data, so widening the sample is a one-line edit rather than a code change.

    python tools/fetch_samples.py [--all-minute]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import sys
import urllib.request

REPO = "lynx1231/historical-futures-data-sample"
# Pinned revision, so a re-run fetches the same corpus the specs were measured against.
REVISION = "29efdfa21c5a5b2d7aa306397385cf116e011559"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}"
DEST = pathlib.Path(__file__).resolve().parents[1] / "data" / "samples"

META = [
    "README.md",
    "SOURCE_NOTICE.md",
    "catalog.csv",
    "files.csv",
    "schema.json",
    "checksums.sha256",
    "dataset.json",
]

# The vendor's own README.md and dataset.json were edited after the manifest was generated,
# so their checksums are known-stale. Reporting a failure the user cannot act on is worse
# than skipping them.
STALE_IN_MANIFEST = {"README.md", "dataset.json"}

# One minute file per root: all six exchanges, all three session profiles, both odd tick
# regimes, a contract expiring inside the window, and sizes from 345 to 139,406 rows.
# Rationale per file: specs/sample-corpus.md §8.
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


def get(rel: str) -> pathlib.Path:
    """Download one file if it is not already here. Idempotent: a partial run resumes."""
    out = DEST / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        with urllib.request.urlopen(f"{BASE}/{rel}", timeout=120) as response:
            out.write_bytes(response.read())
    return out


def daily_paths() -> list[str]:
    """Every daily file. All 40 cost 1.02 MB and give the complete oracle."""
    with get("files.csv").open(newline="") as handle:
        return [row["path"] for row in csv.DictReader(handle) if row["frequency"] == "daily"]


def all_minute_paths() -> list[str]:
    with get("files.csv").open(newline="") as handle:
        return [row["path"] for row in csv.DictReader(handle) if row["frequency"] == "minute"]


def verify() -> int:
    """Check what is on disk against the vendor SHA-256 manifest."""
    manifest = DEST / "checksums.sha256"
    want: dict[str, str] = {}
    for line in manifest.read_text().splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            want[name.strip()] = digest

    bad = 0
    for path in DEST.rglob("*"):
        rel = str(path.relative_to(DEST))
        if not path.is_file() or rel not in want or rel in STALE_IN_MANIFEST:
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != want[rel]:
            print(f"CHECKSUM MISMATCH: {rel}", file=sys.stderr)
            bad += 1
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-minute",
        action="store_true",
        help="fetch all 40 minute files (104 MB) instead of the curated eight (14 MB)",
    )
    args = parser.parse_args()

    for rel in META:
        get(rel)
    minute = all_minute_paths() if args.all_minute else MINUTE
    for rel in daily_paths() + minute:
        print(f"  {rel}")
        get(rel)

    bad = verify()
    total = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file())
    print(f"{total / 1e6:.1f} MB in {DEST}; {bad} checksum failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
