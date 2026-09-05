"""The `insights` layer: daily bars, rolling VWAP, raw/clean compare, and the publish gate.

Aggregation and windows — no SQL loaders and no DQ rule definitions
(`specs/loupe-solution-design.md` §6). The API (slice 4) and the UI (slice 5) call these
functions; nothing here knows what a status code or a widget is.

Two things in this package are easy to get subtly wrong and are therefore centralised:

- **The session boundary.** A full CME session and a full calendar day are both 1,380
  one-minute slots, so a calendar-date grouping produces the right count with the wrong
  membership and every count-based assertion passes (`specs/analytics-semantics.md` §2.2.1).
  Bars group on `trade_date`, which ingest assigned from the profile's roll.
- **What may be published.** `critical` findings block a slice. The gate lives here because
  `quality` owns findings but must not know about publication, and the API may not hold
  business math.
"""

from .bars import (
    BASIS_RELATION,
    BarBuildReport,
    DailyBar,
    build_bars,
    published_bars,
    read_bars,
)
from .compare import BarDelta, VwapDelta, compare_bars, compare_vwap
from .gate import (
    BLOCKING_SEVERITY,
    COUNTED_SCOPES,
    SEVERITY_RANK,
    FrequencyUnavailable,
    PublishedSeries,
    SessionQuality,
    blocked_sessions,
    capability_gap,
    frequencies_held,
    session_quality,
    session_quality_sql,
)
from .vwap import PRICE_BASIS_SQL, VwapPoint, published_vwap, vwap_15m, vwap_sql

__all__ = [
    "BASIS_RELATION",
    "BLOCKING_SEVERITY",
    "COUNTED_SCOPES",
    "PRICE_BASIS_SQL",
    "SEVERITY_RANK",
    "BarBuildReport",
    "BarDelta",
    "DailyBar",
    "FrequencyUnavailable",
    "PublishedSeries",
    "SessionQuality",
    "VwapDelta",
    "VwapPoint",
    "blocked_sessions",
    "build_bars",
    "capability_gap",
    "compare_bars",
    "compare_vwap",
    "frequencies_held",
    "published_bars",
    "published_vwap",
    "read_bars",
    "session_quality",
    "session_quality_sql",
    "vwap_15m",
    "vwap_sql",
]
