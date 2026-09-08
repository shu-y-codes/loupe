"""The demo routes: chrome for locked decision 9, on the server side of the wire.

These moved out of the UI process in slice 17 (`plans/17-react-ui.md`) because a browser
cannot fetch from Hugging Face, read `data/samples/`, or write a defective copy. What the
tests assert is that moving them did not turn them into a second ingest pipeline, and that
the two things the Streamlit panel got right survive the move: **consent before bytes**, and
a planted defect that can never be read as a vendor one.

The corpus itself is not fetched here. `prepare_demo_corpus` is patched, because a test tier
that downloads 16 MB from someone else's server on every run is a test tier people mute.
`tests/integration/` covers the wire; `tests/demo/` covers the injector.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loupe.api.routes import demo as demo_routes
from loupe.demo.corpus import INJECTED_ORIGIN, DemoFile


def ndjson(response) -> list[dict]:
    """The stream, parsed. One JSON object per line, in the order they were emitted."""
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


# ------------------------------------------------------------------------------- consent


def test_corpus_describes_the_download_without_making_one(client):
    """Said before the button. A fetch nobody described is not one anybody consented to."""
    body = client.get("/v1/demo/corpus").json()
    assert body["repo"]
    assert len(body["revision"]) >= 12, "the revision is pinned, so it must be reported"
    assert body["approx_mb"] > 0
    assert body["minute_files"] > 0
    assert "redistribution" in body["licence_note"]


# ---------------------------------------------------------------------------------- load


class _FakeCorpus:
    def __init__(self, files: list[DemoFile]) -> None:
        self.files = files
        self.fetch = type("R", (), {"checksum_failures": []})()
        self.parquet_files = sum(1 for f in files if f.path.suffix == ".parquet")
        self.csv_files = sum(1 for f in files if f.path.suffix == ".csv")


@pytest.fixture
def demo_dir(tmp_path, fixture_path) -> Path:
    """A staging directory shaped like the real one: the corpus files and the injected copy.

    They share a directory because the real swap does. `prepare_injection` writes the defective
    copy beside the clean CSV it stands in for, and `_restore_clean` finds the clean one by
    name in that same directory — a fixture that separated them would test a shape the app
    never has.
    """
    staged = tmp_path / "demo"
    staged.mkdir()
    for name in ("cmp_session_missing.csv", "null_fields.csv"):
        (staged / name).write_bytes(fixture_path(name).read_bytes())
    return staged


@pytest.fixture
def fake_corpus(monkeypatch, demo_dir):
    """Two local CSV files standing in for a fetched corpus, with progress reported."""
    files = [
        DemoFile(path=demo_dir / "cmp_session_missing.csv", origin="demo"),
        DemoFile(path=demo_dir / "null_fields.csv", origin="demo"),
    ]

    def _prepare(*, all_minute=False, on_progress=None, **_kwargs):
        for index, demo_file in enumerate(files, start=1):
            if on_progress is not None:
                on_progress(f"data/minute/{demo_file.path.name}", index, len(files))
        return _FakeCorpus(files)

    monkeypatch.setattr(demo_routes, "prepare_demo_corpus", _prepare)
    return files


def test_load_streams_progress_and_ends_with_a_finished_result(client, fake_corpus):
    """Progress is UI telemetry, not a job table: no handle, and the stream ends done.

    The `done` event is the response — there is nothing to poll afterwards, which is locked
    decision 7 holding (`specs/api-contract.md` §4.4).
    """
    events = ndjson(client.post("/v1/demo/load"))
    kinds = [event["event"] for event in events]

    assert "progress" in kinds
    assert kinds[-1] == "done"
    assert "error" not in kinds

    fetches = [e for e in events if e.get("phase") == "fetch" and e["event"] == "progress"]
    assert [e["message"] for e in fetches] == [
        "Fetching 1/2 · cmp_session_missing.csv",
        "Fetching 2/2 · null_fields.csv",
    ], "the browser needs the same 'Fetching n/m · file' line the panel used to draw itself"

    done = events[-1]
    assert done["loaded"] == 2
    assert not any("job" in event or "poll" in event for event in events)


def test_load_ingests_through_the_ordinary_loader_with_a_demo_origin(client, fake_corpus):
    """Same batches route any upload produces, marked `demo` so nothing reads as manufactured."""
    ndjson(client.post("/v1/demo/load"))

    batches = client.get("/v1/ingest/batches").json()["data"]
    assert {b["filename"] for b in batches} == {
        "cmp_session_missing.csv",
        "null_fields.csv",
    }
    assert {b["origin"] for b in batches} == {"demo"}
    assert client.get("/v1/health").json()["synthetic_batches"] == 0, (
        "real vendor data, real findings — the load button plants nothing"
    )


def test_load_validates_the_whole_corpus_once_at_the_end(client, api_con, fake_corpus):
    """`validate=False` per file, then one unscoped run. Reconciliation needs both grains."""
    events = ndjson(client.post("/v1/demo/load"))
    assert any(e.get("phase") == "validate" for e in events)

    runs = api_con.execute("SELECT batch_id FROM dq.dq_run").fetchall()
    assert len(runs) == 1, "one corpus-wide run, not one per file"
    assert runs[0][0] is None, "an unscoped run, so cross-frequency rules are in scope"


def test_a_duplicate_file_does_not_fail_the_load(client, fake_corpus):
    """Re-pressing the button on a half-loaded store finishes the job rather than refusing."""
    ndjson(client.post("/v1/demo/load"))
    second = ndjson(client.post("/v1/demo/load"))

    assert second[-1]["event"] == "done"
    assert second[-1]["loaded"] == 0, "nothing new was loaded, and that is not an error"
    assert len(client.get("/v1/ingest/batches").json()["data"]) == 2


def test_a_failed_fetch_is_an_event_with_something_to_do(client, monkeypatch):
    """Offline is an answer, not a traceback: the corpus lives on someone else's server."""
    from loupe.demo.fetch import FetchFailed

    def _boom(**_kwargs):
        raise FetchFailed("No route to huggingface.co.")

    monkeypatch.setattr(demo_routes, "prepare_demo_corpus", _boom)
    events = ndjson(client.post("/v1/demo/load"))

    assert events[-1]["event"] == "error"
    assert events[-1]["title"] == "Could not fetch the corpus"
    assert "fully usable without the sample corpus" in events[-1]["hint"]


def test_a_checksum_mismatch_is_reported_and_does_not_stop_the_load(
    client, monkeypatch, fixture_path
):
    files = [DemoFile(path=fixture_path("null_fields.csv"), origin="demo")]

    def _prepare(**_kwargs):
        corpus = _FakeCorpus(files)
        corpus.fetch.checksum_failures = ["data/minute/CME/ES/ESZ25.parquet"]
        return corpus

    monkeypatch.setattr(demo_routes, "prepare_demo_corpus", _prepare)
    events = ndjson(client.post("/v1/demo/load"))

    warnings = [e for e in events if e["event"] == "warning"]
    assert len(warnings) == 1
    assert "does not verify" in warnings[0]["message"]
    assert events[-1]["event"] == "done"


# -------------------------------------------------------------------------------- inject


@pytest.fixture
def fake_injection(monkeypatch, demo_dir):
    """A staged injection beside the clean file, with a manifest in the same `DEMO_DIR`.

    The real `prepare_injection` needs the fetched corpus on disk. What these tests are about
    is the swap and the disclosure, so the staging is faked and the manifest is real JSON in
    the shape `loupe.demo.injection` writes.

    The planted copy carries a changed value rather than being byte-identical, because that is
    what an injection is — and because identical bytes would collide on `file_hash` and hide
    the swap behind a duplicate refusal.
    """
    clean = demo_dir / "null_fields.csv"
    planted = demo_dir / "null_fields_with_defects.csv"
    lines = clean.read_text().splitlines()
    planted.write_text("\n".join([*lines, lines[-1]]) + "\n")
    manifest = {
        "source": str(clean),
        "source_sha256": "0" * 64,
        "output": str(planted),
        "output_sha256": "1" * 64,
        "rows_in": 4,
        "rows_out": 4,
        "seed": 20260906,
        "defects": [
            {"defect_id": "d1", "rule_id": "VAL.NEGATIVE_VOLUME", "kind": "negate_volume",
             "contract_id": "ESZ25", "source_row": 2, "original": "100", "injected": "-100"},
            {"defect_id": "d2", "rule_id": "UNQ.EXACT_DUPLICATE", "kind": "copy_row",
             "contract_id": "ESZ25", "source_row": 3, "original": None, "injected": None},
            {"defect_id": "d3", "rule_id": "CMP.MISSING_TIMESTAMP", "kind": "delete_run",
             "contract_id": "ESZ25", "source_row": 4, "original": None, "injected": None},
            {"defect_id": "d4", "rule_id": "TIM.OUT_OF_ORDER", "kind": "swap_rows",
             "contract_id": "ESZ25", "source_row": 5, "original": None, "injected": None},
        ],
    }
    (demo_dir / f"{planted.name}.manifest.json").write_text(json.dumps(manifest))

    report = type("R", (), {"manifest": type("M", (), {"defects": manifest["defects"]})()})()
    plan = type(
        "Plan",
        (),
        {"path": planted, "replaces_filename": clean.name, "report": report},
    )()
    monkeypatch.setattr(demo_routes, "prepare_injection", lambda **_k: plan)
    monkeypatch.setattr(demo_routes, "DEMO_DIR", demo_dir)
    return plan


def test_inject_swaps_the_clean_file_rather_than_adding_beside_it(
    client, fake_corpus, fake_injection
):
    """Adding would bury nine planted defects under `UNQ.*` findings nobody planted."""
    ndjson(client.post("/v1/demo/load"))
    events = ndjson(client.post("/v1/demo/inject"))
    assert events[-1]["event"] == "done"

    live = client.get("/v1/ingest/batches").json()["data"]
    names = {b["filename"] for b in live}
    assert "null_fields_with_defects.csv" in names
    assert "null_fields.csv" not in names, "the clean copy was replaced, not joined"


def test_injected_records_are_disclosed_as_synthetic(client, fake_corpus, fake_injection):
    """`/health` is what makes the disclosure unskippable — every page calls it first."""
    ndjson(client.post("/v1/demo/load"))
    ndjson(client.post("/v1/demo/inject"))

    health = client.get("/v1/health").json()
    assert health["synthetic_batches"] == 1
    assert health["synthetic_records"] > 0


def test_injection_groups_the_manifest_with_the_catalogue_map(
    client, fake_corpus, fake_injection
):
    """Grouped server-side so no client re-implements `strip_family`.

    Recurring patterns is absent on purpose: patterns are an insight over findings, so nothing
    can be planted *as* one. Off-strip rules get a named group rather than the floor.
    """
    ndjson(client.post("/v1/demo/load"))
    ndjson(client.post("/v1/demo/inject"))

    body = client.get("/v1/demo/injection").json()
    assert body["loaded"] is True
    assert body["manifest_available"] is True
    assert body["seed"] == 20260906

    by_family = {group["family"]: group for group in body["groups"]}
    assert set(by_family) == {"gaps", "duplicates", "invalid", "off_strip"}
    assert by_family["invalid"]["defects"][0]["rule_id"] == "VAL.NEGATIVE_VOLUME"
    assert by_family["off_strip"]["label"] == "Other (off the strip)"
    assert by_family["off_strip"]["defects"][0]["rule_id"] == "TIM.OUT_OF_ORDER"
    assert "patterns" not in by_family


def test_injection_reports_nothing_planted_on_a_clean_store(client, fake_corpus):
    ndjson(client.post("/v1/demo/load"))
    body = client.get("/v1/demo/injection").json()
    assert body["loaded"] is False
    assert body["groups"] == []


def test_a_planted_store_with_no_manifest_says_so(
    client, fake_corpus, fake_injection, monkeypatch, tmp_path
):  # noqa: PT019 - tmp_path is a path, not a fixture flag
    """Honest absence beats an empty list that reads as 'nothing was planted'."""
    ndjson(client.post("/v1/demo/load"))
    ndjson(client.post("/v1/demo/inject"))
    monkeypatch.setattr(demo_routes, "DEMO_DIR", tmp_path / "elsewhere")

    body = client.get("/v1/demo/injection").json()
    assert body["loaded"] is True
    assert body["manifest_available"] is False
    assert body["groups"] == []


# -------------------------------------------------------------------------------- remove


def test_remove_takes_the_defects_out_and_puts_the_clean_file_back(
    client, fake_corpus, fake_injection
):
    """A demo that can only be undone with `rm` is one nobody presses."""
    ndjson(client.post("/v1/demo/load"))
    ndjson(client.post("/v1/demo/inject"))
    events = ndjson(client.post("/v1/demo/remove"))

    assert events[-1]["event"] == "done"
    assert events[-1]["restored"] is True

    live = {b["filename"] for b in client.get("/v1/ingest/batches").json()["data"]}
    assert "null_fields_with_defects.csv" not in live
    assert "null_fields.csv" in live, "the store returns to what Load demo data produced"
    assert client.get("/v1/health").json()["synthetic_batches"] == 0


def test_remove_re_validates_so_the_findings_match_the_records(
    client, fake_corpus, fake_injection
):
    ndjson(client.post("/v1/demo/load"))
    ndjson(client.post("/v1/demo/inject"))
    events = ndjson(client.post("/v1/demo/remove"))

    assert any(e.get("phase") == "validate" for e in events)
    assert client.get("/v1/demo/injection").json()["loaded"] is False
    assert not any(
        b["origin"] == INJECTED_ORIGIN
        for b in client.get("/v1/ingest/batches").json()["data"]
    )
