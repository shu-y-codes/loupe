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
- **[specs/dq-rules-and-scoring.md](specs/dq-rules-and-scoring.md)** — rule catalogue and DQ score
- **[specs/sample-corpus.md](specs/sample-corpus.md)** — what the sample holds, and the oracle

## Setup

Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                              # create the venv and install
git config core.hooksPath .githooks  # ruff check on every commit (matches CI)
uv run python tools/fetch_samples.py # ~15.5 MB of vendor sample data, gitignored
uv run pytest                        # tests that need the corpus skip without it
uv run ruff check .
```

The sample corpus carries **no redistribution licence**, so it is fetched, never committed
(`specs/sample-corpus.md` §1). Nothing in the application fetches at runtime.

## Status

Slices 1 and 2 are done: DuckDB schema, reference seed, upload preview and synchronous
ingest; then the quality engine — 30 rules seeded as rows, default cleaning, and the DQ
score. Insights, API and UI follow — see **[plans/](plans/)**.

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

