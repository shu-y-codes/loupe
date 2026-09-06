"""The demo path: fetch, convert, load, plant, disclose, undo (`plans/07-demo-corpus.md`).

Three of these are seam tests and belong here rather than in a faster tier.

*The CSV oracle.* The claim behind "Accept CSV or Parquet" is not that both parse — it is that
both **mean the same thing**. Only loading one file twice, in two formats, through the real
loader can say that, and it is the one assertion that would catch a conversion which quietly
reformatted a timestamp.

*The disclosure survives a rerun.* Streamlit reruns constantly, so a notice rendered once at the
moment of injection is gone by the time a reviewer changes persona. A test that only checked the
injection moment would pass against exactly that defect.

*The fetch degrades.* The corpus lives on somebody else's server and a laptop is allowed to have
no route to it. Nothing here reaches Hugging Face: the transport is stubbed, because a test tier
that needs the network is a tier that gets muted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loupe.data import apply_schema, connect, load_file, seed_reference
from loupe.demo import corpus as demo_corpus
from loupe.demo import fetch as demo_fetch
from loupe.demo.fetch import FetchFailed, describe_corpus

VENDOR_PARQUET = "vendor_minute.parquet"

RECORD_COLUMNS = (
    "contract_id, frequency, ts_source, ts_exchange, ts_utc, trade_date, "
    "open, high, low, close, volume, volume_source, open_interest"
)


def _records(path: Path) -> list[tuple]:
    """Load one file through the real ingest path and read every record back."""
    con = connect(":memory:")
    try:
        apply_schema(con)
        seed_reference(con)
        result = load_file(con, path)
        assert result.rows_rejected == 0, f"{path.name}: {result.reject_reasons}"
        return con.execute(
            f"SELECT {RECORD_COLUMNS} FROM stage.market_record ORDER BY source_row"
        ).fetchall()
    finally:
        con.close()


# ------------------------------------------------------------------------- the CSV oracle


def test_a_converted_csv_loads_to_identical_records(tmp_path, fixture_path):
    """Done-when 7. Same file, two formats, byte-for-byte the same `stage.market_record`.

    Not "the loader did not crash on a CSV": every derived column has to agree too, and
    `ts_utc` is the one that matters most. The vendor's `timestamp_chicago_wall` is a
    **wall-clock label** and not an instant (`specs/sample-corpus.md` §4.1), so a CSV writer
    that emitted an ISO `T` or a zone suffix would still parse and would silently move every
    timestamp — which no test comparing row counts could see.
    """
    parquet = fixture_path(VENDOR_PARQUET)
    csv_path = tmp_path / "vendor_minute.csv"
    converted = demo_corpus.convert_to_csv(parquet, csv_path)

    assert converted.rows == 60
    assert csv_path.exists()

    from_parquet = _records(parquet)
    from_csv = _records(csv_path)

    assert from_parquet, "the fixture must actually load, or this compares two empty lists"
    assert from_csv == from_parquet


def test_the_two_formats_are_two_batches_and_not_one(tmp_path, fixture_path):
    """The corollary, and the reason a converted file *replaces* its Parquet in the demo load.

    Identical records with different bytes are two distinct batches, so loading both would put
    two copies of one contract's tape in the store and turn almost every row into an exact
    duplicate. That is why `prepare_demo_corpus` swaps rather than appends.
    """
    parquet = fixture_path(VENDOR_PARQUET)
    csv_path = tmp_path / "vendor_minute.csv"
    demo_corpus.convert_to_csv(parquet, csv_path)

    con = connect(":memory:")
    try:
        apply_schema(con)
        seed_reference(con)
        load_file(con, parquet)
        load_file(con, csv_path)  # no DuplicateFileError: different bytes
        formats = dict(
            con.execute(
                "SELECT file_format, count(*) FROM stage.ingest_batch GROUP BY 1"
            ).fetchall()
        )
        duplicated = con.execute(
            "SELECT count(*) FROM (SELECT contract_id, ts_utc FROM stage.market_record "
            "GROUP BY 1, 2 HAVING count(*) > 1)"
        ).fetchone()[0]
    finally:
        con.close()

    assert formats == {"parquet": 1, "csv": 1}
    assert duplicated == 60, "which is exactly why the demo loads one format per file"


# ------------------------------------------------------------------------------ the fetch


def test_the_disclosure_precedes_the_download(monkeypatch):
    """Consent before bytes. `describe_corpus` must not touch the network to answer.

    §1 found no licence grant in the vendor package, so the reader has to be told what is about
    to be downloaded *before* it is. A description that itself required a request would make
    that impossible.
    """
    def refuse(*args, **kwargs):  # pragma: no cover - the point is that it is never called
        raise AssertionError("describe_corpus must not reach the network")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    described = describe_corpus()

    assert "huggingface.co" in described.url
    assert described.revision, "the pinned revision is part of what is being consented to"
    assert "redistribution" in described.licence_note
    assert described.approx_mb > 0


def test_a_fetch_with_no_network_explains_itself(tmp_path, monkeypatch):
    """Offline is an answer, not a traceback."""
    import urllib.error

    def offline(*args, **kwargs):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", offline)

    with pytest.raises(FetchFailed) as raised:
        demo_corpus.prepare_demo_corpus(dest=tmp_path / "samples", out_dir=tmp_path / "demo")

    message = str(raised.value)
    assert "no route to host" in message
    assert "connection" in message.lower(), "the sentence has to say what to do about it"


def test_picking_a_file_from_an_absent_corpus_is_an_answer_too(tmp_path):
    """Nothing fetched yet is a state, not a crash: the buttons are ordered for a reason."""
    assert demo_corpus.earliest_minute(tmp_path) is None
    assert demo_corpus.smallest_minute(tmp_path) is None
    with pytest.raises(FileNotFoundError, match="Load the demo data"):
        demo_corpus.prepare_injection(dest=tmp_path, out_dir=tmp_path / "demo")


# --------------------------------------------------------------------------- the injection


def test_injection_writes_a_copy_and_never_the_source(tmp_path, fixture_path):
    """Done-when 4, through the path the button takes rather than through `inject` directly.

    The refusal in `injection.py` used to be defensive. Now that a button can reach it, it is
    load-bearing: a corrupted vendor file that nobody labelled is indistinguishable from a
    vendor defect, and it would end up quoted in a spec.
    """
    dest = tmp_path / "samples"
    out_dir = tmp_path / "demo"
    _stage_fake_corpus(dest, fixture_path(VENDOR_PARQUET))

    before = (dest / "data/minute/CME/ES/ESZ25.parquet").read_bytes()
    plan = demo_corpus.prepare_injection(dest=dest, out_dir=out_dir)

    assert plan.path.parent == out_dir, "the defective copy lives under data/demo/"
    assert plan.path != plan.report.manifest.source
    assert (dest / "data/minute/CME/ES/ESZ25.parquet").read_bytes() == before

    # The clean CSV it stands in for still exists, so removing the defects can restore it.
    assert (out_dir / plan.replaces_filename).exists()


def test_the_manifest_labels_every_planted_defect(tmp_path, fixture_path):
    """The evidence that makes this a labelled injection rather than a corrupted file."""
    dest = tmp_path / "samples"
    _stage_fake_corpus(dest, fixture_path(VENDOR_PARQUET))
    plan = demo_corpus.prepare_injection(dest=dest, out_dir=tmp_path / "demo")

    payload = json.loads(plan.manifest_path.read_text())
    assert payload["defects"], "an injection with no manifest rows is a corruption"
    for defect in payload["defects"]:
        assert defect["rule_id"], "every planted defect names the rule it should trip"
        assert defect["source_row"] >= 1


def _stage_fake_corpus(dest: Path, parquet: Path, *, with_metadata: bool = False) -> None:
    """A `data/samples/` shaped directory holding one file, without touching the network.

    `files.csv` is the manifest the pickers read, so the fixture has to carry one — which also
    means these tests exercise the real "choose from the manifest, restricted to what is on
    disk" path rather than a shortcut around it.

    `with_metadata` stages the rest of the vendor metadata as well, which is what makes
    `fetch_corpus` a no-op: it downloads only what is missing, so a complete directory needs no
    network at all. An empty `checksums.sha256` verifies nothing and reports nothing, which is
    the right behaviour for a manifest that lists no files.
    """
    from loupe.demo.fetch import META

    target = dest / "data/minute/CME/ES/ESZ25.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(parquet.read_bytes())
    (dest / "files.csv").write_text(
        "frequency,path,row_count,first_timestamp_ms\n"
        "minute,data/minute/CME/ES/ESZ25.parquet,60,1757944800000\n"
    )
    if with_metadata:
        for name in META:
            if not (dest / name).exists():
                (dest / name).write_text("")


# ------------------------------------------------------- the two clicks, end to end


@pytest.fixture
def staged(tmp_path, fixture_path, monkeypatch):
    """A `data/samples/` holding one file, so the demo runs with no network at all.

    `fetch_corpus` downloads only what is missing, so a fully staged directory makes the whole
    prepare step offline — and the transport is stubbed to raise as well, so a regression that
    reached for the network would fail here rather than quietly working on a connected laptop.
    """
    dest = tmp_path / "samples"
    out_dir = tmp_path / "demo"
    _stage_fake_corpus(dest, fixture_path(VENDOR_PARQUET), with_metadata=True)

    def refuse(*args, **kwargs):  # pragma: no cover - the staged corpus needs nothing
        raise AssertionError("the demo reached the network for a file it already had")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr(demo_corpus, "DEST", dest)
    monkeypatch.setattr(demo_corpus, "DEMO_DIR", out_dir)
    # The curated list is data (`specs/sample-corpus.md` §8), so the fixture substitutes the
    # one file it staged. Leaving the real eight in place would send `fetch_corpus` looking for
    # files this directory has never heard of — which is the network call being forbidden.
    monkeypatch.setattr(
        demo_fetch, "MINUTE", ["data/minute/CME/ES/ESZ25.parquet"]
    )
    return dest, out_dir


def test_the_demo_loads_through_the_api_and_declares_its_origin(api_client, staged):
    """Click one. The files go in the way any upload does — real HTTP, real multipart.

    The demo must not have a private path into the store: a shortcut that wrote records
    directly would be demonstrating code the reviewer never actually exercises.
    """
    dest, out_dir = staged
    corpus = demo_corpus.prepare_demo_corpus(dest=dest, out_dir=out_dir)

    assert corpus.csv_files == 1, "the one staged minute file is both earliest and smallest"
    assert corpus.parquet_files == 0, "a converted file replaces its Parquet, never joins it"

    for demo_file in corpus.files:
        api_client.create_batch(
            demo_file.path.name,
            demo_file.path.read_bytes(),
            validate=False,
            origin=demo_file.origin,
        )

    health = api_client.health()
    assert health["records"] == 60
    assert health["synthetic_batches"] == 0, "nothing planted yet, and the app must say so"

    batches = api_client.batches()["data"]
    assert {b["origin"] for b in batches} == {"demo"}


def test_injection_is_declared_synthetic_and_can_be_undone(api_client, staged):
    """Clicks two and three: plant, disclosed on `/health`; remove, and the store is clean.

    The disclosure is asserted on the wire rather than in a widget, because the UI reads it
    from here — a banner driven by session state would survive neither a reload nor this test.
    """
    dest, out_dir = staged
    corpus = demo_corpus.prepare_demo_corpus(dest=dest, out_dir=out_dir)
    for demo_file in corpus.files:
        api_client.create_batch(
            demo_file.path.name, demo_file.path.read_bytes(),
            validate=False, origin=demo_file.origin,
        )

    plan = demo_corpus.prepare_injection(dest=dest, out_dir=out_dir)

    # Swap, not add: the clean copy goes first, or its rows and the defective ones are
    # duplicates of each other and every planted defect is buried under `UNQ.*`.
    clean = next(
        b for b in api_client.batches()["data"] if b["filename"] == plan.replaces_filename
    )
    api_client.purge_batch(clean["batch_id"])
    api_client.create_batch(
        plan.path.name, plan.path.read_bytes(), validate=False, origin="injected"
    )

    planted = api_client.health()
    assert planted["synthetic_batches"] == 1
    assert planted["synthetic_records"] > 0
    assert planted["synthetic_records"] <= planted["records"]

    # ...and the way back.
    injected = next(
        b for b in api_client.batches()["data"] if b["origin"] == "injected"
    )
    api_client.purge_batch(injected["batch_id"])

    cleaned = api_client.health()
    assert cleaned["synthetic_batches"] == 0
    assert cleaned["synthetic_records"] == 0


def test_the_planted_defects_are_found_and_match_their_labels(api_client, staged):
    """The injection is only worth a button if the engine actually finds what was planted."""
    dest, out_dir = staged
    plan = demo_corpus.prepare_injection(dest=dest, out_dir=out_dir)
    api_client.create_batch(
        plan.path.name, plan.path.read_bytes(), validate=True, origin="injected"
    )

    fired = {
        f["rule_id"] for f in api_client.findings(limit=500)["data"]
    }
    labelled = {d.rule_id for d in plan.report.manifest.defects}
    assert labelled, "the manifest must claim something for this to test"

    # Not every planted rule can fire on a 60-row fixture — session-grained rules need a
    # calendar span this file does not have. What must hold is that the engine finds the
    # record-shaped ones the manifest names, rather than nothing at all.
    assert labelled & fired, f"none of {sorted(labelled)} fired; engine saw {sorted(fired)}"
