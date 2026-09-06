"""The per-contract inventory row every persona's Summary table reads.

`score_slice` answers *how good is this contract at this frequency*. The Summary table asks a
coarser question — one row per contract — and asks it three ways, because the personas select
differently over the same findings (`specs/loupe-ui-design.md`). Composing that here rather
than in a handler or a widget keeps the rule in the layer that owns rules: the API renders
these rows, the UI picks which columns to show.

Nothing in this module is a score input. The rollup reuses the weighted `overall` that
§11.1-11.3 already produced; the callouts and the status are selections over findings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from .catalogue import RULE_SUBJECT_FIELD, SETTLEMENT_RULES
from .scoring import SliceScore

#: `specs/loupe-ui-design.md`, Risk → Summary. A contract is `ATTN` when it holds any open
#: finding of these severities, and `OK` otherwise. Not a score threshold: §11.5 has the score
#: as a navigation index rather than a grade, and a cut at 70-or-80-or-90 turns it into one
#: while answering a question the severities already answer exactly. These are also the
#: severities default cleaning acts on (§14), so `ATTN` means "something here was excluded or
#: blocked" — which is what a risk manager is asking.
ATTENTION_SEVERITIES: tuple[str, ...] = ("error", "critical")

#: Ordering for "worst". Severity first, then how many: one `critical` outranks two hundred
#: `info`. This is deliberately not `_top_issues`' scope-wide ordering, which is by count —
#: a book-level list is asking what is most widespread, a per-contract callout is asking what
#: is most serious about this one contract.
_SEVERITY_RANK: dict[str, int] = {"critical": 4, "error": 3, "warning": 2, "info": 1}


@dataclass(frozen=True)
class Issue:
    """One callout: the rule that fired, in the catalogue's own words."""

    rule_id: str
    label: str
    severity: str
    findings: int

    def as_json(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "label": self.label,
            "severity": self.severity,
            "findings": self.findings,
        }


@dataclass(frozen=True)
class ContractRow:
    """One inventory row. Every persona reads this; each shows a different subset."""

    contract_id: str
    score: float | None
    status: str
    frequencies: list[str]
    finding_count: int
    top_issue: Issue | None
    settlement_issue: Issue | None

    def as_json(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "score": self.score,
            "status": self.status,
            "frequencies": self.frequencies,
            "finding_count": self.finding_count,
            "top_issue": self.top_issue.as_json() if self.top_issue else None,
            "settlement_issue": (
                self.settlement_issue.as_json() if self.settlement_issue else None
            ),
        }


@dataclass(frozen=True)
class _Tally:
    """Open findings for one contract × rule × frequency, with the rule's own label."""

    contract_id: str
    rule_id: str
    frequency: str | None
    severity: str
    label: str
    findings: int


def _tallies(
    con: duckdb.DuckDBPyConnection, run_id: str, contracts: list[str]
) -> list[_Tally]:
    """One pass over the run's open findings; everything below is composed from it.

    `f.severity` and not `r.severity`: the finding carries the severity it actually fired at,
    which is the point of `params.daily_severity` on `CON.CLOSE_OUT_OF_RANGE` (§6). Reading
    the declared severity here would re-erase the daily/intraday distinction slice 2 drew.
    """
    clause, args = ("TRUE", [])
    if contracts:
        placeholders = ", ".join("?" for _ in contracts)
        clause, args = (f"f.contract_id IN ({placeholders})", list(contracts))
    rows = con.execute(
        f"""
        SELECT f.contract_id, f.rule_id, f.frequency, f.severity, r.name, count(*)
        FROM dq.dq_finding f JOIN dq.dq_rule r USING (rule_id)
        WHERE f.run_id = ? AND f.status = 'open' AND f.contract_id IS NOT NULL AND {clause}
        GROUP BY 1, 2, 3, 4, 5
        """,
        [run_id, *args],
    ).fetchall()
    return [_Tally(r[0], r[1], r[2], r[3], r[4], int(r[5])) for r in rows]


def _worst(tallies: list[_Tally]) -> Issue | None:
    """Most serious first, then most numerous, then rule ID so the answer is stable."""
    if not tallies:
        return None
    best = max(
        tallies,
        key=lambda t: (_SEVERITY_RANK.get(t.severity, 0), t.findings, t.rule_id),
    )
    return Issue(best.rule_id, best.label, best.severity, best.findings)


def _settlement(tallies: list[_Tally]) -> Issue | None:
    """The Closing-day callout: `SETTLEMENT_RULES` at daily grain only (§11.6).

    The frequency clause is load-bearing, not tidying. `VAL.OFF_TICK_PRICE` on a minute record
    says "off-tick price", not "off-tick close"; `CMP.SESSION_MISSING` at minute grain says
    "no tape at all", not "no settlement". A contract held only at minute grain therefore has
    no closing-day callout, which is the intended reading — settlement lives in the daily file.
    """
    return _worst(
        [t for t in tallies if t.rule_id in SETTLEMENT_RULES and t.frequency == "daily"]
    )


def contract_rows(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    slices: list[SliceScore],
    *,
    contracts: list[str] | None = None,
) -> list[ContractRow]:
    """Roll `slices` up to one row per contract and attach the findings each row calls out.

    **The rollup is the minimum across the contract's slices**, not a mean of them: a contract
    is as trustworthy as its worst frequency. A record-weighted mean is the alternative and
    lets a large clean minute tape bury a broken daily file — the defect this corpus is full
    of. `insufficient_data` slices carry no `overall` and are skipped rather than counted as
    zero; a contract whose every slice is insufficient scores `None`.
    """
    in_scope = sorted({s.contract_id for s in slices})
    tallies = _tallies(con, run_id, contracts or in_scope)
    by_contract: dict[str, list[_Tally]] = {}
    for tally in tallies:
        by_contract.setdefault(tally.contract_id, []).append(tally)

    rows: list[ContractRow] = []
    for contract_id in in_scope:
        mine = [s for s in slices if s.contract_id == contract_id]
        scored = [s.overall for s in mine if s.overall is not None]
        found = by_contract.get(contract_id, [])
        attention = any(t.severity in ATTENTION_SEVERITIES for t in found)
        rows.append(
            ContractRow(
                contract_id=contract_id,
                score=min(scored) if scored else None,
                status="ATTN" if attention else "OK",
                frequencies=sorted({s.frequency for s in mine}),
                finding_count=sum(t.findings for t in found),
                top_issue=_worst(found),
                settlement_issue=_settlement(found),
            )
        )
    return rows


def worst_field(
    con: duckdb.DuckDBPyConnection, run_id: str, contracts: list[str]
) -> dict[str, Any] | None:
    """The Analyst headline tile, from rule identity — never by grouping `details` (§11.7).

    Returns `None` when a scope's open findings are all from unmapped rules. The tile then
    reads "not applicable" rather than inventing a field, and that is a realistic state rather
    than a corner case: outliers and missing-slot runs are both unmapped by design, so a
    corpus whose findings are only those has no worst field to report.
    """
    totals: dict[str, int] = {}
    open_findings = 0
    for tally in _tallies(con, run_id, contracts):
        open_findings += tally.findings
        field = RULE_SUBJECT_FIELD.get(tally.rule_id)
        if field is not None:
            totals[field] = totals.get(field, 0) + tally.findings
    if not totals:
        return None
    field = max(totals, key=lambda f: (totals[f], f))
    # State the denominator, for the reason §11.5 makes scores state theirs: the map excludes
    # three groups of rules by design, so the winning field can rest on a small minority of
    # what is open. A bare "close" invites the reader to assume it summarises everything.
    return {
        "field": field,
        "findings": totals[field],
        "considered": sum(totals.values()),
        "total": open_findings,
    }
