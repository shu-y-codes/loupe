"""Preview discloses the ingestion decisions before anything is committed."""

from __future__ import annotations

import pytest

from loupe.data import preview_file
from loupe.data.errors import MissingRequiredColumn, PreviewError, UnsupportedFileFormat
from loupe.data.preview import detect_format


def test_generic_csv_is_recognised(con, fixture_path):
    preview = preview_file(con, fixture_path("null_fields.csv"))
    assert preview.file_format == "csv"
    assert preview.frequency == "minute"
    assert preview.contracts == ["ESZ25"]
    assert preview.column_mapping["contract"] == "contract_id"
    assert preview.column_mapping["timestamp"] == "ts"


def test_no_vendor_profile_is_a_stated_assumption(con, fixture_path):
    preview = preview_file(con, fixture_path("null_fields.csv"))
    assert any("No vendor profile matched" in w for w in preview.warnings)


def test_interval_is_accepted_on_multiples_not_on_modal_share(con, fixture_path):
    """The modal share is a diagnostic; the acceptance test is the multiple-of check.

    A 0.8 modal-share gate would reject the correct one-minute inference for six of the
    eight roots in the corpus, because illiquid minutes are simply absent.
    """
    preview = preview_file(con, fixture_path("session_roll_boundary.csv"))
    assert preview.inferred_interval.value == "1 minute"
    assert preview.inferred_interval.confidence == 1.0
    assert "exact multiples" in preview.inferred_interval.method
    # Sparse fixture: the modal share alone would not have carried this.
    assert preview.interval_confidence < 0.8


def test_session_boundary_is_named_per_root(con, fixture_path):
    assert "17:00" in preview_file(con, fixture_path("session_roll_boundary.csv")).session_boundary
    assert "19:00" in preview_file(con, fixture_path("zc_two_window.csv")).session_boundary


def test_capabilities_on_a_minute_only_upload(con, fixture_path):
    caps = preview_file(con, fixture_path("null_fields.csv")).capabilities
    assert caps["vwap_15m"].available
    assert not caps["reconciliation"].available
    assert "only one granularity" in caps["reconciliation"].reason


def test_unknown_symbol_warns_and_does_not_block(con, tmp_path):
    path = tmp_path / "odd.csv"
    path.write_text(
        "contract,timestamp,open,high,low,close,volume\n"
        "not-a-symbol,2025-09-15 09:00:00,1,2,0.5,1.5,10\n"
    )
    preview = preview_file(con, path)
    assert preview.contracts == ["not-a-symbol"]
    assert any("STR.UNKNOWN_CONTRACT_FORMAT" in w for w in preview.warnings)


def test_missing_required_column_is_refused(con, tmp_path):
    path = tmp_path / "no_prices.csv"
    path.write_text("contract,timestamp,volume\nESZ25,2025-09-15 09:00:00,10\n")
    with pytest.raises(MissingRequiredColumn) as excinfo:
        preview_file(con, path)
    assert set(excinfo.value.missing) == {"open", "high", "low", "close"}


def test_unsupported_format_is_refused(con, tmp_path):
    path = tmp_path / "notes.pdf"
    path.write_bytes(b"%PDF-1.4 not a market data file")
    with pytest.raises(UnsupportedFileFormat):
        preview_file(con, path)


def test_missing_file_is_an_error(con, tmp_path):
    with pytest.raises(PreviewError):
        preview_file(con, tmp_path / "absent.csv")


def test_detect_format_reads_the_magic_number(tmp_path):
    parquet = tmp_path / "mislabelled.csv"
    parquet.write_bytes(b"PAR1rest-of-the-file")
    assert detect_format(parquet) == "parquet"


@pytest.mark.samples
def test_vendor_minute_profile_matches_the_real_file(con, samples_dir):
    preview = preview_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")
    assert preview.file_format == "parquet"
    assert preview.frequency == "minute"
    assert preview.row_count == 114_477
    assert preview.contracts == ["ESZ25"]
    assert preview.profile is not None
    assert preview.source_timezone.value == "America/Chicago"
    assert preview.source_timezone.confidence == 1.0
    assert preview.ts_convention == "interval_start"
    assert preview.inferred_interval.value == "1 minute"
    # trading_date disagrees with the vendor's own daily boundary, so we decline it — and
    # record that we saw it rather than dropping it silently.
    assert "trading_date" in preview.unmapped_columns
    assert "minute_of_day" in preview.unmapped_columns


@pytest.mark.samples
def test_vendor_daily_profile_matches_the_real_file(con, samples_dir):
    preview = preview_file(con, samples_dir / "data/daily/CME/ES/ESZ25.parquet")
    assert preview.frequency == "daily"
    assert preview.row_count == 1_145
    assert preview.bar_interval == "1 day"
    assert not preview.capabilities["vwap_15m"].available
    assert "no intraday rows" in preview.capabilities["vwap_15m"].reason
    assert preview.column_mapping["open_interest"] == "open_interest"


@pytest.mark.samples
def test_real_minute_headers_are_the_thirteen_documented_columns(con, samples_dir):
    preview = preview_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")
    assert [name for name, _ in preview.detected_columns] == [
        "root_id",
        "exchange",
        "root",
        "contract_symbol",
        "timestamp_ms",
        "timestamp_chicago_wall",
        "trading_date",
        "minute_of_day",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]


@pytest.mark.samples
def test_real_daily_headers_are_the_twelve_documented_columns(con, samples_dir):
    preview = preview_file(con, samples_dir / "data/daily/CME/ES/ESZ25.parquet")
    assert [name for name, _ in preview.detected_columns] == [
        "root_id",
        "exchange",
        "root",
        "contract_symbol",
        "timestamp_ms",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "open_interest",
    ]
