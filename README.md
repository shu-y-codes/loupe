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
uv run python tools/fetch_samples.py # ~15.5 MB of vendor sample data, gitignored
uv run pytest                        # tests that need the corpus skip without it
uv run ruff check .
```

The sample corpus carries **no redistribution licence**, so it is fetched, never committed
(`specs/sample-corpus.md` §1). Nothing in the application fetches at runtime.

## Running the app

Two processes: the API serves `/v1`, the UI talks to it over HTTP. Keeping them apart is
what makes the thin-client boundary real rather than asserted
(`specs/loupe-solution-design.md` §6).

```bash
uv run uvicorn loupe.api.app:create_app --factory   # http://127.0.0.1:8000/v1
uv run streamlit run src/loupe/ui/app.py            # http://localhost:8501
```

The UI reads `LOUPE_API_URL` and falls back to `http://127.0.0.1:8000/v1`, so pointing it at
another host needs no code change:

```bash
LOUPE_API_URL=http://localhost:9000/v1 uv run streamlit run src/loupe/ui/app.py
```

**A new store needs two steps, not one.** `bootstrap` applies the schema and seeds reference
data; the rule catalogue is seeded separately, because rules are rows and which rules a
deployment wants is its decision. Until `seed_quality` has run, an upload is refused and
`GET /v1/health` says `rules_seeded: false` — which is what the UI reads before it offers you
anything. The snippet below does both.

`GET /v1/docs` serves the OpenAPI the app generates. On an empty store the page invites an
upload; the sidebar previews the file, discloses what it cannot support (a daily-only file
gets bars and quality but no 15-minute VWAP), and only then commits it.

## Demo defects

The minute corpus is effectively defect-free (`specs/sample-corpus.md` §7.1), so a demo leads
with the **real** findings it does contain — the timezone trap, settlements outside the traded
range, off-tick settlements. For the defect types it happens not to contain there is a
labelled injector, which writes a defective *copy* and a ground-truth manifest beside it:

```bash
uv run python -m loupe.demo.injection tests/fixtures/injection_base.csv --out /tmp/demo.csv
```

It refuses to write over its source and records the SHA-256 of both files. A corrupted sample
nobody labelled is indistinguishable from a vendor defect, and it would end up quoted in a
spec. `tests/demo/` runs the real engine over an injected file and asserts the findings agree
with the manifest, which is what makes it a test asset rather than a prop.

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

