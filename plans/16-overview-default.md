# 16 — Overview default landing

**Goal.** A cold app session lands on **Overview**. The sidebar remains
**Overview | Review**, and selecting an Overview row still opens Review.

**Status.** done — 2026-09-08

Written 2026-09-08 as a product correction after slices 13–15. Do not reopen those
done plans; amend the specs and routing default in place.

## Done when

1. UI and solution specs name Overview as the default landing.
2. Missing or invalid destination state resolves to Overview.
3. Overview-row click-through still resolves to Review.
4. App tests explicitly seed Review when testing Review; a cold-session test lands
   on Overview.

## Files

- `specs/loupe-ui-design.md`
- `specs/loupe-solution-design.md`
- `src/loupe/ui/chrome.py`
- `tests/ui/conftest.py`, `tests/ui/test_overview.py`
- `plans/README.md`
