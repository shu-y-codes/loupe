"""Seed `dq.dq_rule` and `dq.score_weight` from the declared catalogue.

The seeder is the *only* author of rules in v1: findings and suggestions are report-only
(spec §13, locked decision 10), so nothing at run time writes `dq.dq_rule`. It therefore
inserts absent rule IDs and refreshes existing `origin = 'builtin'` rows to catalogue values,
which is what carries a corrected default into a database that already exists.

Two seams are written now, before anything exercises them, because an untested guard will
have rotted by the time slice 6 needs it:

* The refresh is guarded ``WHERE origin = 'builtin'``. A row someone else authored is never
  touched, and the seeder reports how many it skipped.
* A missing row is re-inserted, so **disabling a rule is `enabled = FALSE`, never a delete**.
  `enabled` is consequently the one field the refresh preserves: it is operator state, not a
  catalogue value, and resetting it on every deploy would make the disable seam a lie. Every
  other field is the catalogue's, so a corrected threshold or severity lands on re-seed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import duckdb

from .catalogue import CATALOGUE, SCORE_WEIGHTS, RuleSpec


@dataclass(frozen=True)
class RuleSeedReport:
    """What a seed run did. Returned rather than logged, so tests can assert on it."""

    inserted: int
    refreshed: int
    skipped_foreign: int
    weights: int

    @property
    def total(self) -> int:
        return self.inserted + self.refreshed + self.skipped_foreign


def _row_values(spec: RuleSpec) -> list[object]:
    return [
        spec.rule_id,
        spec.dimension,
        spec.name,
        spec.description,
        spec.severity,
        spec.scope,
        spec.applies_to_frequency,
        json.dumps(dict(spec.params), sort_keys=True),
        spec.effective_triage_weight,
    ]


def seed_rules(con: duckdb.DuckDBPyConnection) -> tuple[int, int, int]:
    """Insert absent builtin rules and refresh the ones that are present.

    Returns `(inserted, refreshed, skipped_foreign)`. Idempotent: a second call over an
    unchanged catalogue inserts nothing and rewrites the same values.
    """
    existing = dict(
        con.execute("SELECT rule_id, origin FROM dq.dq_rule").fetchall()
    )

    inserted = 0
    refreshed = 0
    skipped_foreign = 0

    for spec in CATALOGUE:
        origin = existing.get(spec.rule_id)
        if origin is None:
            con.execute(
                """
                INSERT INTO dq.dq_rule
                  (rule_id, dimension, name, description, severity, scope,
                   applies_to_frequency, params, triage_weight, enabled, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'builtin')
                """,
                [*_row_values(spec), spec.enabled],
            )
            inserted += 1
            continue
        if origin != "builtin":
            # Someone else authored this ID. The catalogue does not own it.
            skipped_foreign += 1
            continue
        con.execute(
            """
            UPDATE dq.dq_rule
               SET dimension = ?, name = ?, description = ?, severity = ?, scope = ?,
                   applies_to_frequency = ?, params = ?, triage_weight = ?
             WHERE rule_id = ? AND origin = 'builtin'
            """,
            [*_row_values(spec)[1:], spec.rule_id],
        )
        refreshed += 1

    return inserted, refreshed, skipped_foreign


def seed_score_weights(con: duckdb.DuckDBPyConnection) -> int:
    """Write one `dq.score_weight` row per dimension (spec §11.2).

    These are the only weights in the score. `dq.dq_rule.triage_weight` orders the fix-first
    worklist and is never read here (§11.4).
    """
    con.executemany(
        "INSERT OR REPLACE INTO dq.score_weight (dimension, weight, enabled) VALUES (?, ?, TRUE)",
        list(SCORE_WEIGHTS.items()),
    )
    return len(SCORE_WEIGHTS)


def seed_quality(con: duckdb.DuckDBPyConnection) -> RuleSeedReport:
    """Seed rules and score weights together. This is what callers should use."""
    inserted, refreshed, skipped = seed_rules(con)
    return RuleSeedReport(inserted, refreshed, skipped, seed_score_weights(con))


def ruleset_hash(con: duckdb.DuckDBPyConnection) -> str:
    """A stable digest of the ruleset a run evaluated under.

    Recorded on `dq.dq_run` so that a score movement between two runs is attributable to the
    ruleset or to the data, and not ambiguously to both (spec §17 step 6). Disabled rules are
    part of the digest: turning one off changes the ruleset.
    """
    rules = con.execute(
        """
        SELECT rule_id, dimension, severity, scope, applies_to_frequency,
               CAST(params AS VARCHAR), enabled, origin
        FROM dq.dq_rule
        ORDER BY rule_id
        """
    ).fetchall()
    weights = con.execute(
        "SELECT dimension, weight, enabled FROM dq.score_weight ORDER BY dimension"
    ).fetchall()
    payload = json.dumps(
        {"rules": [list(map(str, row)) for row in rules],
         "weights": [list(map(str, row)) for row in weights]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
