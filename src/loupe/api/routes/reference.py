"""Health, contracts and calendar — the reference surface (`specs/api-contract.md` §3).

`GET /contracts` powers every contract filter in the UI. It reports the data range actually
held so date pickers bound to real data, and the frequencies actually held so the UI can
disable VWAP for a daily-only contract instead of routing the user into an error.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..deps import Con, EndDateParam, StartDateParam
from ..errors import ProblemError
from ..models import (
    CalendarDay,
    CalendarResponse,
    Contract,
    ContractsResponse,
    Coverage,
    Health,
)

router = APIRouter(tags=["reference"])


@router.get("/health", response_model=Health, summary="Liveness and store state")
def health(con: Con) -> Health:
    """Whether the store is open, the schema applied, and the rule catalogue seeded."""
    applied = bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'stage' AND table_name = 'market_record'"
        ).fetchone()[0]
    )
    if not applied:
        return Health(
            status="degraded",
            schema_applied=False,
            rules_seeded=False,
            records=0,
            contracts=0,
            batches=0,
            synthetic_batches=0,
            synthetic_records=0,
        )
    records = con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0]
    contracts = con.execute("SELECT count(*) FROM ref.contract").fetchone()[0]
    batches = con.execute(
        "SELECT count(*) FROM stage.ingest_batch WHERE status <> 'purged'"
    ).fetchone()[0]
    seeded = bool(con.execute("SELECT count(*) FROM dq.dq_rule").fetchone()[0])
    # Planted defects, counted every time the page asks whether the store is usable. The UI
    # already calls `/health` before it draws anything, so putting the disclosure here is what
    # makes it impossible to render a score without knowing whether the data behind it is real.
    synthetic_batches, synthetic_records = con.execute(
        """
        SELECT count(*),
               coalesce(sum(rows_accepted), 0)
        FROM stage.ingest_batch
        WHERE origin = 'injected' AND status <> 'purged'
        """
    ).fetchone()
    return Health(
        status="ok",
        schema_applied=True,
        rules_seeded=seeded,
        records=int(records),
        contracts=int(contracts),
        batches=int(batches),
        synthetic_batches=int(synthetic_batches),
        synthetic_records=int(synthetic_records),
    )


_COVERAGE_SQL = """
    SELECT contract_id, frequency,
           min(trade_date), max(trade_date),
           count(DISTINCT trade_date), count(*)
    FROM stage.market_record
    GROUP BY 1, 2
"""


def _coverage(con) -> dict[str, dict[str, Coverage]]:
    """Observed bounds per contract per grain. Absence of a row means the grain is not held."""
    out: dict[str, dict[str, Coverage]] = {}
    for contract_id, frequency, first, last, sessions, records in con.execute(
        _COVERAGE_SQL
    ).fetchall():
        out.setdefault(contract_id, {})[frequency] = Coverage(
            first_trade_date=first,
            last_trade_date=last,
            sessions=int(sessions),
            records=int(records),
        )
    return out


@router.get("/contracts", response_model=ContractsResponse, summary="Contracts held")
def list_contracts(
    con: Con,
    root: str | None = Query(None, description="Filter to one product root, e.g. `ES`."),
    active_on: EndDateParam = None,
    frequency: str | None = Query(
        None,
        pattern="^(minute|daily)$",
        description="Return only contracts holding records at this grain.",
    ),
) -> ContractsResponse:
    clauses = ["TRUE"]
    args: list[object] = []
    if root is not None:
        clauses.append("c.root = ?")
        args.append(root)
    rows = con.execute(
        f"""
        SELECT c.contract_id, c.root, c.exchange, c.contract_month, c.tick_size,
               c.multiplier, c.roll_date, c.dates_inferred
        FROM ref.contract c
        WHERE {" AND ".join(clauses)}
        ORDER BY c.contract_id
        """,
        args,
    ).fetchall()

    coverage = _coverage(con)
    data: list[Contract] = []
    for row in rows:
        held = coverage.get(row[0], {})
        if frequency is not None and frequency not in held:
            continue
        if active_on is not None and not _active_on(held, active_on):
            continue
        data.append(
            Contract(
                contract_id=row[0],
                root=row[1],
                exchange=row[2],
                contract_month=row[3].strftime("%Y-%m") if row[3] else None,
                tick_size=row[4],
                multiplier=row[5],
                coverage=held,
                frequencies_available=sorted(held),
                roll_date=row[6],
                dates_inferred=bool(row[7]) if row[7] is not None else True,
            )
        )
    return ContractsResponse(data=data, total=len(data))


def _active_on(held: dict[str, Coverage], day) -> bool:
    """True when any grain observed data spanning `day`."""
    return any(
        c.first_trade_date is not None
        and c.last_trade_date is not None
        and c.first_trade_date <= day <= c.last_trade_date
        for c in held.values()
    )


@router.get(
    "/contracts/{contract_id}", response_model=Contract, summary="One contract"
)
def get_contract(con: Con, contract_id: str) -> Contract:
    row = con.execute(
        """
        SELECT contract_id, root, exchange, contract_month, tick_size, multiplier,
               roll_date, dates_inferred
        FROM ref.contract WHERE contract_id = ?
        """,
        [contract_id],
    ).fetchone()
    if row is None:
        raise ProblemError(
            status=404,
            title="Contract not found",
            detail=f"No contract {contract_id} is held.",
            code="STR.UNKNOWN_CONTRACT",
            type_="/errors/contract-not-found",
        )
    held = _coverage(con).get(contract_id, {})
    return Contract(
        contract_id=row[0],
        root=row[1],
        exchange=row[2],
        contract_month=row[3].strftime("%Y-%m") if row[3] else None,
        tick_size=row[4],
        multiplier=row[5],
        coverage=held,
        frequencies_available=sorted(held),
        roll_date=row[6],
        dates_inferred=bool(row[7]) if row[7] is not None else True,
    )


@router.get("/calendar", response_model=CalendarResponse, summary="Session calendar")
def calendar(
    con: Con,
    root: str | None = Query(None, description="Filter to one product root."),
    start: StartDateParam = None,
    end: EndDateParam = None,
) -> CalendarResponse:
    clauses = ["TRUE"]
    args: list[object] = []
    if root is not None:
        clauses.append("root = ?")
        args.append(root)
    if start is not None:
        clauses.append("trade_date >= ?")
        args.append(start)
    if end is not None:
        clauses.append("trade_date <= ?")
        args.append(end)
    rows = con.execute(
        f"""
        SELECT exchange, root, trade_date, session_open_utc, session_close_utc,
               is_holiday, is_early_close, expected_slots_1m
        FROM ref.session_calendar
        WHERE {" AND ".join(clauses)}
        ORDER BY root, trade_date
        """,
        args,
    ).fetchall()
    data = [
        CalendarDay(
            exchange=r[0],
            root=r[1],
            trade_date=r[2],
            session_open_utc=r[3],
            session_close_utc=r[4],
            is_holiday=bool(r[5]),
            is_early_close=bool(r[6]),
            expected_slots_1m=int(r[7]) if r[7] is not None else None,
        )
        for r in rows
    ]
    return CalendarResponse(data=data, total=len(data))
