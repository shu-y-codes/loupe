# 08 — Ingest chrome

**Goal.** One sidebar ingest path: Load demo data from the sample directory. No file
uploader. After a load, the sidebar lists what was ingested and marks the files that ran as
CSV.

**Status.** pending

Written 2026-09-07, split out of the README walkthrough (again). Slice 7 shipped the fetch,
the conversion and the two buttons; the sidebar still offers **Upload files** beside them, and
it does not show which files landed. [09-readme-walkthrough.md](09-readme-walkthrough.md)
describes what a reviewer sees — write that after this chrome exists, not against today's
widget.

Do not reopen [07-demo-corpus.md](07-demo-corpus.md). Fetch, conversion and injection stay as
they are. This slice is the chrome around them, and the spec that makes that chrome law.

## The change

The UI spec still says the sidebar holds persona, upload, and the date filter, and the page
wireframe is `[ Upload files ]` plus capability preview
(`specs/loupe-ui-design.md`). **Load demo data is not on that wireframe at all** — only locked
decision 9 names it. After slice 7 those two truths sit on the same sidebar, and a reviewer
can still drag a file in.

Replace the uploader with the demo load; show the loaded files; mark the conversions. Arbitrary
CSV/Parquet ingest remains an API path (`specs/api-contract.md` §4). The UI stops being a
second way to do the same thing.

## Done when

1. **The spec says this before the widgets do.** First done-when, as for every slice.

   - `specs/loupe-ui-design.md` — sidebar inventory, wireframe, empty state. **Load demo data**
     is chrome here, not only a sentence in the solution brief. The file list and the CSV mark
     are named (what the list is, when it appears, that it is inventory not a second ingest
     control).
   - `specs/loupe-solution-design.md` §12 — drop "sidebar (persona, trade dates, upload)" and
     the upload → preview → confirm journey as the v1 UI path. One line in §17 so the order
     matches `plans/`. §16's "capability-aware upload" checkbox follows whatever §12 now says.
   - **Capability preview.** The panel that hosted it is going away. Write the decision in §4
     / §12 so they do not disagree: disclosed in place after load, or UI-absent and API-only.
     `POST /v1/ingest/preview` stays either way.
   - `specs/sample-corpus.md` **only if** the highlight set is not the conversions §8 already
     names (two of eight minute files, earliest by `first_timestamp_ms` and smallest by
     `row_count`, replacing their Parquet in the load). Do not pick a third file, and do not
     collapse to one, without amending that sentence first.

2. **No Upload files widget.** `st.file_uploader`, Confirm upload, and the preview panel leave
   the sidebar. Empty-state copy that says "upload from the sidebar" goes with them
   (`src/loupe/ui/summary.py`, the fetch-failed caption in `src/loupe/ui/demo.py`). Offline is
   still an answer in place; it no longer points at a widget that is not there.

3. **The sidebar lists what was ingested**, after a successful load, from
   `GET /v1/ingest/batches` (`specs/api-contract.md` §4). That is the batch list the API
   already returns — filename, format, origin — not a directory walk. A widget that reads
   `data/samples/` would break the layer table (solution brief §6; slice 7 already kept the
   demo on the HTTP path). Converted rows show as CSV; the Parquet they replaced is not in
   the load (`specs/sample-corpus.md` §8).

4. **Converted files are marked in that list** so a reviewer can see the CSV half of "accept
   CSV or Parquet" without opening a directory. Key off `file_format` / suffix plus
   `origin = demo`, not off "any CSV": after injection the planted file is also a CSV, and
   that mark is already the synthetic disclosure (slice 7 done-when 5), not this one.

5. **Tests.** `AppTest`: the uploader is absent; after a stubbed load the list is present and
   the converted rows are distinguished from the Parquet rows; the synthetic mark is still
   not this mark. Do not make CI fetch Hugging Face.

## Files

- `specs/loupe-ui-design.md` — the chrome.
- `specs/loupe-solution-design.md` §12, §16, §17; §4 if preview leaves the UI.
- `src/loupe/ui/chrome.py` — the uploader comes out.
- `src/loupe/ui/demo.py` — the list and the mark sit with the demo panel; fetch-failed copy.
- `src/loupe/ui/summary.py` — empty state.
- `src/loupe/ui/client.py` — the page already needs a batches list call if it does not have
  one.
- `tests/ui/test_demo_panel.py`, `tests/ui/test_pages.py`.

## Attach

- `specs/loupe-ui-design.md` (current sidebar law and wireframe)
- `specs/loupe-solution-design.md` §3 decisions 8–9, §4 (capability model), §12 (chrome)
- `specs/sample-corpus.md` §8 (which files convert, replacement not join)
- `specs/api-contract.md` §4 (`GET /v1/ingest/batches`; preview and POST stay)
- [07-demo-corpus.md](07-demo-corpus.md) — fetch, convert, two buttons; do not reopen
- [05-ui.md](05-ui.md) — the chrome that shipped the uploader; stays done

## Non-goals

Retiring `POST /v1/ingest/preview` or `POST /v1/ingest/batches`. Changing which files are
fetched or converted. The rest of `_notes/dev/markups.txt` (Risk trust line, Specifics
aggregation, chart widths, Analyst dropped-files). README prose —
[09-readme-walkthrough.md](09-readme-walkthrough.md).
