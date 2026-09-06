"""The `quality` layer: rule catalogue, rule runners, cleaning decisions and the DQ score.

Checks, scores and flags — no charts, no HTTP. The API (slice 4) and the UI (slice 5) call
these functions; nothing in this package knows what a status code or a widget is.

Rules are rows, not code. `seed_quality` writes the declared catalogue into `dq.dq_rule` and
the §11.2 weights into `dq.score_weight`; `assess` then runs the enabled rules over a scope,
records cleaning decisions, and scores what it found — all reading thresholds, severities and
weights back from those rows.

`CON.DERIVED_BAR_INVALID` and `OUT.*` are deferred to slice 3, where bar provenance and the
MAD method are specified (`plans/02-quality.md`). `REC.*`, patterns and suggestions are slice 6.
"""

from .catalogue import (
    CATALOGUE,
    RULE_SUBJECT_FIELD,
    RULES_ENFORCED_BY_ENGINE,
    SCORE_WEIGHTS,
    SETTLEMENT_RULES,
    RuleSpec,
)
from .changelog import ChangelogEntry, changelog, latest_run
from .cleaning import CleaningReport, apply_default_cleaning, exclusion_rate
from .errors import LoupeQualityError, RulesNotSeeded
from .inventory import (
    ATTENTION_SEVERITIES,
    ContractRow,
    Issue,
    contract_rows,
    worst_field,
)
from .registry import REGISTRY, Finding, RuleContext, RuleRefusal, RunScope
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
from .windows import CoverageWindow, RollWindow, RunInputs

__all__ = [
    "ATTENTION_SEVERITIES",
    "CATALOGUE",
    "REGISTRY",
    "RULES_ENFORCED_BY_ENGINE",
    "RULE_SUBJECT_FIELD",
    "SCORE_WEIGHTS",
    "SETTLEMENT_RULES",
    "ChangelogEntry",
    "CleaningReport",
    "ContractRow",
    "CoverageWindow",
    "DimensionScore",
    "Finding",
    "Issue",
    "LoupeQualityError",
    "RollWindow",
    "RuleContext",
    "RuleRefusal",
    "RuleSeedReport",
    "RuleSpec",
    "RulesNotSeeded",
    "RunInputs",
    "RunResult",
    "RunScope",
    "SliceScore",
    "WorklistEntry",
    "apply_default_cleaning",
    "assess",
    "changelog",
    "contract_rows",
    "exclusion_rate",
    "latest_run",
    "persist_daily_metrics",
    "ruleset_hash",
    "run_rules",
    "score_if_resolved",
    "score_run",
    "score_slice",
    "scoped",
    "seed_quality",
    "seed_rules",
    "seed_score_weights",
    "worklist",
    "worst_field",
]
