"""Summary, metrics, findings, rules and runs (`specs/api-contract.md` §6).

Findings are **read-only in v1**. `POST .../findings/{id}/review` and catalogue mutation are
extensions (§6.3, §6.4) and are deliberately absent from this router rather than present and
refusing: an endpoint that exists and returns 405 invites a client to keep the button.

Scores are not computed here. `quality.score_slice` runs inside `quality.scoped`, so a score
is measured over exactly the record set and windows its findings were drawn from; a handler
that added up dimension scores itself would be a second, quietly different scorer.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query

from loupe.insights import build_bars
from loupe.quality import (
    RunScope,
    assess,
    changelog,
    contract_rows,
    review_checks,
    scoped,
    score_slice,
    worst_field,
)
from loupe.quality.corroboration import FindingRef, corroborate
from loupe.quality.errors import RulesNotSeeded

from ..deps import (
    BasisParam,
    Con,
    EndDateParam,
    FrequencyParam,
    LimitParam,
    OffsetParam,
    StartDateParam,
)
from ..errors import ProblemError
from ..models import (
    AggregatedIssue,
    ChangelogEntry,
    ChangelogResponse,
    ContractSummary,
    Corroboration,
    DimensionScore,
    DqChecksResponse,
    DqMetricsResponse,
    DqSummaryResponse,
    FamilyCard,
    Finding,
    FindingsResponse,
    Overlay,
    OverlayMark,
    Rule,
    RulesResponse,
    RunSummary,
    Scope,
    SliceScore,
)

router = APIRouter(prefix="/dq", tags=["data quality"])

ContractParam = Annotated[
    str | None, Query(description="Contract id, or a comma-separated list.")
]

GROUP_BY_COLUMN = {
    "day": "trade_date",
    "contract": "contract_id",
    "dimension": "dimension",
    "frequency": "frequency",
}


def _contracts(contract: str | None) -> list[str]:
    return [c.strip() for c in contract.split(",") if c.strip()] if contract else []


def _json(value: Any) -> Any:
    """`details` and `params` come back from DuckDB as JSON text."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _latest_run(con) -> str | None:
    row = con.execute(
        "SELECT run_id FROM dq.dq_run WHERE status = 'succeeded' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else None


def _as_slice_score(score) -> SliceScore:
    return SliceScore(
        contract_id=score.contract_id,
        frequency=score.frequency,
        overall=score.overall,
        insufficient_data=score.insufficient_data,
        records=score.records,
        dimensions_in_scope=score.dimensions_in_scope,
        dimensions_not_in_scope=score.dimensions_not_in_scope,
        scope_signature=score.scope_signature,
        weight_denominator=score.weight_denominator,
        dimensions={
            name: DimensionScore(dimension=name, **d.as_json())
            for name, d in score.dimensions.items()
        },
    )


@router.get("/summary", response_model=DqSummaryResponse, summary="Dashboard summary")
def summary(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
    basis: BasisParam = "clean",
    frequency: Annotated[
        str | None,
        Query(
            description="Comma-separated grains. Defaults to **every** frequency held for "
            "the contracts in scope, unlike the analytic endpoints.",
        ),
    ] = None,
) -> DqSummaryResponse:
    """One request per page load: score, dimensions in scope, record counts, top issues.

    Which dimensions were in scope is part of the score, not metadata about it — equal
    `scope_signature` means two scores are comparable, unequal means the UI must say so.
    """
    contracts = _contracts(contract)
    frequencies = [f.strip() for f in frequency.split(",")] if frequency else []
    run_id = _latest_run(con)
    if run_id is None:
        return DqSummaryResponse(
            scope=Scope(contracts=contracts, start=start, end=end, basis=basis),
            overall_score=None,
            score_method=_SCORE_METHOD,
            slices=[],
            records=_record_counts(con, contracts),
            top_issues=[],
            meta={"reason": "No completed validation run. POST /v1/dq/runs to create one."},
        )

    scope = RunScope(
        contract_ids=tuple(contracts) or None,
        frequencies=tuple(frequencies) or None,
    )
    with scoped(con, scope) as (_inputs, _rows, _records):
        pairs = con.execute(
            "SELECT DISTINCT contract_id, frequency FROM dq_scope_records ORDER BY 1, 2"
        ).fetchall()
        scores = [score_slice(con, run_id, c, f) for c, f in pairs]

    resolved = sorted({s.frequency for s in scores})
    scored = [s.overall for s in scores if s.overall is not None]
    in_scope = contracts or sorted({s.contract_id for s in scores})
    rows = contract_rows(con, run_id, scores, contracts=contracts or None)
    return DqSummaryResponse(
        scope=Scope(
            contracts=in_scope,
            start=start,
            end=end,
            basis=basis,
            frequency=",".join(resolved) or None,
            frequency_defaulted=not frequencies,
        ),
        overall_score=round(sum(scored) / len(scored), 1) if scored else None,
        score_method=_SCORE_METHOD,
        slices=[_as_slice_score(s) for s in scores],
        contracts=[ContractSummary(**row.as_json()) for row in rows],
        worst_field=worst_field(con, run_id, in_scope),
        records=_record_counts(con, contracts),
        top_issues=_top_issues(con, run_id, contracts),
        meta={
            "run_id": run_id,
            "weight_policy": "renormalise over dimensions in scope: overall = "
            "Σ(w×s) / Σ(w). See specs/dq-rules-and-scoring.md.",
        },
    )


@router.get("/checks", response_model=DqChecksResponse, summary="Reviewer strip")
def checks(
    con: Con,
    contract: Annotated[str, Query(description="One contract. Required.")],
    start: StartDateParam = None,
    end: EndDateParam = None,
    family: Annotated[
        str,
        Query(
            description="Selected overlay family: `gaps`, `duplicates`, `invalid`, or "
            "`patterns`. Default `gaps`.",
        ),
    ] = "gaps",
    basis: BasisParam = "clean",
) -> DqChecksResponse:
    """Cards, overlay marks, picture and aggregated issues for one contract.

    Composed in `quality`. Grouping `findings[]` in a widget is not a substitute.
    """
    try:
        page = review_checks(
            con, contract, start=start, end=end, family=family, basis=basis
        )
    except ValueError as exc:
        raise ProblemError(
            status=400,
            title="Unknown family",
            detail=str(exc),
            code="STR.INVALID_REQUEST",
            type_="/errors/invalid-request",
        ) from exc
    overlay = page.overlay
    return DqChecksResponse(
        scope=Scope(
            contracts=[page.contract_id],
            start=start,
            end=end,
            basis=basis,
        ),
        contract_id=page.contract_id,
        score=page.score,
        scope_signature=page.scope_signature,
        dimensions_not_in_scope=page.dimensions_not_in_scope,
        frequencies=page.frequencies,
        checked=page.checked,
        families=[FamilyCard(**card) for card in page.families],
        issues=[AggregatedIssue(**issue) for issue in page.issues],
        overlay=Overlay(
            family=overlay["family"],
            ohlcv=[OverlayMark(**row) for row in overlay.get("ohlcv", [])],
            vwap=overlay.get("vwap") or {},
            picture=overlay.get("picture") or {},
        ),
        meta=page.meta,
    )


_SCORE_METHOD = "weighted mean of in-scope dimension scores; overall = Σ(w×s) / Σ(w)"


def _record_counts(con, contracts: list[str]) -> dict[str, Any]:
    clause, args = _contract_clause(contracts, "contract_id")
    total, by_freq = con.execute(
        f"SELECT count(*), list(DISTINCT frequency) FROM stage.market_record WHERE {clause}",
        args,
    ).fetchone()
    per = {
        f: int(n)
        for f, n in con.execute(
            f"SELECT frequency, count(*) FROM stage.market_record WHERE {clause} GROUP BY 1",
            args,
        ).fetchall()
    }
    rejected = con.execute("SELECT count(*) FROM stage.record_reject").fetchone()[0]
    return {
        "total": int(total or 0),
        "by_frequency": per,
        "frequencies": sorted(by_freq or []),
        "rejected_at_load": int(rejected or 0),
    }


def _contract_clause(contracts: list[str], column: str) -> tuple[str, list[object]]:
    if not contracts:
        return "TRUE", []
    placeholders = ", ".join("?" for _ in contracts)
    return f"{column} IN ({placeholders})", list(contracts)


def _top_issues(con, run_id: str, contracts: list[str]) -> list[dict[str, Any]]:
    clause, args = _contract_clause(contracts, "f.contract_id")
    rows = con.execute(
        f"""
        SELECT f.rule_id, count(*), sum(f.affected_rows), max(r.severity)
        FROM dq.dq_finding f JOIN dq.dq_rule r USING (rule_id)
        WHERE f.run_id = ? AND {clause}
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """,
        [run_id, *args],
    ).fetchall()
    return [
        {
            "rule_id": r[0],
            "findings": int(r[1]),
            "affected_rows": int(r[2] or 0),
            "severity": r[3],
        }
        for r in rows
    ]


@router.get("/metrics", response_model=DqMetricsResponse, summary="Metrics by grouping")
def metrics(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
    frequency: FrequencyParam = None,
    group_by: Annotated[
        str,
        Query(
            pattern="^(day|contract|rule|dimension|frequency)$",
            description="One endpoint per grouping scales with the rule catalogue; one "
            "endpoint per metric would not.",
        ),
    ] = "day",
    dimension: Annotated[
        str | None,
        Query(
            pattern="^(completeness|validity|consistency|uniqueness|timeliness|reconciliation)$",
            description="Restrict to one quality dimension. Without it `group_by=day` "
            "averages the dimensions together, which cannot express a single-dimension "
            "trend. `dimension=completeness` at `frequency=daily` is daily completeness "
            "over trade dates.",
        ),
    ] = None,
) -> DqMetricsResponse:
    """Persisted daily metrics, rolled up. `group_by=rule` reads findings instead."""
    contracts = _contracts(contract)
    if group_by == "rule":
        data = _metrics_by_rule(con, contracts, start, end, frequency, dimension)
    else:
        data = _metrics_from_mart(con, contracts, start, end, frequency, group_by, dimension)
    return DqMetricsResponse(
        scope=Scope(contracts=contracts, start=start, end=end, frequency=frequency),
        group_by=group_by,
        data=data,
        total=len(data),
        dimension=dimension,
    )


def _metric_filters(
    contracts, start, end, frequency, dimension=None, *, prefix: str = "", dimension_column=None
) -> tuple[str, list]:
    clauses, args = [], []
    clause, cargs = _contract_clause(contracts, f"{prefix}contract_id")
    clauses.append(clause)
    args.extend(cargs)
    if start is not None:
        clauses.append(f"{prefix}trade_date >= ?")
        args.append(start)
    if end is not None:
        clauses.append(f"{prefix}trade_date <= ?")
        args.append(end)
    if frequency is not None:
        clauses.append(f"{prefix}frequency = ?")
        args.append(frequency)
    if dimension is not None:
        clauses.append(f"{dimension_column or f'{prefix}dimension'} = ?")
        args.append(dimension)
    return " AND ".join(clauses), args


def _metrics_from_mart(
    con, contracts, start, end, frequency, group_by, dimension=None
) -> list[dict]:
    column = GROUP_BY_COLUMN[group_by]
    where, args = _metric_filters(contracts, start, end, frequency, dimension)
    rows = con.execute(
        f"""
        SELECT {column}, sum(expected_records), sum(actual_records),
               sum(affected_records), sum(finding_count), avg(dimension_score)
        FROM mart.dq_metric_daily WHERE {where}
        GROUP BY 1 ORDER BY 1
        """,
        args,
    ).fetchall()
    return [
        {
            group_by: r[0],
            "expected_records": int(r[1] or 0),
            "actual_records": int(r[2] or 0),
            "affected_records": int(r[3] or 0),
            "finding_count": int(r[4] or 0),
            "dimension_score": round(r[5], 2) if r[5] is not None else None,
        }
        for r in rows
    ]


def _metrics_by_rule(con, contracts, start, end, frequency, dimension=None) -> list[dict]:
    # `dq.dq_finding` has no dimension column; the rule carries it, so the filter lands on
    # the joined `dq.dq_rule` rather than on the finding's own prefix.
    where, args = _metric_filters(
        contracts, start, end, frequency, dimension, prefix="f.", dimension_column="r.dimension"
    )
    rows = con.execute(
        f"""
        SELECT f.rule_id, r.dimension, r.severity, count(*), sum(f.affected_rows)
        FROM dq.dq_finding f JOIN dq.dq_rule r USING (rule_id)
        WHERE {where}
        GROUP BY 1, 2, 3 ORDER BY 4 DESC
        """,
        args,
    ).fetchall()
    return [
        {
            "rule": r[0],
            "dimension": r[1],
            "severity": r[2],
            "finding_count": int(r[3]),
            "affected_rows": int(r[4] or 0),
        }
        for r in rows
    ]


@router.get("/findings", response_model=FindingsResponse, summary="Findings (read-only)")
def findings(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
    frequency: FrequencyParam = None,
    rule_id: Annotated[str | None, Query(description="Exact rule id.")] = None,
    severity: Annotated[
        str | None, Query(pattern="^(info|warning|error|critical)$")
    ] = None,
    status: Annotated[
        str | None, Query(pattern="^(open|accepted|overridden|resolved)$")
    ] = None,
    limit: LimitParam = 100,
    offset: OffsetParam = 0,
) -> FindingsResponse:
    """Paginated. A corrupt file can still produce tens of thousands of rows.

    **Read-only in v1**: there is no review or override route on this router.
    """
    where, args = _metric_filters(_contracts(contract), start, end, frequency, prefix="f.")
    for column, value in (("rule_id", rule_id), ("severity", severity), ("status", status)):
        if value is not None:
            where += f" AND f.{column} = ?"
            args.append(value)

    total = con.execute(
        f"SELECT count(*) FROM dq.dq_finding f WHERE {where}", args
    ).fetchone()[0]
    rows = con.execute(
        f"""
        SELECT f.finding_id, f.rule_id, f.contract_id, f.frequency, f.trade_date,
               f.ts_start_utc, f.ts_end_utc, f.severity, f.affected_rows, f.status,
               f.details, m.batch_id, b.filename, m.source_row, f.run_id
        FROM dq.dq_finding f
        LEFT JOIN stage.market_record m ON m.record_id = f.record_id
        LEFT JOIN stage.ingest_batch  b ON b.batch_id  = m.batch_id
        WHERE {where}
        ORDER BY f.detected_at DESC, f.finding_id
        LIMIT ? OFFSET ?
        """,
        [*args, limit, offset],
    ).fetchall()
    return FindingsResponse(
        data=_as_findings(con, rows), total=int(total), limit=limit, offset=offset
    )


def _as_findings(con, rows) -> list[Finding]:
    """One resolution pass over the page, not one per row (`specs/api-contract.md` §6.2).

    Corroboration is three lookups shared across every row, so resolving it per finding would
    turn a hundred-row page into three hundred queries for an answer that does not change.
    """
    resolved = corroborate(
        con,
        [
            FindingRef(
                finding_id=str(row[0]),
                rule_id=row[1],
                frequency=row[3],
                contract_id=row[2],
                trade_date=row[4],
                run_id=str(row[14]) if row[14] is not None else None,
            )
            for row in rows
        ],
    )
    return [_as_finding(row, resolved.get(str(row[0]))) for row in rows]


def _as_finding(row, corroboration=None) -> Finding:
    source = (
        {
            "batch_id": str(row[11]),
            "filename": row[12],
            "source_row": int(row[13]) if row[13] is not None else None,
        }
        if row[11] is not None
        else None
    )
    return Finding(
        finding_id=str(row[0]),
        rule_id=row[1],
        contract_id=row[2],
        frequency=row[3],
        trade_date=row[4],
        ts_start_utc=row[5],
        ts_end_utc=row[6],
        severity=row[7],
        affected_rows=int(row[8] or 0),
        status=row[9],
        details=_json(row[10]),
        source=source,
        # Absent rather than a placeholder state: null means corroboration does not apply to
        # this finding, which is a different answer from `not_comparable` (§6.2).
        corroboration=(
            Corroboration(**corroboration.as_json()) if corroboration is not None else None
        ),
    )


@router.get("/findings/{finding_id}", response_model=Finding, summary="One finding")
def get_finding(con: Con, finding_id: str) -> Finding:
    row = con.execute(
        """
        SELECT f.finding_id, f.rule_id, f.contract_id, f.frequency, f.trade_date,
               f.ts_start_utc, f.ts_end_utc, f.severity, f.affected_rows, f.status,
               f.details, m.batch_id, b.filename, m.source_row, f.run_id
        FROM dq.dq_finding f
        LEFT JOIN stage.market_record m ON m.record_id = f.record_id
        LEFT JOIN stage.ingest_batch  b ON b.batch_id  = m.batch_id
        WHERE f.finding_id = ?
        """,
        [finding_id],
    ).fetchone()
    if row is None:
        raise ProblemError(
            status=404,
            title="Finding not found",
            detail=f"No finding {finding_id}.",
            code="STR.UNKNOWN_FINDING",
            type_="/errors/finding-not-found",
        )
    # Both routes carry it (§6.2). A detail view that dropped the qualification would be the
    # one place a reader looks hardest at a finding and the one place it is unqualified.
    return _as_findings(con, [row])[0]


@router.get(
    "/changelog",
    response_model=ChangelogResponse,
    summary="Cleaning decisions (read-only)",
)
def get_changelog(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
    run_id: Annotated[
        str | None,
        Query(description="Defaults to the latest succeeded run; pass one to inspect a past "
              "run, which stays readable after a later run supersedes it."),
    ] = None,
    limit: LimitParam = 100,
    offset: OffsetParam = 0,
) -> ChangelogResponse:
    """What default cleaning decided, aggregated by rule x trade date x action.

    Read-only, like findings: cleaning is automatic policy driven by severity, not a user
    action, so there is nothing here to post to. The rows are the evidence that the clean
    basis is derived rather than edited in place.
    """
    contracts = _contracts(contract)
    resolved = run_id or _latest_run(con)
    if resolved is None:
        return ChangelogResponse(
            scope=Scope(contracts=contracts, start=start, end=end),
            run_id=None,
            data=[],
            total=0,
            limit=limit,
            offset=offset,
        )
    entries, total = changelog(
        con,
        resolved,
        contracts=contracts or None,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    return ChangelogResponse(
        scope=Scope(contracts=contracts, start=start, end=end),
        run_id=resolved,
        data=[ChangelogEntry(**e.as_json()) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/rules", response_model=RulesResponse, summary="The rule catalogue")
def rules(con: Con) -> RulesResponse:
    """Rules are rows, not code branches. This returns the rows as seeded."""
    rows = con.execute(
        "SELECT rule_id, dimension, severity, scope, enabled, params, description "
        "FROM dq.dq_rule ORDER BY rule_id"
    ).fetchall()
    return RulesResponse(
        data=[
            Rule(
                rule_id=r[0],
                dimension=r[1],
                severity=r[2],
                scope=r[3],
                enabled=bool(r[4]),
                params=_json(r[5]),
                description=r[6],
            )
            for r in rows
        ],
        total=len(rows),
    )


@router.post("/runs", response_model=RunSummary, summary="Re-validate a scope")
def create_run(
    con: Con,
    contract: ContractParam = None,
    frequency: FrequencyParam = None,
    batch_id: Annotated[str | None, Query(description="Narrow to one batch.")] = None,
) -> RunSummary:
    """Blocks until the run finishes and returns the **completed** run, not a job handle."""
    contract_ids = tuple(_contracts(contract)) or None
    try:
        result, scores = assess(
            con,
            batch_id=batch_id,
            contract_ids=contract_ids,
            frequencies=(frequency,) if frequency else None,
        )
    except RulesNotSeeded as exc:
        raise ProblemError(
            status=409,
            title="Rules not seeded",
            detail=str(exc),
            code="CAP.RULES_NOT_SEEDED",
            type_="/errors/rules-not-seeded",
        ) from exc
    # Rebuild bars so clean-basis OHLCV and finding annotations match this run.
    # `None` contracts = corpus-wide, matching an unscoped re-validate.
    build_bars(con, contract_ids=contract_ids)
    return _run_summary(con, result.run_id, scores=[_as_slice_score(s) for s in scores])


@router.get("/runs/{run_id}", response_model=RunSummary, summary="A past run")
def get_run(con: Con, run_id: str) -> RunSummary:
    """Retrieves a past run — never a pending job handle."""
    return _run_summary(con, run_id)


def _run_summary(con, run_id: str, *, scores: list[SliceScore] | None = None) -> RunSummary:
    row = con.execute(
        "SELECT run_id, status, batch_id, ruleset_hash, findings_count, scope_filter, "
        "started_at, finished_at FROM dq.dq_run WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if row is None:
        raise ProblemError(
            status=404,
            title="Run not found",
            detail=f"No validation run {run_id}.",
            code="STR.UNKNOWN_RUN",
            type_="/errors/run-not-found",
        )
    return RunSummary(
        run_id=str(row[0]),
        status=row[1],
        batch_id=str(row[2]) if row[2] else None,
        ruleset_hash=row[3],
        findings_count=int(row[4] or 0),
        scope_filter=_json(row[5]),
        started_at=row[6],
        finished_at=row[7],
        scores=scores or [],
    )
