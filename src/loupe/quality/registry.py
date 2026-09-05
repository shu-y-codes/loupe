"""Runner registry, the finding shape, and the context a runner is handed.

A runner is a function from a `RuleContext` to a list of `Finding`s. It reads its thresholds
from `ctx.params` — the seeded `dq.dq_rule` row — and never from a literal, so changing a
default is a re-seed rather than a deploy.

A runner that cannot get the inputs it needs raises `RuleRefusal`. Refusing is a first-class
outcome, distinct from "evaluated and found nothing": the session-grained completeness rules
must not evaluate without the calendar, because a session with no calendar row looks exactly
like a session that is missing (`plans/02-quality.md` done-when 6, spec §3).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import duckdb

#: The scoped record set every runner queries. A temp table rather than a view so that the
#: scope filter is applied once per run instead of once per rule.
RECORDS = "dq_scope_records"

#: The coverage and roll windows for that record set, published as a table so rule SQL can
#: join to them instead of receiving them as literals.
WINDOWS = "dq_scope_windows"

VALID_FREQUENCIES = ("minute", "daily")


class RuleRefusal(Exception):
    """A rule declines to evaluate because an input it requires is unavailable.

    Not an error: evaluating a completeness rule without a calendar would report normal
    market behaviour as missing data, which is worse than reporting nothing.
    """


@dataclass(frozen=True)
class Finding:
    """One `dq.dq_finding` row, before it is written.

    A range is one row, not one row per slot: `ts_start_utc` / `ts_end_utc` with
    `affected_rows` set to the slot count is what keeps a 1,380-slot gap from becoming 1,380
    findings (`specs/data-model.md` §4).
    """

    rule_id: str
    severity: str
    contract_id: str | None = None
    frequency: str | None = None
    compare_frequency: str | None = None
    trade_date: date | None = None
    ts_start_utc: datetime | None = None
    ts_end_utc: datetime | None = None
    record_id: int | None = None
    affected_rows: int = 1
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleRow:
    """A seeded `dq.dq_rule` row, as the engine reads it back."""

    rule_id: str
    dimension: str
    name: str
    severity: str
    scope: str
    applies_to_frequency: str | None
    params: Mapping[str, Any]
    enabled: bool
    triage_weight: float


@dataclass(frozen=True)
class RunScope:
    """What a rule pass covers. Every field is a narrowing; all null means the whole corpus."""

    batch_id: str | None = None
    contract_ids: tuple[str, ...] | None = None
    frequencies: tuple[str, ...] | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "contract_ids": list(self.contract_ids) if self.contract_ids else None,
            "frequencies": list(self.frequencies) if self.frequencies else None,
        }


@dataclass(frozen=True)
class RuleContext:
    """Everything a runner is given: the connection, its own row, and the shared inputs."""

    con: duckdb.DuckDBPyConnection
    rule: RuleRow
    scope: RunScope
    inputs: Any  # RunInputs; typed loosely to keep windows.py from importing this module

    @property
    def params(self) -> Mapping[str, Any]:
        return self.rule.params

    @property
    def severity(self) -> str:
        return self.rule.severity

    def param(self, name: str, default: Any = None) -> Any:
        """A threshold, from the seeded row. Runners must not carry their own defaults."""
        return self.rule.params.get(name, default)

    def frequency_filter(self, alias: str = "r") -> str:
        """SQL restricting the record set to the granularity this rule applies to.

        `applies_to_frequency` comes from a `CHECK`-free column, so the value is validated
        against the known granularities before it is inlined.
        """
        wanted = self.rule.applies_to_frequency
        if wanted is None:
            return "TRUE"
        if wanted not in VALID_FREQUENCIES:
            raise ValueError(f"{self.rule.rule_id}: unknown applies_to_frequency {wanted!r}")
        return f"{alias}.frequency = '{wanted}'"

    def finding(self, **kwargs: Any) -> Finding:
        """A finding carrying this rule's id and severity unless one is passed explicitly."""
        kwargs.setdefault("rule_id", self.rule.rule_id)
        kwargs.setdefault("severity", self.rule.severity)
        return Finding(**kwargs)


Runner = Callable[[RuleContext], list[Finding]]

REGISTRY: dict[str, Runner] = {}


def rule(rule_id: str) -> Callable[[Runner], Runner]:
    """Register a runner against a catalogue rule ID.

    Registration is by ID rather than by name so that the parity test can compare the
    registry, the catalogue and the spec's in-scope list as three sets.
    """

    def register(runner: Runner) -> Runner:
        if rule_id in REGISTRY:
            raise ValueError(f"duplicate runner registered for {rule_id}")
        REGISTRY[rule_id] = runner
        return runner

    return register
