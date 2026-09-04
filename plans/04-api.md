# 04 — API

**Goal.** FastAPI `/v1` matching the promoted contract. Handlers call quality / insights /
data; no duplicated business maths.

**Status.** pending

## Done when

1. Promote `_notes/cursor/05-api-contract.md` → `specs/api-contract.md`. Do not code
   from the note.
2. Base path `/v1`. Sync writes return finished results. UTC on the wire;
   `basis=raw|clean`; `frequency=minute|daily`; RFC 7807 errors.
3. Areas in the solution brief §11 exist: health/reference, ingest preview + batches
   (201, `file_hash` 409), analytics bars/VWAP/compare, DQ summary/metrics/findings
   (GET findings read-only), insights patterns/suggestions (GET only).
4. VWAP on daily-only returns a structured frequency-unavailable error.
5. OpenAPI is generated from the app; `TestClient` covers shapes.

## Files to create

- `api/` — routes, Pydantic models
- `tests/api/` — contract tests

v1: no `POST .../review`, no suggestion apply/dismiss (extensions).

## Tests

Happy-path ingest 201; duplicate hash 409; findings GET is read-only; VWAP refused
in place for daily-only; RFC 7807 on validation errors.

## Attach

- `specs/loupe-solution-design.md` §11
- After promote: `specs/api-contract.md`
- Research until promoted: `_notes/cursor/05-api-contract.md`

## Non-goals

Streamlit, apply/override, async job table, auth/RBAC.
