"""Errors raised by the data layer.

The API maps these to RFC 7807 problem responses (slice 4); nothing here knows about HTTP.
"""

from __future__ import annotations


class LoupeDataError(Exception):
    """Base class for every failure the data layer raises deliberately."""


class UnsupportedFileFormat(LoupeDataError):
    """The upload is neither CSV nor Parquet.

    Gating is on file format only, never on granularity (locked decision 8).
    """


class DuplicateFileError(LoupeDataError):
    """The same file bytes have already been ingested.

    `stage.ingest_batch.file_hash` is unique, which makes re-upload idempotent rather than
    silently doubling every volume figure. The API surfaces this as 409.
    """

    def __init__(self, file_hash: str, existing_batch_id: str, filename: str) -> None:
        super().__init__(
            f"file_hash {file_hash} already ingested as batch {existing_batch_id} "
            f"({filename!r})"
        )
        self.file_hash = file_hash
        self.existing_batch_id = existing_batch_id
        self.filename = filename


class MissingRequiredColumn(LoupeDataError):
    """A required source column is absent. File-level reject: STR.MISSING_REQUIRED_COLUMN."""

    def __init__(self, missing: list[str], seen: list[str]) -> None:
        super().__init__(f"missing required column(s) {missing}; file has {seen}")
        self.missing = missing
        self.seen = seen


class PreviewError(LoupeDataError):
    """The file could not be inspected well enough to offer a load."""
