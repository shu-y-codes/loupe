"""Insights routes (`specs/api-contract.md` §7).

Two v1 routes, deferred from slice 4 because nothing backed them: pattern lift and suggestion
rationale are `quality`'s arithmetic, and `plans/04-api.md` forbids putting either in a
handler. They land here now that `loupe.quality.patterns` and `loupe.quality.suggestions`
exist, and these handlers do what every other handler in this app does — resolve the scope,
call the layer, shape the envelope.

**Neither route can mutate anything, and the absence is the design.**
`POST /v1/insights/suggestions/{id}/apply` and `.../dismiss` are extensions (§7.1), and they
are absent rather than present-and-refusing: an endpoint that exists and returns 405 invites a
client to keep the button. The suggestion payload carries no action list for the same reason.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from loupe.quality.patterns import DEFAULT_LIFT, DEFAULT_MIN_PERIODS, DEFAULT_MIN_SUPPORT
from loupe.quality.patterns import find_patterns as _find_patterns
from loupe.quality.suggestions import suggest as _suggest

from ..deps import Con, EndDateParam, StartDateParam
from ..models import Pattern, PatternsResponse, Scope, Suggestion, SuggestionsResponse

router = APIRouter(prefix="/insights", tags=["insights"])

ContractParam = Annotated[
    str | None, Query(description="Contract id, or a comma-separated list.")
]

MinLiftParam = Annotated[
    float,
    Query(
        ge=1.0,
        description="Report a bucket only when its share of a rule's findings is at least this "
        "multiple of its share of the records. A ratio, never a count: a bucket holding half "
        "the findings is unremarkable if it also holds half the records.",
    ),
]

MinSupportParam = Annotated[
    int,
    Query(
        ge=1,
        description="Minimum findings in the bucket. Guards against a rule that fired four "
        "times reading as 100% concentrated wherever those four landed.",
    ),
]


def _contracts(contract: str | None) -> list[str]:
    return [c.strip() for c in contract.split(",") if c.strip()] if contract else []


@router.get(
    "/patterns",
    response_model=PatternsResponse,
    summary="Recurring patterns (lift)",
)
def patterns(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
    min_lift: MinLiftParam = DEFAULT_LIFT,
    min_support: MinSupportParam = DEFAULT_MIN_SUPPORT,
) -> PatternsResponse:
    """Where findings concentrate, corrected for exposure.

    No lift arithmetic here: `quality.patterns` owns the ratio and the templated narrative, and
    a second copy in a handler would be free to disagree with the one the suggestions are
    generated from.
    """
    contracts = _contracts(contract)
    found = _find_patterns(
        con,
        contracts=contracts or None,
        start=start,
        end=end,
        lift=min_lift,
        min_support=min_support,
    )
    return PatternsResponse(
        scope=Scope(contracts=contracts, start=start, end=end),
        data=[Pattern(**p.as_json()) for p in found],
        total=len(found),
        # Echoed so an empty list is readable: a caller can tell "nothing concentrates" from
        # "the thresholds excluded everything", which are different answers.
        meta={
            "min_lift": min_lift,
            "min_support": min_support,
            "min_periods": DEFAULT_MIN_PERIODS,
        },
    )


@router.get(
    "/suggestions",
    response_model=SuggestionsResponse,
    summary="Suggested changes (report-only)",
)
def suggestions(
    con: Con,
    contract: ContractParam = None,
    start: StartDateParam = None,
    end: EndDateParam = None,
) -> SuggestionsResponse:
    """Proposed changes with rationale and dry-run effect. Text, and nothing to press.

    No `min_lift` or `min_support` here, deliberately: a suggestion is only as good as the
    pattern behind it, and letting a caller widen the thresholds on this route would produce
    proposals from concentrations the patterns route would not have reported.
    """
    contracts = _contracts(contract)
    found = _suggest(con, contracts=contracts or None, start=start, end=end)
    return SuggestionsResponse(
        scope=Scope(contracts=contracts, start=start, end=end),
        data=[Suggestion(**s.as_json()) for s in found],
        total=len(found),
    )
