"""The `quality` layer: rule catalogue, rule runners, cleaning decisions and the DQ score.

Checks, scores and flags — no charts, no HTTP. The API (slice 4) and the UI (slice 5) call
these functions; nothing in this package knows what a status code or a widget is.

Rules are rows, not code. `seed_quality` writes the declared catalogue into `dq.dq_rule` and
the §11.2 weights into `dq.score_weight`; `assess` then runs the enabled rules over a scope,
records cleaning decisions, and scores what it found — all reading thresholds, severities and
weights back from those rows.

`REC.*` is the one family that reads two granularities at once, so it is spread over four
modules on purpose: `reconciliation` holds the session frame the other three share,
`rules.reconciliation` writes the findings, `scoring` takes §8.6's denominator from the frame,
and `corroboration` reads the findings back to say what the tape makes of a *daily* finding —
writing nothing and scoring nothing. `patterns` and `suggestions` sit on top of all of it and
are reports: they read findings and propose, and they never mutate a rule or a calendar.
"""

from .catalogue import (
    CATALOGUE,
    DUPLICATE_RULES,
    GAPS_RULES,
    INVALID_RULES,
    RULE_SUBJECT_FIELD,
    RULES_ENFORCED_BY_ENGINE,
    SCORE_WEIGHTS,
    SETTLEMENT_RULES,
    STRIP_FAMILIES,
    STRIP_FAMILY_RULES,
    VOLUME_INVALID_RULES,
    RuleSpec,
    strip_family,
)
from .changelog import ChangelogEntry, changelog, latest_run
from .cleaning import CleaningReport, apply_default_cleaning, exclusion_rate
from .corroboration import CORROBORATED_RULES, Corroboration, FindingRef, corroborate
from .errors import LoupeQualityError, RulesNotSeeded
from .inventory import (
    ATTENTION_SEVERITIES,
    ContractRow,
    Issue,
    contract_rows,
    worst_field,
)
from .patterns import Pattern, find_patterns
from .reconciliation import (
    CROSS,
    ReconciliationScore,
    reconciliation_evidence,
    reconciliation_score,
)
from .registry import REGISTRY, Finding, RuleContext, RuleRefusal, RunScope
from .review import ReviewPage, review_checks
from .runner import RunResult, assess, run_rules, scoped
from .scoring import (
    DimensionScore,
    SliceScore,
    WorklistEntry,
    persist_daily_metrics,
    score_if_resolved,
    score_run,
    score_slice,
    worklist,
)
from .seed import RuleSeedReport, ruleset_hash, seed_quality, seed_rules, seed_score_weights
from .suggestions import Suggestion, suggest
from .windows import CoverageWindow, RollWindow, RunInputs

__all__ = [
    "ATTENTION_SEVERITIES",
    "CATALOGUE",
    "CORROBORATED_RULES",
    "CROSS",
    "ChangelogEntry",
    "CleaningReport",
    "ContractRow",
    "Corroboration",
    "CoverageWindow",
    "DimensionScore",
    "Finding",
    "FindingRef",
    "DUPLICATE_RULES",
    "GAPS_RULES",
    "INVALID_RULES",
    "Issue",
    "LoupeQualityError",
    "Pattern",
    "REGISTRY",
    "RULES_ENFORCED_BY_ENGINE",
    "RULE_SUBJECT_FIELD",
    "ReconciliationScore",
    "ReviewPage",
    "RollWindow",
    "RuleContext",
    "RuleRefusal",
    "RuleSeedReport",
    "RuleSpec",
    "RulesNotSeeded",
    "RunInputs",
    "RunResult",
    "RunScope",
    "SCORE_WEIGHTS",
    "SETTLEMENT_RULES",
    "STRIP_FAMILIES",
    "STRIP_FAMILY_RULES",
    "SliceScore",
    "Suggestion",
    "VOLUME_INVALID_RULES",
    "WorklistEntry",
    "apply_default_cleaning",
    "assess",
    "changelog",
    "contract_rows",
    "corroborate",
    "exclusion_rate",
    "find_patterns",
    "latest_run",
    "persist_daily_metrics",
    "reconciliation_evidence",
    "reconciliation_score",
    "review_checks",
    "ruleset_hash",
    "run_rules",
    "scoped",
    "score_if_resolved",
    "score_run",
    "score_slice",
    "seed_quality",
    "seed_rules",
    "seed_score_weights",
    "suggest",
    "strip_family",
    "worklist",
    "worst_field",
]
