"""Rule runners, one module per dimension.

Importing this package is what populates `registry.REGISTRY`: each module registers its
runners against catalogue IDs at import time, and the parity test then compares the registry,
the catalogue and the spec's in-scope list as three sets. A rule family added without a line
here would seed rows that never fire, which is exactly what that test exists to catch.
"""

from . import (
    completeness,
    consistency,
    outliers,
    reconciliation,
    roll,
    timeliness,
    uniqueness,
    validity,
)

__all__ = [
    "completeness",
    "consistency",
    "outliers",
    "reconciliation",
    "roll",
    "timeliness",
    "uniqueness",
    "validity",
]
