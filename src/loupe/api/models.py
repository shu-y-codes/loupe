"""Pydantic response models — the JSON envelopes `specs/api-contract.md` owns.

These are shapes and descriptions only. No model computes a bar, a score or a window; the
values arrive from `data` / `quality` / `insights` already decided. Where a field needs
provenance stated (§3 lists the ones that do), the description carries it, because OpenAPI
generated from this app is the architecture evidence the contract asks for (§2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class Scope(BaseModel):
    """What a request resolved to. Echoed so a client never has to assume a default held."""

    contracts: list[str] = Field(description="Contracts actually in scope after filtering.")
    start: date | None = Field(None, description="Resolved inclusive start trade date.")
    end: date | None = Field(None, description="Resolved inclusive end trade date.")
    basis: str | None = Field(None, description="`raw` or `clean`.")
    frequency: str | None = Field(None, description="Resolved record grain read from.")
    frequency_defaulted: bool = Field(
        False,
        description="True when the server chose the grain because the caller omitted it.",
    )


class Health(BaseModel):
    status: str = Field(description="`ok` when the schema is applied and the store is open.")
    schema_applied: bool
    rules_seeded: bool = Field(description="False until `seed_quality` has run.")
    records: int = Field(description="Rows in `stage.market_record`.")
    contracts: int
    batches: int = Field(description="Ingest batches, excluding purged ones.")


class Coverage(BaseModel):
    """Observed data bounds for one grain — never listing or expiry dates (§3)."""

    first_trade_date: date | None
    last_trade_date: date | None
    sessions: int
    records: int


class Contract(BaseModel):
    contract_id: str
    root: str | None = Field(None, description="Parsed from the symbol; `SR3M26` proves the "
                             "root is not always two characters.")
    exchange: str | None = None
    contract_month: str | None = Field(
        None, description="Parsed from the symbol and validated against the file manifest."
    )
    tick_size: float | None = Field(
        None,
        description="Largest increment every observed price lies on; measured, not declared.",
    )
    multiplier: float | None = Field(None, description="Seeded per root.")
    coverage: dict[str, Coverage] = Field(
        default_factory=dict, description="Observed bounds, keyed by frequency."
    )
    frequencies_available: list[str] = Field(
        default_factory=list,
        description="Grains actually held. A daily-only contract cannot serve a 15-minute "
        "VWAP, and this is how the UI disables it without provoking an error.",
    )
    roll_date: date | None = Field(
        None, description="Null for every contract loaded from the development sample."
    )
    dates_inferred: bool = Field(
        True,
        description="True when the date bounds are observed from data rather than read from "
        "expiry reference data. Means 'we observed data between these dates'.",
    )


class ContractsResponse(BaseModel):
    data: list[Contract]
    total: int


class CalendarDay(BaseModel):
    exchange: str | None
    root: str | None
    trade_date: date
    session_open_utc: datetime | None
    session_close_utc: datetime | None
    is_holiday: bool
    is_early_close: bool
    expected_slots_1m: int | None = Field(
        None, description="Null on an early close rather than a guessed truncated grid."
    )


class CalendarResponse(BaseModel):
    data: list[CalendarDay]
    total: int


# ------------------------------------------------------------------------------- ingest


class Capability(BaseModel):
    """One thing an upload will or will not enable, decided before anything is written."""

    available: bool
    reason: str | None = None
    substitute_offered: bool | None = Field(
        None,
        description="Present and false on a refused capability: machine-readable proof that "
        "nothing was quietly swapped in.",
    )


class Inference(BaseModel):
    """A value the loader derived rather than read, with the method that produced it."""

    value: str | None
    method: str
    confidence: float | None = None


class PreviewResponse(BaseModel):
    filename: str
    file_format: str
    file_bytes: int
    rows_total: int
    detected_columns: list[str]
    column_mapping: dict[str, Any] = Field(
        description="Not a bijection: one source column can feed a derived pair, as a "
        "wall-clock label feeds both `ts_exchange` and `ts_utc`."
    )
    unmapped_columns: list[str]
    inferred_frequency: Inference
    inferred_timezone: Inference
    inferred_interval: Inference
    ts_convention: str
    session_boundary: str | None = Field(
        None, description="An ingestion decision that can go wrong silently, so it is shown."
    )
    contracts_detected: list[str]
    verdict: str = Field(description="`accept`, or `duplicate` when these bytes are loaded.")
    already_ingested: str | None = Field(
        None, description="Batch id holding these exact bytes, when one exists."
    )
    enables: dict[str, Capability] = Field(
        description="The point of the step: a daily-only upload sees VWAP unavailable "
        "before commit."
    )
    warnings: list[str] = Field(default_factory=list)


class BatchSummary(BaseModel):
    """The four decisions a later reprocessing must reproduce, plus what was loaded."""

    batch_id: str
    status: str
    filename: str
    file_format: str | None
    file_hash: str
    frequency: str
    source_timezone: str | None
    ts_convention: str | None
    session_boundary: str | None
    rows_read: int
    rows_accepted: int
    rows_rejected: int
    contracts_detected: list[str] = Field(default_factory=list)
    sessions_detected: int = 0
    trade_date_range: list[date | None] = Field(default_factory=list)
    dq_run_id: str | None = None
    elapsed_ms: int | None = None


class BatchesResponse(BaseModel):
    data: list[BatchSummary]
    total: int


class RejectRow(BaseModel):
    source_row: int = Field(description="1-based row in the source file.")
    reason_code: str = Field(description="An `STR.*` code; the rules spec owns the vocabulary.")
    reason_detail: str | None
    raw_payload: str | None = Field(None, description="The original row, verbatim.")


class RejectsResponse(BaseModel):
    data: list[RejectRow]
    total: int
    limit: int
    offset: int


class PurgeResponse(BaseModel):
    """What the purge removed. Soft delete: the batch row survives as `purged`."""

    batch_id: str
    status: str
    records_deleted: int
    rejects_deleted: int
    findings_deleted: int
    bars_deleted: int
    sessions_affected: int


# ---------------------------------------------------------------------------- analytics


class Reconciliation(BaseModel):
    status: str = Field(description="`compared` or `not_comparable`.")
    supplied_close: float | None = None
    close_diff: float | None = None
    supplied_volume: int | None = None
    volume_ratio: float | None = None


class Bar(BaseModel):
    contract_id: str
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    record_count: int | None
    expected_count: int | None = Field(
        None, description="Null on an early close rather than a guessed truncated grid."
    )
    completeness_pct: float | None
    finding_count: int
    max_severity: str | None
    reconciliation: Reconciliation | None = None


class BlockedSession(BaseModel):
    """A session withheld because a `critical` finding intersects it.

    Named rather than dropped: a missing candle that reads as "no data" is the confusion the
    publish gate exists to prevent.
    """

    contract_id: str
    trade_date: date
    frequency: str
    blocking_rule_ids: list[str]
    max_severity: str | None


class BarsResponse(BaseModel):
    scope: Scope
    data: list[Bar]
    total: int
    blocked_sessions: list[BlockedSession] = Field(
        default_factory=list,
        description="Sessions withheld by the publish gate, with the rule that blocked each.",
    )
    meta: dict[str, Any] = Field(default_factory=dict)


class VwapPoint(BaseModel):
    contract_id: str
    trade_date: date
    ts_utc: datetime
    vwap: float | None = Field(
        None,
        description="Null where the window holds no volume. Charts break the line here; "
        "they must not interpolate.",
    )
    window_volume: int | None
    window_records: int
    is_warmup: bool


class VwapResponse(BaseModel):
    scope: Scope
    window: str = "15m"
    window_type: str = "trailing_time_range_inclusive"
    price_basis: str
    partition: list[str] = Field(default_factory=lambda: ["contract_id", "trade_date"])
    data: list[VwapPoint]
    total: int
    blocked_sessions: list[BlockedSession] = Field(default_factory=list)


class CompareResponse(BaseModel):
    scope: Scope
    metric: str
    compare: str
    data: list[dict[str, Any]]
    total: int
    differing: int = Field(description="Rows where the two sides disagree.")


# ----------------------------------------------------------------------------------- dq


class DimensionScore(BaseModel):
    dimension: str
    score: float
    weight: float
    denominator: int
    basis: str
    affected_records: int
    finding_count: int


class SliceScore(BaseModel):
    """Which dimensions were in scope is part of the score, not metadata about it."""

    contract_id: str
    frequency: str
    overall: float | None
    insufficient_data: bool
    records: int
    dimensions_in_scope: list[str]
    dimensions_not_in_scope: list[dict[str, str]]
    scope_signature: str = Field(
        description="Equal signature means two scores are comparable; unequal means the UI "
        "must say so."
    )
    weight_denominator: float
    dimensions: dict[str, DimensionScore]


class Issue(BaseModel):
    """One inventory callout, in the rule catalogue's own words — never copy from a widget."""

    rule_id: str
    label: str = Field(description="`dq.dq_rule.name`, so the wording lives with the rule.")
    severity: str = Field(
        description="The severity the finding fired at, which is not always the rule's "
        "declared one: `CON.CLOSE_OUT_OF_RANGE` drops to `params.daily_severity` on daily "
        "rows."
    )
    findings: int


class ContractSummary(BaseModel):
    """One row of the Summary inventory. Every persona reads this; each shows a subset."""

    contract_id: str
    score: float | None = Field(
        description="**Minimum** across the contract's slices — as trustworthy as its worst "
        "frequency. Not a mean, which would let a large clean minute tape bury a broken "
        "daily file."
    )
    status: str = Field(
        description="`ATTN` when the contract holds any open `error` or `critical` finding, "
        "`OK` otherwise. Severity, never a score cut: the score is a navigation index and "
        "not a grade (`specs/dq-rules-and-scoring.md` §11.5)."
    )
    frequencies: list[str]
    finding_count: int
    top_issue: Issue | None = Field(
        None, description="Worst issue of any kind: the Analyst Top issue and Trader Warning."
    )
    settlement_issue: Issue | None = Field(
        None,
        description="Risk's Closing-day column — `SETTLEMENT_RULES` at daily grain only "
        "(§11.6). Null for a contract held solely at minute grain, because settlement lives "
        "in the daily file.",
    )


class DqSummaryResponse(BaseModel):
    scope: Scope
    overall_score: float | None
    score_method: str
    slices: list[SliceScore]
    contracts: list[ContractSummary] = Field(
        default_factory=list,
        description="`slices` rolled up to one row per contract, with the callouts each "
        "persona selects. Both callouts ship on every row rather than behind a `?callout=` "
        "parameter: personas are a UI view selector and nothing here is persona-aware (§8).",
    )
    worst_field: dict[str, Any] | None = Field(
        None,
        description="The Analyst tile, derived from rule identity (§11.7). Null — the tile "
        "reads 'not applicable' — when the scope's findings are all from unmapped rules.",
    )
    records: dict[str, Any]
    top_issues: list[dict[str, Any]]
    meta: dict[str, Any]


class DqMetricsResponse(BaseModel):
    scope: Scope
    group_by: str
    dimension: str | None = Field(
        None, description="Echoed dimension filter; null means every dimension, averaged."
    )
    data: list[dict[str, Any]]
    total: int


class Finding(BaseModel):
    finding_id: str
    rule_id: str
    contract_id: str | None
    frequency: str | None
    trade_date: date | None
    ts_start_utc: datetime | None
    ts_end_utc: datetime | None
    severity: str
    affected_rows: int
    status: str
    details: Any | None = Field(None, description="Evidence. Never grouped on.")
    source: dict[str, Any] | None = Field(
        None, description="Carries `source_row` so the UI can cite a row of a named file."
    )


class FindingsResponse(BaseModel):
    data: list[Finding]
    total: int
    limit: int
    offset: int


class ChangelogEntry(BaseModel):
    """One cleaning decision, summarised over the records it touched."""

    contract_id: str
    trade_date: date | None
    frequency: str | None
    rule_id: str | None = Field(
        None, description="Null when a decision cannot be attributed to a rule; kept rather "
        "than dropped, because an unattributable action is what an audit trail must show."
    )
    label: str | None = Field(None, description="`dq.dq_rule.name`.")
    action: str = Field(description="`exclude`, `dedupe_drop`, `coerce` or `impute`.")
    records: int = Field(description="How many records this decision touched.")


class ChangelogResponse(BaseModel):
    """Aggregated by rule × trade date × action, never one row per record: the panel shows a
    count, and summing rows in a widget is aggregation outside `ui`."""

    scope: Scope
    run_id: str | None
    data: list[ChangelogEntry]
    total: int
    limit: int
    offset: int


class Rule(BaseModel):
    rule_id: str
    dimension: str
    severity: str
    scope: str
    enabled: bool
    params: Any | None = None
    description: str | None = None


class RulesResponse(BaseModel):
    data: list[Rule]
    total: int


class RunSummary(BaseModel):
    """A completed run, never a pending job handle."""

    run_id: str
    status: str
    batch_id: str | None
    ruleset_hash: str | None
    findings_count: int
    scope_filter: Any | None = None
    started_at: datetime | None
    finished_at: datetime | None
    scores: list[SliceScore] = Field(default_factory=list)
