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

Slice 1 (data ingest) is done: DuckDB schema, reference seed, upload preview and synchronous
ingest. Quality, insights, API and UI follow — see **[plans/](plans/)**.

```python
from pathlib import Path
from loupe.data import apply_schema, connect, load_file, preview_file, seed_reference

con = connect()                       # data/loupe.duckdb; LOUPE_DB overrides
apply_schema(con)
seed_reference(con, manifest=Path("data/samples/files.csv"))

preview = preview_file(con, "data/samples/data/minute/CME/ES/ESZ25.parquet")
print(preview.frequency, preview.source_timezone.value, preview.session_boundary)
print({name: cap.available for name, cap in preview.capabilities.items()})

result = load_file(con, preview.path, preview=preview)
print(result.status, result.rows_accepted, result.rows_rejected)
```

