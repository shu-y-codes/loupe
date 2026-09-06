"""What the tape says about a daily finding (`specs/dq-rules-and-scoring.md` §8.7).

Reconciliation's value to the Risk persona is **attribution, not detection**. A daily defect is
already visible in the daily file; what one file cannot say is *which of its numbers to
distrust*. `CON.CLOSE_OUT_OF_RANGE` is the worked example, and it has two readings that call
for opposite responses:

- the range is right and the settlement sits outside it, which is ordinary behaviour for a
  price struck by committee rather than traded;
- the range is *understated*, because the tape found prints outside it — and then the close may
  be sound and the range is the broken field.

Without the tape the second is invisible and the reader reaches for the close.

**This is not a rule and it writes no finding.** It is a reading of findings that already
exist, so it enters no score: §8.6's numerator is unchanged. That is why it lives here rather
than beside the runners or inside the scorer — a runner writes findings and a scorer produces
numbers, and filing this with either would invite a later contributor to make it do the thing
its neighbours do.

**Four answers, not three.** `confirmed`, `disputed` and `not_comparable` are §8.7's states;
*absent* is the fourth and means something else entirely — corroboration does not apply to this
finding at all. A minute-grain timeliness finding is not a claim the daily file can speak to.
`not_comparable` means it applies and could not be evaluated. Collapsing the two, or collapsing
`confirmed` into `not_comparable`, is the failure this module exists to prevent: "we could not
check" must never render as "we checked and it holds".
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from .reconciliation import CROSS

#: The rules a daily finding's corroboration applies to.
#:
#: Membership follows §8.7's states, which are all statements about **the stated range**:
#: `confirmed` says the range is measured correctly, `disputed` says it is wrong. So the set is
#: the rules whose reading changes depending on whether the range can be trusted — the daily
#: bar's own coherence rules. `CON.CLOSE_OUT_OF_RANGE` is the one the spec works through;
#: `CON.OPEN_OUT_OF_RANGE` and `CON.HIGH_LT_LOW` are the same shape, a value judged against a
#: range the tape can independently measure.
#:
#: Everything else is absent, and absence is the fourth answer rather than an oversight. A
#: `TIM.*` or `UNQ.*` finding is about a timestamp or a duplicate key, which the minute tape
#: cannot adjudicate; `VAL.OFF_TICK_PRICE` is about a lattice, not a range; and every `REC.*`
#: finding *is* the tape's statement, so qualifying it with itself would be circular.
#:
#: It lives here rather than in `catalogue.py` with `SETTLEMENT_RULES` deliberately. Those sets
#: classify rules for the engine and the seeder; this one is the applicability domain of one
#: reading, and moving it next to them would make it look like a property of the rule.
CORROBORATED_RULES: frozenset[str] = frozenset(
    {"CON.CLOSE_OUT_OF_RANGE", "CON.OPEN_OUT_OF_RANGE", "CON.HIGH_LT_LOW"}
)

#: Only a disagreement on `high` or `low` disputes a *range* (§8.7). A disagreement on `open`
#: means the vendor's first print is wrong, which is a defect in its own right and says nothing
#: about whether the close sits inside a correctly measured range.
RANGE_FIELDS: frozenset[str] = frozenset({"high", "low"})

CONFIRMED = "confirmed"
DISPUTED = "disputed"
NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True)
class FindingRef:
    """The columns of a finding this reading needs. Not the finding itself.

    `run_id` matters: a daily finding is qualified by the `REC.*` findings from **its own
    run**, so a re-run that fixed the tape does not retrospectively dispute an old finding, and
    an old run's disagreements do not dispute a new one.
    """

    finding_id: str
    rule_id: str
    frequency: str | None
    contract_id: str | None
    trade_date: date | None
    run_id: str | None = None

    @property
    def applies(self) -> bool:
        """Whether corroboration is a question that can be asked of this finding at all."""
        return (
            self.rule_id in CORROBORATED_RULES
            and self.frequency == "daily"
            and self.contract_id is not None
            and self.trade_date is not None
        )


@dataclass(frozen=True)
class Corroboration:
    """One finding's state, the sentence that states it, and the evidence behind it."""

    state: str
    reason: str
    detail: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "detail": self.detail}


def corroborate(
    con: duckdb.DuckDBPyConnection, findings: Sequence[FindingRef]
) -> dict[str, Corroboration]:
    """Resolve a page of findings in **one pass**, keyed by `finding_id`.

    One pass rather than one query per row, because a page is a hundred findings and the
    evidence is three lookups shared across all of them (`specs/api-contract.md` §6.2).
    Findings the reading does not apply to are simply absent from the result — the caller
    renders no `corroboration` object for them, which is the fourth answer.
    """
    applicable = [f for f in findings if f.applies]
    if not applicable:
        return {}

    contracts = sorted({f.contract_id for f in applicable if f.contract_id})
    sessions = {(f.contract_id, f.trade_date) for f in applicable}
    grains = _grains_held(con, contracts)
    compared = _compared_sessions(con, contracts)
    disagreements = _range_disagreements(con, sessions)
    conventions = _close_conventions(con, sessions)
    min_coverage = _min_coverage_pct(con)

    resolved: dict[str, Corroboration] = {}
    for finding in applicable:
        key = (finding.contract_id, finding.trade_date)
        resolved[finding.finding_id] = _state(
            key=key,
            grains=grains.get(finding.contract_id or "", ()),
            compared=compared.get(key),
            disagreements=disagreements.get((*key, finding.run_id), []),
            convention=conventions.get((*key, finding.run_id)),
            min_coverage=min_coverage,
        )
    return resolved


def _state(
    *,
    key: tuple[str | None, date | None],
    grains: tuple[str, ...],
    compared: tuple[float | None, int, int] | None,
    disagreements: list[dict[str, Any]],
    convention: dict[str, Any] | None,
    min_coverage: float,
) -> Corroboration:
    """§8.7's table, in order. Every branch ends in a state and a sentence that justifies it."""
    contract_id = key[0]

    if len(grains) < 2:
        held = grains[0] if grains else "no"
        return Corroboration(
            state=NOT_COMPARABLE,
            reason=(
                f"Only {held} records are held for {contract_id}. Reconciliation compares the "
                "vendor's daily bar against one derived from the minute tape and needs both."
            ),
            detail={"minute_coverage_pct": None, "frequencies_held": list(grains)},
        )

    if compared is None:
        return Corroboration(
            state=NOT_COMPARABLE,
            reason=(
                "This session falls outside the window where the two granularities overlap, "
                "so the tape has nothing to say about it."
            ),
            detail={"minute_coverage_pct": None, "frequencies_held": list(grains)},
        )

    coverage_pct, minute_records, expected_slots = compared
    coverage_display = None if coverage_pct is None else round(100.0 * coverage_pct, 2)
    if coverage_pct is None or coverage_pct < min_coverage:
        return Corroboration(
            state=NOT_COMPARABLE,
            reason=(
                "The minute tape holds "
                + (
                    "an unknown share"
                    if coverage_display is None
                    else f"{coverage_display}%"
                )
                + f" of this session's expected slots, below the {round(100 * min_coverage, 2)}%"
                " a range comparison needs. An incomplete session cannot reproduce a high or a"
                " low, so neither confirming nor disputing the range would be honest."
            ),
            detail={
                "minute_coverage_pct": coverage_display,
                "minute_records": minute_records,
                "expected_slots": expected_slots,
            },
        )

    if disagreements:
        worst = max(disagreements, key=lambda d: abs(d.get("difference") or 0))
        fields = sorted({str(d.get("field")) for d in disagreements})
        return Corroboration(
            state=DISPUTED,
            reason=(
                f"The minute tape disagrees with the stated {' and '.join(fields)} for this "
                "session, so the range is itself in question and the finding should be re-read "
                "as a range defect rather than a statement about the close."
            ),
            detail={
                "field": worst.get("field"),
                "ticks": worst.get("difference_ticks"),
                "difference": worst.get("difference"),
                "minute_coverage_pct": coverage_display,
                "finding_ids": [d["finding_id"] for d in disagreements],
            },
        )

    detail: dict[str, Any] = {"minute_coverage_pct": coverage_display}
    if convention is not None:
        # Read off the one finding that already measured this session's close gap, rather than
        # recomputing it here: the close-convention rule owns that arithmetic and a second
        # copy could disagree with the finding printed beside it.
        detail["close_gap_ticks"] = convention.get("close_gap_ticks")
        detail["close_at_mark"] = convention.get("close_at_mark")
    return Corroboration(
        state=CONFIRMED,
        reason=(
            "The vendor's high and low agree with the minute tape for this session, so the "
            "traded range is measured correctly and the finding is about the value sitting "
            "outside it."
        ),
        detail=detail,
    )


# ------------------------------------------------------------------------------- evidence


def _grains_held(
    con: duckdb.DuckDBPyConnection, contracts: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    """Which granularities each contract holds records at — the first of §8.7's three tests."""
    if not contracts:
        return {}
    placeholders = ", ".join("?" for _ in contracts)
    rows = con.execute(
        f"""
        SELECT contract_id, frequency
        FROM stage.market_record
        WHERE contract_id IN ({placeholders})
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        list(contracts),
    ).fetchall()
    held: dict[str, list[str]] = {}
    for contract_id, frequency in rows:
        held.setdefault(contract_id, []).append(frequency)
    return {contract_id: tuple(f) for contract_id, f in held.items()}


def _compared_sessions(
    con: duckdb.DuckDBPyConnection, contracts: Sequence[str]
) -> dict[tuple[str, date], tuple[float | None, int, int]]:
    """The reconcilable sessions and the coverage each comparison rested on.

    Read from `mart.dq_metric_daily` at `frequency = 'cross'`, which the scorer writes for
    exactly the sessions the frame found reconcilable. A session that reconciled cleanly writes
    **no finding**, so findings alone cannot distinguish "compared and agreed" from "never
    compared" — that is the whole reason the cross row exists rather than being derived here.
    """
    if not contracts:
        return {}
    placeholders = ", ".join("?" for _ in contracts)
    rows = con.execute(
        f"""
        SELECT contract_id, trade_date, expected_records, actual_records
        FROM mart.dq_metric_daily
        WHERE frequency = ? AND dimension = 'reconciliation'
          AND contract_id IN ({placeholders})
        """,
        [CROSS, *contracts],
    ).fetchall()
    out: dict[tuple[str, date], tuple[float | None, int, int]] = {}
    for contract_id, trade_date, expected, actual in rows:
        expected = int(expected or 0)
        actual = int(actual or 0)
        out[(contract_id, trade_date)] = (
            (actual / expected) if expected else None,
            actual,
            expected,
        )
    return out


def _session_clause(
    sessions: Iterable[tuple[str | None, date | None]],
) -> tuple[str, list[Any]]:
    pairs = [(c, d) for c, d in sessions if c and d]
    if not pairs:
        return "FALSE", []
    clause = " OR ".join("(f.contract_id = ? AND f.trade_date = ?)" for _ in pairs)
    args: list[Any] = []
    for contract_id, trade_date in pairs:
        args.extend([contract_id, trade_date])
    return f"({clause})", args


def _range_disagreements(
    con: duckdb.DuckDBPyConnection,
    sessions: Iterable[tuple[str | None, date | None]],
) -> dict[tuple[str, date, str | None], list[dict[str, Any]]]:
    """`REC.OHLC_DISAGREE` on `high` or `low`, by session and run — what makes a range disputed."""
    clause, args = _session_clause(sessions)
    if not args:
        return {}
    rows = con.execute(
        f"""
        SELECT f.contract_id, f.trade_date, CAST(f.run_id AS VARCHAR),
               CAST(f.finding_id AS VARCHAR), CAST(f.details AS VARCHAR)
        FROM dq.dq_finding f
        WHERE f.rule_id = 'REC.OHLC_DISAGREE' AND {clause}
        """,
        args,
    ).fetchall()
    out: dict[tuple[str, date, str | None], list[dict[str, Any]]] = {}
    for contract_id, trade_date, run_id, finding_id, details in rows:
        payload = json.loads(details) if details else {}
        if payload.get("field") not in RANGE_FIELDS:
            continue
        out.setdefault((contract_id, trade_date, run_id), []).append(
            {**payload, "finding_id": finding_id}
        )
    return out


def _close_conventions(
    con: duckdb.DuckDBPyConnection,
    sessions: Iterable[tuple[str | None, date | None]],
) -> dict[tuple[str, date, str | None], dict[str, Any]]:
    """`REC.CLOSE_CONVENTION`'s evidence, for the gap a confirmed reading quotes."""
    clause, args = _session_clause(sessions)
    if not args:
        return {}
    rows = con.execute(
        f"""
        SELECT f.contract_id, f.trade_date, CAST(f.run_id AS VARCHAR), CAST(f.details AS VARCHAR)
        FROM dq.dq_finding f
        WHERE f.rule_id = 'REC.CLOSE_CONVENTION' AND {clause}
        """,
        args,
    ).fetchall()
    return {
        (contract_id, trade_date, run_id): json.loads(details) if details else {}
        for contract_id, trade_date, run_id, details in rows
    }


def _min_coverage_pct(con: duckdb.DuckDBPyConnection) -> float:
    """The gate, from `REC.OHLC_DISAGREE`'s seeded row rather than from a literal here.

    Corroboration must draw the line in the same place the rule did. A second copy would let
    this module call a session comparable that the rule declined to compare, and then report
    `confirmed` on the strength of a comparison that never happened.
    """
    row = con.execute(
        "SELECT params->>'min_coverage_pct' FROM dq.dq_rule WHERE rule_id = 'REC.OHLC_DISAGREE'"
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.98
