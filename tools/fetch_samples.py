#!/usr/bin/env python3
"""Fetch the development sample corpus into the gitignored `data/samples/`.

The data is **not** redistributed with this repository: the publisher grants no licence
(`specs/sample-corpus.md` §1). Nothing in the application fetches *during ingest*; the corpus
arrives when a person asks for it, either by running this script or by pressing **Load demo
data** in the UI (locked decision 9).

Both doors run the same code. The pinned revision, the checksum handling and the curated file
list live in `loupe.demo.fetch`, and this script is the terminal front end for it — a second
implementation here would be free to drift from the one the button uses.

    python tools/fetch_samples.py [--all-minute] [--csv]
"""

from __future__ import annotations

import argparse
import sys

from loupe.demo.corpus import convert_earliest_to_csv
from loupe.demo.fetch import DEST, FetchFailed, describe_corpus, fetch_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-minute",
        action="store_true",
        help="fetch all 40 minute files (104 MB) instead of the curated eight (14 MB)",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="also write a CSV copy of the earliest minute file, so both accepted formats "
        "have an example on disk",
    )
    args = parser.parse_args()

    described = describe_corpus(all_minute=args.all_minute)
    print(f"{described.url} @ {described.revision[:12]} (~{described.approx_mb} MB)")
    print(f"  {described.licence_note}")

    try:
        report = fetch_corpus(
            all_minute=args.all_minute,
            on_progress=lambda rel, done, total: print(f"  [{done}/{total}] {rel}"),
        )
    except FetchFailed as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.csv:
        converted = convert_earliest_to_csv()
        print(f"  csv copy: {converted.csv_path.relative_to(DEST.parent)} "
              f"({converted.rows:,} rows from {converted.source_path.name})")

    for name in report.checksum_failures:
        print(f"CHECKSUM MISMATCH: {name}", file=sys.stderr)
    print(
        f"{report.total_bytes / 1e6:.1f} MB in {report.dest}; "
        f"{report.files} file(s), {len(report.checksum_failures)} checksum failure(s)"
    )
    return 1 if report.checksum_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
