# Loupe

Lightweight app for **data quality** and **market insights** from historical futures data.

Stack: Python, Streamlit, FastAPI, DuckDB.

## Design

Committed docs: `specs/` (normative) and `plans/` (execution). `_notes/` is a local
research scrapbook (gitignored; not in clones). Founding notes are locked historical.

- **[specs/](specs/)** — living product and calculation specs (normative)
- **[specs/loupe-solution-design.md](specs/loupe-solution-design.md)** — implementation brief
- **[specs/loupe-ui-design.md](specs/loupe-ui-design.md)** — UI / personas / wireframes
- **[plans/](plans/)** — slice sequence and done-when
- **[specs/data-model.md](specs/data-model.md)** — DuckDB schema and its invariants
- **[specs/analytics-semantics.md](specs/analytics-semantics.md)** — trade date, grid, OHLCV, VWAP
- **[specs/dq-rules-and-scoring.md](specs/dq-rules-and-scoring.md)** — rule catalogue and DQ score
- **[specs/sample-corpus.md](specs/sample-corpus.md)** — what the sample holds, and the oracle

## Setup

Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                              # create the venv and install
git config core.hooksPath .githooks  # ruff + pytest on every commit (matches CI)
uv run pytest                        # tests that need the corpus skip without it
uv run ruff check .
```

You do not need to fetch data to start — **Load demo data** in the running app does it. To do
it from a terminal instead:

```bash
uv run python tools/fetch_samples.py --csv   # ~16 MB of vendor sample data, gitignored
```

The sample corpus carries **no redistribution licence**, so it is fetched and never committed
(`specs/sample-corpus.md` §1). Nothing fetches **during ingest** — reading a file touches the
filesystem and the database and nothing else (locked decision 9). The download happens when a
person asks for it, by running that script or by pressing that button, and the app says what it
is about to download and from where before it does.

## Running the app

Two processes: the API serves `/v1`, the UI talks to it over HTTP. Keeping them apart is
what makes the thin-client boundary real rather than asserted
(`specs/loupe-solution-design.md` §6).

```bash
uv run uvicorn loupe.api.app:bootstrapped_app --factory   # http://127.0.0.1:8000/v1
uv run streamlit run src/loupe/ui/app.py                  # http://localhost:8501
```

**That is the whole setup.** On a store that does not exist yet, the first start creates it,
applies the schema, and seeds both the reference data and the rule catalogue — so the two
commands above take a fresh clone to a page you can upload a file to. Nothing to run in a REPL
first.

`loupe.api.app:create_app` is the same app without that: it opens the store and creates
nothing, which is what you want when a store already exists and an empty one should be reported
rather than silently manufactured. `GET /v1/health` says which state you are in through
`schema_applied` and `rules_seeded`, and the UI reads it before offering you anything.

The UI reads `LOUPE_API_URL` and falls back to `http://127.0.0.1:8000/v1`, so pointing it at
another host needs no code change:

```bash
LOUPE_API_URL=http://localhost:9000/v1 uv run streamlit run src/loupe/ui/app.py
```

`GET /v1/docs` serves the OpenAPI the app generates. On an empty store the page invites an
upload; the sidebar previews the file, discloses what it cannot support (a daily-only file
gets bars and quality but no 15-minute VWAP), and only then commits it.

## The demo, in two clicks

**Load demo data** fetches 40 daily files and eight minute files — all six exchanges, all three
session profiles, both odd tick regimes — and loads them. Two of the eight are converted from
Parquet to CSV first, so both accepted formats actually run: the earliest file by
`first_timestamp_ms` and the smallest by `row_count`, picked from the vendor's own manifest
rather than by name. The whole thing takes about three quarters of a minute — mostly parsing —
and every finding it produces is real.

**Inject demo defects** is a second, separate click, and the separation is the point. The
vendor corpus is close to defect-free — 17 of 37 rules fire on it and 20 cannot
(`specs/sample-corpus.md` §8.1) — so the injector plants nine labelled defects to show six that
are otherwise unreachable, including a key conflict, an inverted bar and a negative volume. It
writes a defective *copy*, refuses to touch the vendor file, and records a manifest naming the
rule each defect should trip.

**While any of it is loaded the app says so, on every screen and every rerun.** A banner names
how many records are synthetic, the manifest is one expander away, and **Remove demo defects**
puts the clean file back. A planted defect that a reader could mistake for a vendor one would
make every number in the app unciteable, which is the one thing this demo may not trade away
for convenience.

The injector is also available from a terminal:

```bash
uv run python -m loupe.demo.injection tests/fixtures/injection_base.csv --out /tmp/demo.csv
```

`tests/demo/` runs the real engine over an injected file and asserts the findings agree with the
manifest, which is what makes it a test asset rather than a prop.

## Status

Slices 1-6 are done: DuckDB schema, reference seed, upload preview and synchronous ingest;
the quality engine — 38 rules seeded as rows, default cleaning, and the DQ score; daily bars,
VWAP and the raw/clean compare; the FastAPI `/v1` surface; the Streamlit UI with its three
personas; and cross-frequency reconciliation with the pattern and suggestion reports. The
README walkthrough follows — see **[plans/](plans/)**.

**Reconciliation needs both grains.** `REC.*` compares vendor daily bars against bars derived
from the minute tape, so it runs only where a contract holds both — and where it does, the
score is a weighted mean over six dimensions rather than five. Every score states which
dimensions were in scope and what it was renormalised by, because the two are not the same
measurement (`specs/dq-rules-and-scoring.md` §11.3).

```python
from pathlib import Path
from loupe.data import apply_schema, connect, load_file, preview_file, seed_reference
from loupe.quality import RunScope, assess, scoped, seed_quality, worklist

con = connect()                       # data/loupe.duckdb; LOUPE_DB overrides
apply_schema(con)
seed_reference(con, manifest=Path("data/samples/files.csv"))
seed_quality(con)                     # rules and score weights are rows, not code

preview = preview_file(con, "data/samples/data/minute/CME/ES/ESZ25.parquet")
print(preview.frequency, preview.source_timezone.value, preview.session_boundary)
print({name: cap.available for name, cap in preview.capabilities.items()})

result = load_file(con, preview.path, preview=preview)
print(result.status, result.rows_accepted, result.rows_rejected)

run, scores = assess(con, batch_id=result.batch_id)
print(run.findings_by_rule, run.cleaning, run.refusals)
for score in scores:
    print(score.overall, score.scope_signature, score.as_json()["dimensions"])
    with scoped(con, RunScope(batch_id=result.batch_id)):   # what to fix first
        for entry in worklist(con, run.run_id, score.contract_id, score.frequency)[:3]:
            print(entry.rule_id, entry.rank, entry.score_if_resolved)
```

The score is a 0-100 quality index where higher is better, and it is a **navigation tool
rather than a grade**: show the per-dimension breakdown first, state the denominator, and
say which dimensions were in scope (`specs/dq-rules-and-scoring.md` §11.5).

