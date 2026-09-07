"""The demo panel: load real vendor data, then — separately — plant labelled defects.

Two buttons, and the separation between them is the whole design. A reviewer has to be able to
see real findings on real vendor data *and know that is what they are looking at* before
anything synthetic exists in the store. Bundling the injection into "Load demo data" would make
every number on the screen ambiguous, which is precisely the failure
`loupe.demo.injection` names in its own docstring: a corrupted file nobody labelled is
indistinguishable from a vendor defect.

**Consent before bytes.** `specs/sample-corpus.md` §1 found no licence grant anywhere in the
vendor package — public and ungated, so downloading it for evaluation is plainly intended, but
nothing authorises redistribution. So the panel says what it is about to download and from
where, and waits. Locked decision 9 permits exactly this ("optionally a 'Load demo data'
button") and forbids the thing that would actually be wrong: fetching *during ingest*. Ingest
still reaches nothing but the filesystem and the database.

**The disclosure is not this module's to forget.** `render_synthetic_notice` reads
`/v1/health`, which the page already calls before it draws anything, so a store holding planted
defects says so on every rerun rather than once at the moment of injection. A toast would be
gone by the time the reviewer changed family.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from loupe.demo.corpus import (
    DEMO_ORIGIN,
    INJECTED_ORIGIN,
    prepare_demo_corpus,
    prepare_injection,
)
from loupe.demo.fetch import FetchFailed, describe_corpus
from loupe.quality.catalogue import strip_family

from .client import ApiProblem, ApiUnavailable, LoupeClient

#: Marks every surface that could otherwise be read as a statement about vendor data.
SYNTHETIC_MARK = "⚠️"

#: Demo CSV rows: format fact, not a defect (`specs/loupe-ui-design.md`).
CONVERTED_MARK = "Converted from Parquet"

#: Ingested-file buckets. Coverage is per contract, not per file frequency.
COVERAGE_BOTH = "Daily + minute"
COVERAGE_DAILY = "Daily-only"
COVERAGE_MINUTE = "Minute-only"
_COVERAGE_ORDER = (COVERAGE_BOTH, COVERAGE_DAILY, COVERAGE_MINUTE)

#: Planted-defect groups. Recurring patterns is not a planted family.
_PLANTED_FAMILY_ORDER = ("gaps", "duplicates", "invalid", "off_strip")
PLANTED_FAMILY_LABEL = {
    "gaps": "Gaps",
    "duplicates": "Duplicates",
    "invalid": "Invalid values",
    "off_strip": "Other (off the strip)",
}


def render_demo(client: LoupeClient, health: dict[str, Any]) -> None:
    """The sidebar panel. Which controls appear follows the state of the store, not a flag."""
    st.sidebar.subheader("Demo data")
    records = int(health.get("records") or 0)
    synthetic = int(health.get("synthetic_batches") or 0)

    if records == 0:
        _render_load(client)
        return

    st.sidebar.caption(f"{records:,} records loaded.")
    _render_ingested_files(client)
    if synthetic:
        _render_remove(client, health)
    else:
        _render_inject(client)


# ------------------------------------------------------------------------ load real data


def _render_load(client: LoupeClient) -> None:
    """Fetch the vendor corpus and ingest it — real data, real findings, nothing planted."""
    described = describe_corpus()
    st.sidebar.caption(
        f"No data yet. Load ~{described.approx_mb} MB of real futures data from the "
        "publisher's Hugging Face dataset. Takes about a minute."
    )
    # Said before the button, not after it: the reader decides whether to download, and they
    # cannot decide without knowing what and from where.
    with st.sidebar.expander("What this downloads"):
        st.write(f"**{described.repo}** at revision `{described.revision[:12]}`")
        st.write(
            f"{described.minute_files} minute files and every daily file, checksum-verified "
            "against the vendor's own manifest."
        )
        st.caption(described.licence_note)

    if not st.sidebar.button("Load demo data", key="load-demo", type="primary"):
        return

    with st.status("Fetching the sample corpus…", expanded=True) as status:
        try:
            corpus = prepare_demo_corpus(
                on_progress=lambda rel, done, total: status.update(
                    label=f"Fetching {done}/{total} · {rel.split('/')[-1]}"
                )
            )
        except FetchFailed as exc:
            # Offline is an answer, not a traceback: the corpus lives on someone else's server
            # and a reviewer's laptop is allowed to have no route to it.
            status.update(label="Could not fetch the corpus", state="error")
            st.write(str(exc))
            st.caption(
                "The app is fully usable without the sample corpus. Try Load demo data again "
                "when you have a network."
            )
            return

        for name in corpus.fetch.checksum_failures:
            st.warning(f"Checksum mismatch on {name}; it was fetched but does not verify.")

        status.update(label=f"Loading {len(corpus.files)} files…")
        loaded = _ingest_all(client, corpus.files, status)
        if loaded is None:
            return

        # One corpus-wide run at the end rather than one per file. Faster, and *correct*: an
        # upload validates its own batch only, so reconciliation cannot be in scope until a run
        # has seen both granularities of a contract (`specs/api-contract.md` §6.4).
        status.update(label="Validating the whole corpus…")
        try:
            client.run_rules()
        except (ApiProblem, ApiUnavailable) as exc:
            status.update(label="Loaded, but the corpus-wide run failed", state="error")
            st.write(str(exc))
            return

        formats = f"{corpus.parquet_files} Parquet, {corpus.csv_files} CSV"
        status.update(label=f"Loaded {loaded} files ({formats})", state="complete")
    st.rerun()


def _ingest_all(client: LoupeClient, files, status) -> int | None:
    """Post each file through the API — the same `POST /v1/ingest/batches` any ingest uses.

    `validate=False` on every upload because the corpus-wide run above supersedes them: running
    the rules 48 times over one batch each, then again over everything, is slower and answers a
    narrower question each time.
    """
    loaded = 0
    for index, demo_file in enumerate(files, start=1):
        status.update(label=f"Loading {index}/{len(files)} · {demo_file.path.name}")
        try:
            client.create_batch(
                demo_file.path.name,
                demo_file.path.read_bytes(),
                validate=False,
                origin=demo_file.origin,
            )
            loaded += 1
        except ApiProblem as problem:
            # A duplicate is not a failure. Re-pressing the button on a half-loaded store
            # should finish the job, which is the same idempotence the fetch already has.
            if problem.status != 409:
                status.update(label=f"Failed on {demo_file.path.name}", state="error")
                st.write(str(problem))
                return None
        except ApiUnavailable as exc:
            status.update(label="No answer from the API", state="error")
            st.write(str(exc))
            return None
    return loaded


def is_demo_csv_conversion(batch: dict[str, Any]) -> bool:
    """CSV that arrived via demo load — converted from Parquet. Not any CSV.

    Key off `file_format` / suffix **plus** `origin = demo`. After injection the planted
    file is also a CSV; that mark is the synthetic disclosure, not this one.
    """
    origin = batch.get("origin")
    fmt = (batch.get("file_format") or "").lower()
    name = (batch.get("filename") or "").lower()
    is_csv = fmt == "csv" or name.endswith(".csv")
    return origin == "demo" and is_csv


def _coverage_label(grains: set[str]) -> str | None:
    held = {grain for grain in grains if grain in {"daily", "minute"}}
    if held == {"daily", "minute"}:
        return COVERAGE_BOTH
    if held == {"daily"}:
        return COVERAGE_DAILY
    if held == {"minute"}:
        return COVERAGE_MINUTE
    return None


def group_batches_by_coverage(
    batches: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group ingested files by **contract** coverage, not the file's own frequency.

    A contract that holds both grains lists both of its files under Daily + minute.
    """
    grains: dict[str, set[str]] = {
        row["contract_id"]: set(row.get("frequencies_available") or [])
        for row in contracts
        if row.get("contract_id")
    }
    for batch in batches:
        freq = batch.get("frequency")
        for cid in batch.get("contracts_detected") or []:
            if cid not in grains or not grains[cid]:
                grains.setdefault(cid, set())
                if freq:
                    grains[cid].add(freq)

    buckets: dict[str, list[dict[str, Any]]] = {label: [] for label in _COVERAGE_ORDER}
    seen: set[str] = set()
    for batch in batches:
        keys: set[str] = set()
        for cid in batch.get("contracts_detected") or []:
            label = _coverage_label(grains.get(cid, set()))
            if label:
                keys.add(label)
        if COVERAGE_BOTH in keys:
            bucket = COVERAGE_BOTH
        elif keys:
            bucket = next(iter(keys))
        else:
            bucket = _coverage_label({batch.get("frequency") or ""})
        if not bucket:
            continue
        bid = str(batch.get("batch_id") or batch.get("filename") or id(batch))
        if bid in seen:
            continue
        seen.add(bid)
        buckets[bucket].append(batch)
    return [(label, rows) for label, rows in buckets.items() if rows]


def group_planted_by_family(
    defects: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group planted manifest rows with the same catalogue map as the cards.

    Recurring patterns is not a planted family. Off-strip injectables (e.g. `TIM.*`)
    land in Other (off the strip), not a fifth card.
    """
    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in _PLANTED_FAMILY_ORDER}
    for row in defects:
        family = strip_family(str(row.get("rule_id") or ""))
        if family not in buckets:
            family = "off_strip"
        buckets[family].append(row)
    return [
        (PLANTED_FAMILY_LABEL[name], rows)
        for name, rows in buckets.items()
        if rows
    ]


def _render_ingested_files(client: LoupeClient) -> None:
    """Inventory of batches in the store — not a second ingest control, not a directory walk."""
    try:
        body = client.batches()
    except (ApiProblem, ApiUnavailable) as exc:
        st.sidebar.caption(f"Could not list ingested files. {exc}")
        return
    try:
        contracts_body = client.contracts()
    except (ApiProblem, ApiUnavailable):
        contracts_body = {"data": []}
    rows = [batch for batch in (body.get("data") or []) if isinstance(batch, dict)]
    if not rows:
        return
    contracts = [
        row for row in (contracts_body.get("data") or []) if isinstance(row, dict)
    ]
    groups = group_batches_by_coverage(rows, contracts)
    with st.sidebar.expander(f":material/folder: {len(rows)} ingested files", expanded=False):
        st.caption("What this store holds — not a directory of downloads.")
        for label, files in groups:
            st.markdown(f"**{label}**")
            for batch in files:
                name = batch.get("filename") or "—"
                fmt = batch.get("file_format") or "—"
                origin = batch.get("origin") or "—"
                line = f"`{name}` · {fmt} · {origin}"
                if is_demo_csv_conversion(batch):
                    line += f" · :blue-badge[{CONVERTED_MARK}]"
                st.markdown(line)


# ------------------------------------------------------------------- plant, and undo it


def _render_inject(client: LoupeClient) -> None:
    """The second button. Separate, and it says what it is before it is pressed."""
    st.sidebar.caption(
        "Every finding above is real. The sample tape is close to defect-free, so several "
        "rules have no natural example in it."
    )
    with st.sidebar.expander("Add labelled defects"):
        st.write(
            "Writes a **copy** of one minute file with nine planted defects — negative "
            "volume, an inverted bar, a key conflict, a deleted run of slots and five more — "
            "and loads it in place of the clean one."
        )
        st.write(
            "Every defect is labelled in a manifest naming the rule it should trip, and the "
            "app marks the data as synthetic for as long as it is loaded."
        )
        st.caption("The vendor files on disk are never modified.")

    if not st.sidebar.button("Inject demo defects", key="inject-demo"):
        return

    with st.status("Planting labelled defects…", expanded=True) as status:
        try:
            plan = prepare_injection()
        except (FileNotFoundError, RuntimeError) as exc:
            status.update(label="Could not stage the injection", state="error")
            st.write(str(exc))
            return

        # Swap, do not add: the injected copy is the same contract and the same sessions, so
        # loading it alongside the clean one would make almost every row an exact duplicate
        # and bury the planted defects under `UNQ.*` findings nobody planted.
        status.update(label=f"Removing the clean {plan.replaces_filename}…")
        if not _purge_where(client, lambda b: b.get("filename") == plan.replaces_filename):
            status.update(label="Could not remove the clean copy", state="error")
            return

        status.update(label="Loading the defective copy…")
        try:
            client.create_batch(
                plan.path.name,
                plan.path.read_bytes(),
                validate=False,
                origin=INJECTED_ORIGIN,
            )
            client.run_rules()
        except (ApiProblem, ApiUnavailable) as exc:
            status.update(label="Could not load the defective copy", state="error")
            st.write(str(exc))
            return

        st.session_state["injected_manifest"] = str(plan.manifest_path)
        planted = len(plan.report.manifest.defects)
        status.update(label=f"{planted} labelled defects loaded", state="complete")
    st.rerun()


def _render_remove(client: LoupeClient, health: dict[str, Any]) -> None:
    """The way back. A demo that can only be undone with `rm` is one nobody presses."""
    st.sidebar.warning(
        f"{SYNTHETIC_MARK} **{health.get('synthetic_records', 0):,} synthetic records** are "
        "loaded."
    )
    _render_sidebar_planted()
    if not st.sidebar.button("Remove demo defects", key="remove-demo"):
        return

    with st.status("Removing planted defects…", expanded=True) as status:
        if not _purge_where(client, lambda b: b.get("origin") == INJECTED_ORIGIN):
            status.update(label="Could not remove them", state="error")
            return
        # Put the clean copy back, so removing the defects returns the store to what the demo
        # button produced rather than to a hole where one contract used to be.
        restored = _restore_clean(client, status)
        try:
            client.run_rules()
        except (ApiProblem, ApiUnavailable) as exc:
            status.update(label="Removed, but the re-run failed", state="error")
            st.write(str(exc))
            return
        status.update(
            label="Removed" + (" and the clean file restored" if restored else ""),
            state="complete",
        )
    st.session_state.pop("injected_manifest", None)
    st.rerun()


def _render_sidebar_planted() -> None:
    """Planted file(s) under strip families — nothing says 'findings below'."""
    path = st.session_state.get("injected_manifest")
    if not path or not Path(path).exists():
        return
    payload = json.loads(Path(path).read_text())
    filename = Path(str(payload.get("output") or "")).name
    groups = group_planted_by_family(list(payload.get("defects") or []))
    if not groups:
        return
    st.sidebar.caption("Planted in:")
    for label, _rows in groups:
        st.sidebar.markdown(f"**{label}**")
        if filename:
            st.sidebar.caption(f"`{filename}`")


def _restore_clean(client: LoupeClient, status) -> bool:
    try:
        plan = prepare_injection()
    except (FileNotFoundError, RuntimeError):
        return False
    clean = plan.path.parent / plan.replaces_filename
    if not clean.exists():
        return False
    try:
        client.create_batch(
            clean.name, clean.read_bytes(), validate=False, origin=DEMO_ORIGIN
        )
    except ApiProblem as problem:
        if problem.status != 409:  # already there is the outcome we wanted
            status.update(label=str(problem), state="error")
            return False
    except ApiUnavailable:
        return False
    return True


def _purge_where(client: LoupeClient, predicate) -> bool:
    try:
        batches = client.batches(limit=500).get("data", [])
    except (ApiProblem, ApiUnavailable):
        return False
    for batch in batches:
        if not predicate(batch):
            continue
        try:
            client.purge_batch(batch["batch_id"])
        except ApiProblem as problem:
            if problem.status not in (404, 409):
                return False
        except ApiUnavailable:
            return False
    return True


# ------------------------------------------------------------------- standing disclosure


def render_synthetic_notice(health: dict[str, Any]) -> bool:
    """The disclosure that has to survive a rerun. Returns whether anything is synthetic.

    Driven by `/v1/health`, which the page calls before it draws anything, so this cannot be
    skipped by a code path that forgot: there is no route to the dashboard that does not pass
    through here. A one-time toast at the moment of injection would be gone three interactions
    later, with a screen full of findings and nothing saying nine of them were manufactured.
    """
    if not int(health.get("synthetic_batches") or 0):
        return False

    st.warning(
        f"{SYNTHETIC_MARK} **This store contains planted defects.** "
        f"{health.get('synthetic_records', 0):,} of "
        f"{health.get('records', 0):,} records come from a deliberately corrupted copy of one "
        "file, loaded to demonstrate rules the real corpus cannot trigger. **Scores, finding "
        "counts and patterns below are partly synthetic.** Remove them from the sidebar to "
        "return to real vendor data."
    )
    _render_manifest()
    return True


def _render_manifest() -> None:
    """The evidence, where the reviewer is rather than only on disk.

    The manifest names the rule each planted defect should trip. Showing it is what turns
    "some of this is fake" into something a reader can check, and it is the difference between
    a labelled injection and a corrupted file.
    """
    path = st.session_state.get("injected_manifest")
    if not path or not Path(path).exists():
        return
    with st.expander("What was planted"):
        payload = json.loads(Path(path).read_text())
        st.caption(
            f"{payload['source']} → {payload['output']} · {payload['rows_in']:,} rows in, "
            f"{payload['rows_out']:,} out · seed {payload['seed']}"
        )
        filename = Path(str(payload.get("output") or "")).name
        groups = group_planted_by_family(list(payload.get("defects") or []))
        for label, rows in groups:
            st.markdown(f"**{label}**")
            if filename:
                st.caption(f"`{filename}`")
            st.dataframe(
                [
                    {
                        "Row": d.get("source_row"),
                        "Rule": d.get("rule_id"),
                        "What was done": d.get("kind"),
                        "Was": d.get("original"),
                        "Now": d.get("injected"),
                    }
                    for d in rows
                ],
                hide_index=True,
                width="stretch",
            )
