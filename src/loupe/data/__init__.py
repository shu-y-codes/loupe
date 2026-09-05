"""The `data` layer: DuckDB connect, schema, reference seed, preview and ingest.

No UI and no HTTP here. The API (slice 4) calls these functions; nothing in this package
knows what an HTTP status code is.
"""

from .connection import connect, database_path
from .errors import (
    DuplicateFileError,
    LoupeDataError,
    MissingRequiredColumn,
    PreviewError,
    UnsupportedFileFormat,
)
from .load import LoadResult, load_file
from .preview import Preview, preview_file
from .purge import (
    BatchAlreadyPurged,
    BatchNotFound,
    PurgeResult,
    purge_batch,
)
from .reference import SeedSummary, seed_reference
from .schema import apply_schema, schema_is_applied

__all__ = [
    "BatchAlreadyPurged",
    "BatchNotFound",
    "DuplicateFileError",
    "LoadResult",
    "LoupeDataError",
    "MissingRequiredColumn",
    "Preview",
    "PreviewError",
    "PurgeResult",
    "SeedSummary",
    "UnsupportedFileFormat",
    "apply_schema",
    "connect",
    "database_path",
    "load_file",
    "preview_file",
    "purge_batch",
    "schema_is_applied",
    "seed_reference",
]
