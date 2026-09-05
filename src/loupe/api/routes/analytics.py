"""Daily bars, rolling VWAP and compare (`specs/api-contract.md` §5).

Every number here is read from `insights`; nothing is re-derived. The handlers' whole job is
to resolve scope, echo what they resolved, and turn the publish gate's four states into the
four responses the contract names — a series, a series with sessions withheld, an empty
result, and a `CAP.FREQUENCY_UNAVAILABLE` refusal.

**Why the refusal is not decided here.** `insights.published_vwap` returns it. A handler that
asked the store which frequencies a contract holds would be taking a capability decision away
from the layer that owns publication (`plans/04-api.md` done-when 7), and the UI would have
two sources of truth for the same question.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from loupe.insights import (
    DailyBar,
    PublishedSeries,
    compare_bars,
    compare_vwap,
    frequencies_held,
    published_bars,
    published_vwap,
    read_bars,
)

from ..deps import BasisParam, Con, EndDateParam, FrequencyParam, StartDateParam
from ..errors import ProblemError
from ..models import (
    Bar,
    BarsResponse,
    BlockedSession,
    CompareResponse,
    Reconciliation,
    Scope,
    VwapPoint,
    VwapResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

ContractParam = Annotated[
    str | None,
    Query(
        description="Contract id, or a comma-separated list. Omit for every contract held.",
    ),
]

#: `mart.bar_daily.source` follows from the grain the caller reads *from*: bars derived from
#: the minute tape against bars supplied at daily grain. §2.1 is why these are not the same
#: numbers and must not be conflated.
SOURCE_FOR_FREQUENCY = {"minute": "derived", "daily": "vendor"}


def _contracts(contract: str | None) -> list[str]:
    return [c.strip() for c in contract.split(",") if c.strip()] if contract else []


def _resolve_frequency(
    con, contracts: list[str], requested: str | None
) -> tuple[str, bool]:
    """The finest grain held for the contracts in scope, unless the caller named one.

    A fixed `daily` default would silently downgrade a minute upload; requiring the parameter
    on every call would block the simplest request (§2.1).
    """
    if requested is not None:
        return requested, False
    held: set[str] = set()
    for contract_id in contracts or [None]:
        held.update(frequencies_held(con, contract_id=contract_id))
    return ("minute" if "minute" in held else "daily"), True


def _blocked(series: PublishedSeries) -> list[BlockedSession]:
    return [
        BlockedSession(
            contract_id=q.contract_id,
            trade_date=q.trade_date,
            frequency=q.frequency,
            blocking_rule_ids=list(q.blocking_rule_ids),
            max_severity=q.max_severity,
        )
        for q in series.blocked_sessions
    ]


def _in_range(value: date, start: date | None, end: date | None) -> bool:
    return (start is None or value >= start) and (end is None or value <= end)


def _refuse_frequency(series: PublishedSeries, what: str) -> None:
    """Render the gate's refusal as the contract's 422.

    **422, not 404 or 400**: the request is syntactically valid and the contract exists; the
    server understands it and cannot process it given the data currently held.
    """
    gap = series.unsupported
    if gap is None:
        return
    available = ", ".join(gap.frequencies_available) or "no"
    raise ProblemError(
        status=422,
        title="Minute records required",
        detail=(
            f"{gap.contract_id or 'The store'} holds {available} records only. {what} "
            "requires intraday records; there is no intraday window to volume-weight. "
            "Upload the minute file for this contract to enable it."
        ),
        code="CAP.FREQUENCY_UNAVAILABLE",
        type_="/errors/frequency-unavailable",
        meta={
            "contract_id": gap.contract_id,
            "requested_frequency": gap.requested_frequency,
            "frequencies_available": list(gap.frequencies_available),
            "substitute_offered": gap.substitute_offered,
        },
    )


def _reconciliation(bar: DailyBar, supplied: DailyBar | None) -> Reconciliation:
    """Attach the supplied bar beside the derived one, or say it is not comparable.

    A lookup and two differences between numbers `insights` already published — the
    reconciliation *rules* (`REC.*`, coverage gating, close-convention findings) are slice 6
    and are not anticipated here.
    """
    if supplied is None:
        return Reconciliation(status="not_comparable")
    close_diff = (
        None if bar.close is None or supplied.close is None else bar.close - supplied.close
    )
    ratio = (
        None
        if not supplied.volume or bar.volume is None
        else round(bar.volume / supplied.volume, 4)
    )
    return Reconciliation(
        status="compared",
        supplied_close=supplied.close,
        close_diff=None if close_diff is None else round(close_diff, 6),
        supplied_volume=supplied.volume,
        volume_ratio=ratio,
    )


@router.get("/bars/daily", response_model=BarsResponse, summary="Daily OHLCV bars")
def bars_daily(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
    basis: BasisParam = "clean",
    frequency: FrequencyParam = None,
) -> BarsResponse:
    """Each bar with its quality annotation. `contract` accepts a comma-separated list.

    `frequency=minute` aggregates the minute tape; `frequency=daily` returns the supplied
    bars unchanged. Both return daily bars and are **not** the same numbers.
    """
    contracts = _contracts(contract)
    grain, defaulted = _resolve_frequency(con, contracts, frequency)
    source = SOURCE_FOR_FREQUENCY[grain]

    rows: list[Bar] = []
    blocked: list[BlockedSession] = []
    for contract_id in contracts or [None]:
        series = published_bars(con, contract_id=contract_id, basis=basis, source=source)
        blocked.extend(
            b for b in _blocked(series) if _in_range(b.trade_date, start, end)
        )
        supplied = {
            (b.contract_id, b.trade_date): b
            for b in read_bars(con, contract_id=contract_id, basis=basis, source="vendor")
        } if source == "derived" else {}
        for bar in series.rows:
            if not _in_range(bar.trade_date, start, end):
                continue
            rows.append(
                Bar(
                    contract_id=bar.contract_id,
                    trade_date=bar.trade_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    record_count=bar.record_count,
                    expected_count=bar.expected_count,
                    completeness_pct=bar.completeness_pct,
                    finding_count=bar.finding_count,
                    max_severity=bar.max_severity,
                    reconciliation=(
                        _reconciliation(bar, supplied.get((bar.contract_id, bar.trade_date)))
                        if source == "derived"
                        else None
                    ),
                )
            )
    rows.sort(key=lambda b: (b.contract_id, b.trade_date))
    return BarsResponse(
        scope=Scope(
            contracts=contracts or sorted({b.contract_id for b in rows}),
            start=start,
            end=end,
            basis=basis,
            frequency=grain,
            frequency_defaulted=defaulted,
        ),
        data=rows,
        total=len(rows),
        blocked_sessions=blocked,
        meta={
            "bar_source": (
                "derived_from_minute" if source == "derived" else "supplied_daily"
            ),
        },
    )


@router.get("/vwap", response_model=VwapResponse, summary="Rolling 15-minute VWAP")
def vwap(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
    basis: BasisParam = "clean",
    price_basis: Annotated[
        str,
        Query(pattern="^(typical|close)$", description="Price the window weights."),
    ] = "typical",
) -> VwapResponse:
    """A trailing 15-minute window, partitioned by `(contract, trade_date)`.

    Refuses with **422 `CAP.FREQUENCY_UNAVAILABLE`** when the contract holds daily records
    only — not an empty `data` array, not a zero-filled series, and never a 15-*day* VWAP
    over daily bars standing in for it.
    """
    contracts = _contracts(contract)
    points: list[VwapPoint] = []
    blocked: list[BlockedSession] = []
    for contract_id in contracts or [None]:
        series = published_vwap(
            con, contract_id=contract_id, basis=basis, price_basis=price_basis
        )
        _refuse_frequency(series, "A rolling 15-minute VWAP")
        blocked.extend(b for b in _blocked(series) if _in_range(b.trade_date, start, end))
        for p in series.rows:
            if not _in_range(p.trade_date, start, end):
                continue
            points.append(
                VwapPoint(
                    contract_id=p.contract_id,
                    trade_date=p.trade_date,
                    ts_utc=p.ts_utc,
                    vwap=p.vwap_15m,
                    window_volume=p.window_volume,
                    window_records=p.window_records,
                    is_warmup=p.is_warmup,
                )
            )
    return VwapResponse(
        scope=Scope(
            contracts=contracts or sorted({p.contract_id for p in points}),
            start=start,
            end=end,
            basis=basis,
            frequency="minute",
            frequency_defaulted=False,
        ),
        price_basis=price_basis,
        data=points,
        total=len(points),
        blocked_sessions=blocked,
    )


@router.get("/compare", response_model=CompareResponse, summary="Compare two views")
def compare(
    con: Con,
    metric: Annotated[
        str,
        Query(pattern="^(vwap|close|ohlcv)$", description="What to line up."),
    ] = "close",
    compare: Annotated[
        str,
        Query(
            pattern="^(basis|frequency)$",
            description="`basis`: raw against clean (cleaning impact). `frequency`: supplied "
            "daily against bars derived from the minute tape.",
        ),
    ] = "basis",
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
) -> CompareResponse:
    """`compare=frequency` needs both grains and refuses with the same `CAP.*` when only
    one is held."""
    contracts = _contracts(contract)
    rows: list[dict[str, Any]] = []

    for contract_id in contracts or [None]:
        if compare == "frequency":
            _require_both(con, contract_id)
            rows.extend(_frequency_rows(con, contract_id, start, end))
        elif metric == "vwap":
            rows.extend(_basis_vwap_rows(con, contract_id, start, end))
        else:
            rows.extend(_basis_bar_rows(con, contract_id, start, end))

    return CompareResponse(
        scope=Scope(
            contracts=contracts or sorted({r["contract_id"] for r in rows}),
            start=start,
            end=end,
            frequency_defaulted=False,
        ),
        metric=metric,
        compare=compare,
        data=rows,
        total=len(rows),
        differing=sum(1 for r in rows if r.get("differs")),
    )


def _require_both(con, contract_id: str | None) -> None:
    held = frequencies_held(con, contract_id=contract_id)
    if held and not {"minute", "daily"} <= set(held):
        raise ProblemError(
            status=422,
            title="Both frequencies required",
            detail=(
                f"{contract_id or 'The store'} holds {', '.join(held)} records only. "
                "Comparing supplied against derived bars requires both grains."
            ),
            code="CAP.FREQUENCY_UNAVAILABLE",
            type_="/errors/frequency-unavailable",
            meta={
                "contract_id": contract_id,
                "requested_frequency": "minute,daily",
                "frequencies_available": list(held),
                "substitute_offered": False,
            },
        )


def _basis_bar_rows(con, contract_id, start, end) -> list[dict[str, Any]]:
    return [
        {
            "contract_id": d.contract_id,
            "trade_date": d.trade_date,
            "raw": _bar_fields(d.raw),
            "clean": _bar_fields(d.clean),
            "differs": d.differs,
        }
        for d in compare_bars(con, contract_id=contract_id)
        if _in_range(d.trade_date, start, end)
    ]


def _basis_vwap_rows(con, contract_id, start, end) -> list[dict[str, Any]]:
    return [
        {
            "contract_id": d.contract_id,
            "trade_date": d.trade_date,
            "ts_utc": d.ts_utc,
            "raw_vwap": d.raw_vwap,
            "clean_vwap": d.clean_vwap,
            "delta": d.delta,
            "differs": d.differs,
        }
        for d in compare_vwap(con, contract_id=contract_id)
        if _in_range(d.trade_date, start, end)
    ]


def _frequency_rows(con, contract_id, start, end) -> list[dict[str, Any]]:
    """Supplied daily bars beside bars derived from the minute tape, field by field."""
    derived = {
        (b.contract_id, b.trade_date): b
        for b in read_bars(con, contract_id=contract_id, source="derived")
    }
    supplied = {
        (b.contract_id, b.trade_date): b
        for b in read_bars(con, contract_id=contract_id, source="vendor")
    }
    rows = []
    for key in sorted(set(derived) | set(supplied)):
        if not _in_range(key[1], start, end):
            continue
        d, s = derived.get(key), supplied.get(key)
        rows.append(
            {
                "contract_id": key[0],
                "trade_date": key[1],
                "derived": _bar_fields(d),
                "supplied": _bar_fields(s),
                "status": "compared" if d and s else "not_comparable",
                "differs": (d is None) != (s is None)
                or (d is not None and s is not None and _bar_fields(d) != _bar_fields(s)),
            }
        )
    return rows


def _bar_fields(bar: DailyBar | None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }
