# 07 — Demo corpus and first run

**Goal.** A reviewer clones, runs two commands, clicks once, and is looking at real findings on
real vendor data. A second, separate click adds labelled synthetic defects — and the app never
stops saying it did.

**Status.** done — 2026-09-07

Written 2026-09-07, split out of the README walkthrough once it was clear the prose depends on
it: there is nothing to describe until the corpus, the CSV file and the buttons exist.
[08-readme-walkthrough.md](08-readme-walkthrough.md) follows this slice, not alongside it.

## The two things this slice is balancing

**Make it easy.** The exercise is judged by someone who has minutes, not an afternoon. Today
the quickstart is three steps and one of them is a script they have to know to run; a fetched
corpus is 15.5 MB they will not have.

**Keep it honest.** The demo strategy is *real findings first, injected defects second and
labelled* (`specs/loupe-solution-design.md` §9). The moment those two are indistinguishable on
screen, every number in the app becomes unciteable — which is the failure
`src/loupe/demo/injection.py` already names in its own docstring: "a corrupted sample that
nobody labelled is indistinguishable from a vendor defect, and it would end up quoted in a
spec." Ease that costs honesty is not a trade this slice may make.

## Done when

1. **A "Load demo data" button, and it is sanctioned rather than invented.** Locked decision 9
   already names it: *"Sample data is fetched at setup time, via a pinned script and optionally
   a 'Load demo data' button — never as a runtime dependency during ingest."* The constraint is
   narrower than the README's current sentence implies — what is forbidden is **ingest** reaching
   the network, not the app offering a fetch. Ingest still reaches nothing.

   Four properties, each of which is a way this goes wrong:

   - **Consent before bytes.** §1 is blunt that nothing authorises redistribution and that
     "other" with no text is not permission. The button therefore says what it is about to
     download and from where *before* it downloads, so the decision sits with the person
     clicking rather than with us.
   - **Resumable and idempotent**, which `tools/fetch_samples.py` already is. A second click on
     a half-fetched corpus finishes it; it does not start again or duplicate a batch.
   - **Offline is an answer, not a traceback.** A laptop with no network, a 404, a checksum
     mismatch — each is explained in place, the way the VWAP panel explains a refusal.
   - **Reuse the pinned script.** The revision, the checksum verification and the two known-stale
     manifest entries are already solved in `tools/`. The button calls that logic; it does not
     grow a second downloader that can drift from it.

2. **One Parquet becomes CSV, and the choice is data-driven.** The exercise requires accepting
   both formats and `specs/api-contract.md` §9 puts "Accept CSV or Parquet" in the traceability
   table — but today only `tests/` ever loads a CSV, so a reviewer following the walkthrough
   would never see one. Convert the **earliest** file by `first_timestamp_ms`, which `files.csv`
   already carries, so the selection is reproducible rather than a name someone typed.

   The conversion is derived data and is gitignored like everything else under `data/`. It is
   also a real oracle, and done-when 7 spends it.

3. **The curated selection, checked against the rule catalogue rather than assumed.** The
   existing eight-file `MINUTE` list is already curated with per-file rationale (§8): six
   exchanges, three session profiles, both odd tick regimes, a contract expiring inside the
   window, sizes from 345 to 139,406 rows. That is curation for **ingest** diversity, and it is
   good.

   What is *not* recorded anywhere is which **rule families** the selection actually fires. Run
   it and write the answer into §8, so slice 8's walkthrough can cite a measured list instead of
   guessing. Expect the answer to be partial, and expect that to be correct rather than a
   shortfall: §7.1 has the minute config effectively defect-free and §7.5 says the defects that
   exist are natural, not planted. **No vendor file in this repository will demonstrate
   `UNQ.KEY_CONFLICT` or `TIM.TIMEZONE_MISALIGNED`, because nothing is wrong with them.** Hunting
   for one is the wrong response; done-when 4 is the right one, and the gap belongs in slice 8's
   limitations.

4. **"Inject demo defects" is a separate button.** Not a step inside Load demo data, and not a
   checkbox on it. A reviewer has to be able to see real findings on real vendor data *and know
   that is what they are looking at*, before anything synthetic exists in the store. Two clicks,
   in that order, are the demo.

   It writes a derived copy under `data/demo/` and never touches a fetched sample — the injector
   already refuses to overwrite its source, and that refusal is now load-bearing rather than
   defensive.

5. **The disclosure is persistent, not a notification.** This is the requirement the slice turns
   on, and the reason it is stated separately from done-when 4.

   A toast at injection time is gone on the next rerun. Streamlit reruns constantly; a reviewer
   who clicks the button, then changes persona, then sorts the inventory, is three interactions
   away from a screen full of findings with nothing anywhere saying that nine of them were
   manufactured. **The property to hold: a reader who arrives mid-session, or reloads, still
   knows.** Candidate mechanisms, to be chosen in the build —

   - mark the batch, so provenance travels with the records rather than with the session;
   - badge every contract in the inventory whose records came from an injected file;
   - a standing banner for as long as any injected batch is loaded.

   The first is the most honest because it survives a restart and a re-run, and the third is the
   hardest to miss; they are not exclusive. Whichever is built, **no surface may report a score,
   a finding count or a pattern drawn from injected data without it.**

   The manifest is the evidence and belongs where the reviewer is, not only on disk: nine rows
   saying which rule each planted defect should trip, reachable from the UI.

6. **A way back.** Injected data must be removable without deleting the store — `POST
   /v1/ingest/batches/{id}` purge already exists (`specs/api-contract.md` §4). A demo that can
   only be un-poisoned by `rm data/loupe.duckdb` is a demo people will be afraid to click.

7. **The CSV is tested as an oracle, not just as a file.** The same vendor file in two formats
   must produce identical `stage.market_record` content — same rows, same `ts_utc`, same
   `trade_date`. That is a far stronger claim than "the loader did not crash on a CSV", and it
   is the actual content of the "Accept CSV or Parquet" requirement: not that both parse, but
   that both *mean the same thing*.

## Files

- `tools/fetch_samples.py` — the curated list, and the Parquet→CSV conversion, factored so the
  UI can call it rather than shelling out.
- `src/loupe/demo/corpus.py` (new) — fetch → convert → ingest, and separately, inject. The
  orchestration belongs beside `injection.py` in the package that already exists for demo
  assets, not in a widget and not in `data/`.
- `src/loupe/ui/` — the two buttons and the standing disclosure.
- `specs/sample-corpus.md` §8 — the selection rationale, the CSV file, and the measured rule
  coverage from done-when 3.
- `README.md` — the quickstart becomes two commands and a click. **Fix the overstated sentence
  while there:** "Nothing in the application fetches at runtime" is wrong once the button exists
  and was always imprecise; §1 and locked decision 9 both say the real constraint, which is that
  nothing fetches *during ingest*.

## Tests

Integration tier (`tests/integration/`), because this is a seam question and that is the tier
that owns seams.

- **The CSV/Parquet oracle** of done-when 7, on a committed fixture pair rather than a fetched
  file, so it runs without the corpus.
- **The disclosure survives a rerun.** `AppTest` over an injected store: run the page twice and
  assert the marker is present both times. A test that only checks the moment of injection would
  pass against exactly the defect this slice exists to prevent.
- **Injection still refuses a pristine sample**, asserted through the button path and not only
  through `inject()` directly.
- **The fetch path degrades**: no network is explained rather than raised. Stub the transport;
  do not make CI reach Hugging Face.
- Anything needing the real corpus stays `@pytest.mark.samples` and skips without it (§6.5).

## Attach

- `specs/loupe-solution-design.md` §3 decision 9 (the button, named), §9 (demo defects: real
  findings first, injection labelled)
- `specs/sample-corpus.md` §1 (no redistribution grant), §7.1 and §7.5 (the corpus is clean, and
  its defects are natural), §8 (the committed subset and why each file is in it)
- `specs/api-contract.md` §4 (ingest and purge), §9 (the CSV-or-Parquet requirement this closes)
- `src/loupe/demo/injection.py` — the manifest shape and the refusals already built

## Non-goals

Committing vendor data, in any form, under any size. Fetching during ingest. Making the injected
corpus the default state of the app. Widening the catalogue to fire on files we chose — the
selection demonstrates the rules that exist; it does not get to define them.
