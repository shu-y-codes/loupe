"""The declared rule catalogue — the only author of `dq.dq_rule` in v1.

Rules are **rows, not code branches** (`specs/dq-rules-and-scoring.md` §17). This module
declares them once; `seed.py` writes them to `dq.dq_rule`; every runner and the scorer then
read severities, thresholds and weights back from those rows at run time. Changing a default
is therefore a catalogue edit plus a re-seed, never a code change at the point of use.

Adding a rule is the five-step workflow in spec §17: amend the spec, add a `RuleSpec` here,
register a runner against the same ID, add a fixture and unit test, deploy. The parity test
in `tests/quality/test_catalogue.py` fails the suite if any of those steps is missed, so a
catalogue entry with no runner cannot quietly seed a rule that never fires.

Params carried here are **calibration for this corpus**, measured in
`specs/sample-corpus.md` §7, not specification. They are meant to be tuned in the row.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

# specs/dq-rules-and-scoring.md §11.4. Seeded from severity so the worklist orders sensibly
# before anyone tunes it, and so the number means something sayable out loud: one critical
# outranks two errors. Never an input to any score (§11.4).
TRIAGE_WEIGHT_BY_SEVERITY: Mapping[str, float] = MappingProxyType(
    {"critical": 8.0, "error": 4.0, "warning": 2.0, "info": 0.5}
)

# specs/dq-rules-and-scoring.md §11.2. Seeded into `dq.score_weight` and read at scoring
# time; the scorer holds no literals. Reconciliation is conditional and only enters the sum
# when both frequencies exist for a contract (§11.3).
SCORE_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "completeness": 0.30,
        "validity": 0.25,
        "consistency": 0.20,
        "uniqueness": 0.15,
        "timeliness": 0.10,
        "reconciliation": 0.20,
    }
)

# specs/dq-rules-and-scoring.md §11.5. Below this many records a slice reports "insufficient
# data" rather than a score.
DEFAULT_MIN_RECORDS = 100


@dataclass(frozen=True)
class RuleSpec:
    """One catalogue entry — the declared form of a `dq.dq_rule` row.

    `enforced_at` distinguishes a rule the rule engine evaluates from one ingest already
    enforces. `UNQ.DUPLICATE_FILE` is the only member of the second kind: the spec requires
    the row (§"Scope of authority") but ingest refuses the batch outright, so no finding is
    ever written and no runner exists to write one.
    """

    rule_id: str
    dimension: str
    name: str
    description: str
    severity: str
    scope: str
    applies_to_frequency: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    enforced_at: str = "rules"
    triage_weight: float | None = None

    @property
    def effective_triage_weight(self) -> float:
        """The declared weight, or the §11.4 default for this severity."""
        if self.triage_weight is not None:
            return self.triage_weight
        return TRIAGE_WEIGHT_BY_SEVERITY[self.severity]


# ------------------------------------------------------------------- shared calibration

# The completeness window is a *liquidity* window: a contract is listed years before it
# trades, so the listed span is the wrong bound (sample-corpus §7.4). The floor is carried on
# each session-grained completeness rule rather than in a global, because it is that rule's
# parameter and different deployments may want different bounds per rule.
VOLUME_FLOOR = 1000

# specs/sample-corpus.md §7.2. Bands are per root because a band suiting ES at ~6,000 or ZC
# at ~475 passes anything for SR3 at ~97. Wide by design: this rule catches decimal shifts
# (10x, 100x), not unusual days. A root with no band is not evaluated.
PRICE_BANDS: Mapping[str, list[float]] = MappingProxyType(
    {
        "CL": [5.0, 500.0],
        "ES": [500.0, 30000.0],
        "GC": [200.0, 20000.0],
        "SB": [2.0, 200.0],
        # A rate contract quoted as 100 - rate; the band is a property of the quotation.
        "SR3": [90.0, 101.0],
        "VX": [5.0, 200.0],
        # Quoted in cents per bushel: 475 means $4.75.
        "ZC": [100.0, 3000.0],
        "ZN": [50.0, 250.0],
    }
)

# `CON.STALE_REPEAT` default n is not global (spec §6): a flat price for many consecutive
# minutes is ordinary on an illiquid rate contract and a feed failure on ES. At n = 10 the
# corpus fires 14,830 times, 13,285 of them SR3 (sample-corpus §7.1).
STALE_REPEAT_N_BY_ROOT: Mapping[str, int] = MappingProxyType(
    {"SR3": 120, "ZC": 90, "SB": 90, "VX": 60}
)


CATALOGUE: tuple[RuleSpec, ...] = (
    # ------------------------------------------------------------------ completeness
    RuleSpec(
        rule_id="CMP.NULL_FIELD",
        dimension="completeness",
        name="Null OHLCV field",
        description=(
            "Any of open/high/low/close/volume is null. An empty cell parses, so it is "
            "loaded and flagged here; a non-numeric string is a STR.* parse reject instead."
        ),
        severity="error",
        scope="record",
        params={"fields": ["open", "high", "low", "close", "volume"]},
    ),
    RuleSpec(
        rule_id="CMP.MISSING_TIMESTAMP",
        dimension="completeness",
        name="Missing grid slots",
        description=(
            "A contiguous run of expected grid slots with no record. One finding per run, "
            "with affected_rows set to the slot count, so a gap is one row and not 1,380."
        ),
        severity="warning",
        scope="session",
        applies_to_frequency="minute",
        params={"volume_floor": VOLUME_FLOOR, "min_run_slots": 1},
    ),
    RuleSpec(
        rule_id="CMP.SESSION_MISSING",
        dimension="completeness",
        name="Session absent",
        description=(
            "No records at all for an active contract on a non-holiday session inside the "
            "liquidity window."
        ),
        severity="error",
        scope="session",
        params={"volume_floor": VOLUME_FLOOR},
    ),
    RuleSpec(
        rule_id="CMP.PARTIAL_SESSION",
        dimension="completeness",
        name="Partial session",
        description="Session completeness below the threshold share of expected grid slots.",
        severity="warning",
        scope="session",
        applies_to_frequency="minute",
        params={"threshold": 0.95, "volume_floor": VOLUME_FLOOR},
    ),
    RuleSpec(
        rule_id="CMP.SPARSE_SERIES",
        dimension="completeness",
        name="Sparse series",
        description="The contract carries fewer than min_sessions sessions in total.",
        severity="info",
        scope="series",
        params={"min_sessions": 20},
    ),
    # --------------------------------------------------------------------- uniqueness
    RuleSpec(
        rule_id="UNQ.EXACT_DUPLICATE",
        dimension="uniqueness",
        name="Exact duplicate row",
        description=(
            "Two or more rows identical across every field. The lowest source_row is kept "
            "and the rest are dedupe_drop-ed (spec §14)."
        ),
        severity="warning",
        scope="record",
        params={"keep": "lowest_source_row"},
    ),
    RuleSpec(
        rule_id="UNQ.KEY_CONFLICT",
        dimension="uniqueness",
        name="Key conflict",
        description=(
            "Same (contract_id, frequency, ts_utc) with differing OHLCV. Every row in the "
            "conflict is excluded: there is no principled winner inside one file."
        ),
        severity="error",
        scope="record",
    ),
    RuleSpec(
        rule_id="UNQ.DUPLICATE_FILE",
        dimension="uniqueness",
        name="Duplicate file",
        description=(
            "These file bytes were already ingested. Enforced at ingest by the unique "
            "file_hash (DuplicateFileError); the batch never lands, so no finding is written."
        ),
        severity="warning",
        scope="file",
        enforced_at="ingest",
    ),
    # ----------------------------------------------------------------------- validity
    RuleSpec(
        rule_id="VAL.NON_POSITIVE_PRICE",
        dimension="validity",
        name="Non-positive price",
        description="A price field is zero or negative.",
        severity="error",
        scope="record",
        params={"fields": ["open", "high", "low", "close"]},
    ),
    RuleSpec(
        rule_id="VAL.NEGATIVE_VOLUME",
        dimension="validity",
        name="Negative volume",
        description="Volume is below zero.",
        severity="error",
        scope="record",
    ),
    RuleSpec(
        rule_id="VAL.NON_INTEGER_VOLUME",
        dimension="validity",
        name="Non-integer volume",
        description=(
            "The source volume label carries a fractional part. Volume is a count of "
            "contracts, so ingest preserves the label in volume_source and this rule reads it."
        ),
        severity="warning",
        scope="record",
    ),
    RuleSpec(
        rule_id="VAL.OFF_TICK_PRICE",
        dimension="validity",
        name="Off-tick price",
        description=(
            "A price is not a multiple of the tick for (root, frequency, field). Flag only, "
            "never exclude: a systematic pattern more likely means the tick reference is "
            "wrong than that 84% of a contract's prices are invalid."
        ),
        severity="warning",
        scope="record",
        # Absolute tolerance is epsilon_ticks x tick. 0.01, 0.10 and 0.0025 are the ticks
        # that are inexact in IEEE 754; 0.25 and 1/64 are dyadic and exact (sample-corpus §7.2).
        params={"epsilon_ticks": 1e-4, "fields": ["open", "high", "low", "close"]},
    ),
    RuleSpec(
        rule_id="VAL.ZERO_VOLUME_WITH_RANGE",
        dimension="validity",
        name="Zero volume with a price range",
        description=(
            "Volume is zero but high > low. Asked of the bar interval, not of the frequency "
            "name: an intraday bar is emitted because something transacted, while a daily "
            "summary is published for listed contracts whether or not they traded."
        ),
        severity="warning",
        scope="record",
        params={"frequencies": ["intraday"], "daily_severity": "info"},
    ),
    RuleSpec(
        rule_id="VAL.PRICE_MAGNITUDE",
        dimension="validity",
        name="Implausible price magnitude",
        description=(
            "A price falls outside the plausible band for its root. Catches decimal shifts."
        ),
        severity="warning",
        scope="record",
        params={"bands": dict(PRICE_BANDS), "fields": ["open", "high", "low", "close"]},
    ),
    RuleSpec(
        rule_id="VAL.EXTREME_VOLUME",
        dimension="validity",
        name="Extreme volume",
        description="Volume above the plausible ceiling for the granularity.",
        severity="info",
        scope="record",
        # Per granularity, not per root: a daily volume is three orders of magnitude above a
        # minute bar's for the same contract.
        params={"max_plausible": {"minute": 100_000, "daily": 5_000_000}},
    ),
    # -------------------------------------------------------------------- consistency
    RuleSpec(
        rule_id="CON.HIGH_LT_LOW",
        dimension="consistency",
        name="High below low",
        description=(
            "high < low. The bar's range is inverted, so no other range test is meaningful."
        ),
        severity="error",
        scope="record",
    ),
    RuleSpec(
        rule_id="CON.OPEN_OUT_OF_RANGE",
        dimension="consistency",
        name="Open outside the bar range",
        description="open is outside [low, high]. Evaluated only where high >= low.",
        severity="error",
        scope="record",
    ),
    RuleSpec(
        rule_id="CON.CLOSE_OUT_OF_RANGE",
        dimension="consistency",
        name="Close outside the bar range",
        description=(
            "close is outside [low, high]. Evaluated only where high >= low. Asked of the "
            "bar interval, not of the frequency name: an intraday close is a trade and must "
            "sit inside the range, while a daily close is a settlement and is under no such "
            "obligation, so it drops to params.daily_severity and is explained by "
            "CON.DERIVED_BAR_INVALID on the bar instead of being excluded."
        ),
        severity="error",
        scope="record",
        params={"daily_severity": "warning"},
    ),
    RuleSpec(
        rule_id="CON.WEEKEND_RECORD",
        dimension="consistency",
        name="Weekend session",
        description=(
            "The derived session date falls on a Saturday or Sunday. Computed on the derived "
            "date and on nothing else: a vendor trading_date is an assertion, and feeding it "
            "here labels every Sunday-evening CME bar a weekend record."
        ),
        severity="error",
        scope="record",
    ),
    RuleSpec(
        rule_id="CON.RECORD_IN_HALT",
        dimension="consistency",
        name="Record inside a halt",
        description="The timestamp falls inside a maintenance break or trading halt.",
        severity="warning",
        scope="record",
    ),
    RuleSpec(
        rule_id="CON.RECORD_ON_HOLIDAY",
        dimension="consistency",
        name="Record on a holiday",
        description="The record's session is a calendar holiday.",
        severity="warning",
        scope="record",
    ),
    RuleSpec(
        rule_id="CON.STALE_REPEAT",
        dimension="consistency",
        name="Stale repeated bar",
        description=(
            "n consecutive records with identical OHLC and non-zero volume. One finding per "
            "run. n is per root: flat bars track liquidity, from 11% on ES to 80% on SR3."
        ),
        severity="warning",
        scope="session",
        params={"n": 30, "n_by_root": dict(STALE_REPEAT_N_BY_ROOT)},
    ),
    RuleSpec(
        rule_id="CON.PRICE_JUMP",
        dimension="consistency",
        name="Price jump",
        description="The absolute log return between consecutive records exceeds the threshold.",
        severity="info",
        scope="record",
        params={"threshold": {"minute": 0.05, "daily": 0.25}},
    ),
    RuleSpec(
        rule_id="CON.DERIVED_BAR_INVALID",
        dimension="consistency",
        name="Daily bar violates OHLC invariants",
        description=(
            "A daily bar has open or close outside [low, high], or high < low. Severity "
            "follows bar provenance: critical when Loupe derived the bar, because a defect "
            "escaped record validation; warning when a vendor supplied it, because a "
            "settlement close is not obliged to sit inside the traded range."
        ),
        severity="critical",
        scope="session",
        params={"vendor_severity": "warning", "basis": "clean"},
    ),
    # --------------------------------------------------------------------- timeliness
    RuleSpec(
        rule_id="TIM.OUT_OF_ORDER",
        dimension="timeliness",
        name="Out-of-order timestamp",
        description="ts_utc decreases as source_row increases within one contract and frequency.",
        severity="warning",
        scope="record",
    ),
    RuleSpec(
        rule_id="TIM.FUTURE_TIMESTAMP",
        dimension="timeliness",
        name="Future timestamp",
        description="The timestamp is after the moment the record was ingested.",
        severity="error",
        scope="record",
    ),
    RuleSpec(
        rule_id="TIM.BEFORE_LISTING",
        dimension="timeliness",
        name="Record before listing",
        description="The session precedes ref.contract.first_trade_date.",
        severity="warning",
        scope="record",
    ),
    RuleSpec(
        rule_id="TIM.AFTER_EXPIRY",
        dimension="timeliness",
        name="Record after expiry",
        description="The session follows ref.contract.last_trade_date.",
        severity="error",
        scope="record",
    ),
    RuleSpec(
        rule_id="TIM.OFF_GRID",
        dimension="timeliness",
        name="Off-grid timestamp",
        description="The timestamp is not aligned to the batch's inferred interval boundary.",
        severity="warning",
        scope="record",
    ),
    RuleSpec(
        rule_id="TIM.TIMEZONE_MISALIGNED",
        dimension="timeliness",
        name="Timezone misaligned",
        description=(
            "The file's 60-minute activity dead zone is offset from the expected maintenance "
            "break by a whole number of hours. If the timezone was misread every downstream "
            "number is wrong and no other rule notices, so this one is critical."
        ),
        severity="critical",
        scope="file",
        applies_to_frequency="minute",
        params={"min_records": 100, "min_active_hours": 20},
    ),
    # --------------------------------------------------------------- roll and expiry
    RuleSpec(
        rule_id="ROL.THIN_NEAR_EXPIRY",
        dimension="completeness",
        name="Thin volume near expiry",
        description=(
            "Volume collapses in the final sessions before expiry. Exists to suppress "
            "completeness alerts in that window rather than to report a defect."
        ),
        severity="info",
        scope="series",
        params={"days": 10, "collapse_ratio": 0.2},
    ),
    RuleSpec(
        rule_id="ROL.NO_SUCCESSOR",
        dimension="completeness",
        name="No successor contract",
        description=(
            "A contract is approaching expiry with no later-dated contract of the same root "
            "in the corpus, so the roll cannot be followed."
        ),
        severity="info",
        scope="series",
        params={"days": 30},
    ),
    # ----------------------------------------------------------------------- outliers
    # v1 optional (spec §10). Always info, never auto-excluded: an outlier is a question,
    # never a verdict, and any volatile window in 2021-2026 is full of legitimate extreme
    # returns. The Iglewicz-Hoaglin constants live here so they are tunable in the row.
    RuleSpec(
        rule_id="OUT.RETURN_MAD",
        dimension="validity",
        name="Outlying log return",
        description=(
            "Modified z-score on log returns exceeds the threshold. Robust to fat tails: a "
            "single extreme print inflates a standard deviation enough to hide itself, but "
            "not a median absolute deviation."
        ),
        severity="info",
        scope="record",
        params={"threshold": 3.5, "constant": 0.6745, "min_records": 30},
    ),
    RuleSpec(
        rule_id="OUT.VOLUME_MAD",
        dimension="validity",
        name="Outlying volume",
        description="The same modified z-score, on log volume rather than on log returns.",
        severity="info",
        scope="record",
        params={"threshold": 3.5, "constant": 0.6745, "min_records": 30},
    ),
)

CATALOGUE_BY_ID: Mapping[str, RuleSpec] = MappingProxyType({r.rule_id: r for r in CATALOGUE})

#: Rule IDs this slice's engine evaluates. `UNQ.DUPLICATE_FILE` is excluded because ingest
#: enforces it: the batch is refused outright, so no finding is ever written.
RULES_ENFORCED_BY_ENGINE: frozenset[str] = frozenset(
    spec.rule_id for spec in CATALOGUE if spec.enforced_at == "rules"
)

#: Cleaning consequences, spec §14. `error` and `critical` map to `exclude` by the §1
#: severity table; this names the two rules whose action is not that default.
#: `CON.DERIVED_BAR_INVALID` needs no entry: it is session-scope and carries no `record_id`,
#: so there is nothing for cleaning to exclude. Its critical branch blocks the series instead,
#: which `loupe.insights.gate` enforces.
#: `CON.CLOSE_OUT_OF_RANGE` needs no entry either, and deliberately so: its daily rows are
#: kept because the finding's own severity is `params.daily_severity`, not because a list
#: here exempts the rule. Cleaning stays a function of severity, and a deployment that wants
#: the exclusion back re-seeds the param rather than editing this set.
DEDUPE_DROP_RULES: frozenset[str] = frozenset({"UNQ.EXACT_DUPLICATE"})
NEVER_EXCLUDE_RULES: frozenset[str] = frozenset({"VAL.OFF_TICK_PRICE"})

#: specs/dq-rules-and-scoring.md §11.6. The Risk inventory's **Closing-day** column is a
#: statement about the session's *settlement* record, not the contract's worst issue of any
#: kind, and nothing on `dq.dq_rule` distinguishes the two — hence a named set rather than a
#: query. Membership test: the rule's subject can be the session's settlement record.
#: Applied together with `frequency = 'daily'`; at minute grain `VAL.OFF_TICK_PRICE` says
#: "off-tick price", not "off-tick close", and `CMP.SESSION_MISSING` says "no tape at all"
#: rather than "no settlement".
#: `UNQ.EXACT_DUPLICATE` is deliberately absent though a duplicated daily row is literally a
#: duplicated settlement: `dedupe_drop` resolves it automatically, so it is a changelog entry
#: rather than open settlement risk. A key conflict is two *different* settlement prices for
#: one session with no principled winner, which is what a risk manager must be told.
#: **No `REC.*` rule joins this set** (§11.6). `REC.CLOSE_CONVENTION` is the near miss: its
#: subject is plainly the settlement, but it is `info` and fires on the *expected* difference
#: between a settlement and a last trade, and the Closing-day column is what a risk manager
#: reads as what is *wrong* with a settlement. Reconciliation's contribution to the Risk view
#: is the corroboration state of §8.7 — which changes what an existing callout means — not
#: another callout.
SETTLEMENT_RULES: frozenset[str] = frozenset(
    {
        "CON.CLOSE_OUT_OF_RANGE",
        "CMP.SESSION_MISSING",
        "UNQ.KEY_CONFLICT",
        "VAL.OFF_TICK_PRICE",
    }
)

#: specs/dq-rules-and-scoring.md §11.7. The Analyst **Worst field** tile, derived from rule
#: identity rather than by grouping `dq.dq_finding.details` — that column is evidence and is
#: never grouped on (`specs/data-model.md`).
#:
#: Membership is a two-part test, because the tile answers *what is broken*: the rule must
#: **assert a defect**, and must **fix the field that defect is in**. "Fixes a field" alone
#: is too loose — it admits rules that name a field while claiming nothing is wrong with it.
#:
#: Three groups are therefore absent, and their absence is the design:
#:   * field-parametric — `CMP.NULL_FIELD`, `VAL.NON_POSITIVE_PRICE`, `VAL.OFF_TICK_PRICE`,
#:     `VAL.PRICE_MAGNITUDE`, `CON.HIGH_LT_LOW`, `CON.PRICE_JUMP`. Which field they implicate
#:     is known only per finding, in `details`.
#:   * record-, session- or series-shaped — all `UNQ.*`, `CMP.MISSING_TIMESTAMP`,
#:     `CMP.SESSION_MISSING`, `CMP.PARTIAL_SESSION`, `CMP.SPARSE_SERIES`, `CON.STALE_REPEAT`,
#:     `CON.DERIVED_BAR_INVALID`, all `ROL.*`. `CMP.MISSING_TIMESTAMP` belongs here and not
#:     under `timestamp`: its trigger is a run of expected slots with *no record*, so no
#:     timestamp value is wrong — the defect is absence, exactly as for the other two `CMP`
#:     session rules.
#:   * diagnostic rather than defect — `OUT.*`, always `info` and never auto-excluded (§10).
#:     A log return also spans two closes, so no individual close is accused.
RULE_SUBJECT_FIELD: Mapping[str, str] = MappingProxyType(
    {
        "CON.CLOSE_OUT_OF_RANGE": "close",
        "CON.OPEN_OUT_OF_RANGE": "open",
        "VAL.NEGATIVE_VOLUME": "volume",
        "VAL.NON_INTEGER_VOLUME": "volume",
        "VAL.ZERO_VOLUME_WITH_RANGE": "volume",
        "VAL.EXTREME_VOLUME": "volume",
        # Every `timestamp` entry fires on a record that *exists* and whose timestamp is
        # wrong — off the grid, out of order, misaligned, or placing the record on a
        # weekend, holiday or halt. That is what separates them from the absence rules.
        "TIM.AFTER_EXPIRY": "timestamp",
        "TIM.BEFORE_LISTING": "timestamp",
        "TIM.FUTURE_TIMESTAMP": "timestamp",
        "TIM.OFF_GRID": "timestamp",
        "TIM.OUT_OF_ORDER": "timestamp",
        "TIM.TIMEZONE_MISALIGNED": "timestamp",
        "CON.WEEKEND_RECORD": "timestamp",
        "CON.RECORD_IN_HALT": "timestamp",
        "CON.RECORD_ON_HOLIDAY": "timestamp",
    }
)
