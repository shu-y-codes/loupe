# 01 — Data ingest

**Goal.** DuckDB schema, preview/load, reference seed from sample, idempotent ingest
(`file_hash` → 409).

**Status.** done — 2026-09-05

## Done when

1. ✅ Promoted `_notes/cursor/03-data-model.md` → `specs/data-model.md` and the sample /
   oracle claims from `_notes/cursor/06-sample-data.md` → `specs/sample-corpus.md`. Both
   notes marked superseded.
2. ✅ `src/loupe/data/`: connection factory, `ddl.sql` for the four schemas, reference seed
   (8 products, 64 tick rows, 40 contracts from `files.csv`, generated session calendar).
3. ✅ Preview infers timezone / interval / frequency and the capability matrix; load is
   synchronous; duplicate `file_hash` raises `DuplicateFileError` (the API maps it to 409 in
   slice 4); parse failures → `stage.record_reject` with `STR.*` codes and the batch goes
   `partial`.
4. ✅ Frequency discriminator on every record. Measured on the real pair: 79 collisions on
   `(contract_id, ts_utc)`, 0 with frequency in the key.
5. ✅ `tools/fetch_samples.py` pinned to revision `29efdfa2`; verifies the vendor SHA-256
   manifest (15.5 MB, 0 failures). `data/samples/` gitignored.

## Files created

- `src/loupe/data/` — `connection`, `schema` + `ddl.sql`, `profiles`, `sessions`, `symbols`,
  `reference`, `preview`, `load`, `errors`
- `tools/fetch_samples.py`
- `tests/data/` (128 tests) and `tests/fixtures/` (6 ingest CSVs)
- `pyproject.toml` (uv, Python 3.12, ruff, pytest)

**Spec corrections this slice made**, both validated against the corpus rather than assumed:
`halt_windows` holds intra-session halts only (the CME 16:00–17:00 break falls *between*
sessions, so ES has none and ZC has one), and only New Year's Day and Christmas Day are full
closures — every other US market holiday carries rows and is an early close with an unknown
grid.

HTTP routes wait for [04-api.md](04-api.md); this slice owns the `data` layer.

## Tests

Schema creates; seed rows exist; preview vs known sample headers; second load of the
same file is rejected; unparseable rows land in rejects; daily + minute for one contract
do not collide.

## Attach

- `specs/loupe-solution-design.md` §6–7 (and §10 once `specs/data-model.md` exists)
- Research until promoted: `_notes/cursor/03-data-model.md`, `_notes/cursor/06-sample-data.md`

## Non-goals

Quality engine, bars/VWAP, FastAPI surface, Streamlit, `REC.*`, demo injection.
No Redis, extra DBs, or auth.
