"""The Loupe page. Run it with `streamlit run src/loupe/ui/app.py`.

Composed of functions that take data and emit elements, deliberately: `AppTest` can only
assert over a page shaped that way, and a script that interleaved `st.*` calls with fetching
would be untestable without a live API (`plans/05-ui.md` done-when 4).

The whole script is one `main()` so the module can be imported without drawing anything.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# Absolute, not relative: `streamlit run` executes this file as `__main__` rather than as a
# module of the package, so a relative import fails at launch as well as under test.
from loupe.ui.chrome import render_header, render_sidebar
from loupe.ui.client import ApiProblem, ApiUnavailable, LoupeClient
from loupe.ui.demo import render_demo, render_synthetic_notice
from loupe.ui.review import render_review
from loupe.ui.runtime import get_client


def contract_ids(client: LoupeClient) -> list[str]:
    """Loaded contracts for the sidebar picker. A lookup, not a rollup."""
    try:
        body = client.contracts()
    except (ApiProblem, ApiUnavailable):
        return []
    return [
        row["contract_id"]
        for row in body.get("data", [])
        if row.get("contract_id")
    ]


def contract_catalogue(client: LoupeClient) -> list[dict[str, Any]]:
    """Loaded contracts with their held grains for the Quality grain control."""
    try:
        return list(client.contracts().get("data", []))
    except (ApiProblem, ApiUnavailable):
        return []


def read_health(client: LoupeClient) -> dict[str, Any] | None:
    """Ask `/health` before anything else, and hand the answer back rather than a verdict.

    Two things depend on the body, not on a yes/no. The demo panel decides which controls to
    offer from `records`, and the synthetic-data disclosure fires on `synthetic_batches` — and
    that disclosure has to be driven by something the page cannot skip, which is why it reads
    the call that already gates everything else.
    """
    try:
        return client.health()
    except ApiUnavailable as exc:
        st.error(str(exc))
        return None
    except ApiProblem as problem:
        st.error(f"{problem.title}: {problem}")
        return None


def store_is_ready(health: dict[str, Any]) -> bool:
    """Whether the store can answer at all, with a sentence when it cannot.

    A store with no schema answers every analytic call with a refusal — `dq.dq_run` does not
    exist to be queried. Blaming the reader for a setup step nobody told them about would be
    the wrong response, so the page checks first and says what to run. Both branches should be
    unreachable now that `bootstrapped_app` seeds on first start; they stay because a store
    can also be pointed at by `LOUPE_DB` after being created some other way.
    """
    if not health.get("schema_applied"):
        st.warning(
            "**The store has no schema yet.** Start the API with the bootstrapping factory, "
            "which applies the schema and seeds the rule catalogue on first run:\n\n"
            "```bash\n"
            "uv run uvicorn loupe.api.app:bootstrapped_app --factory\n"
            "```"
        )
        return False
    if not health.get("rules_seeded"):
        st.warning(
            "**The rule catalogue is not seeded.** Restart the API with "
            "`loupe.api.app:bootstrapped_app`, or run `seed_quality(con)` — quality rules are "
            "rows, so nothing can be validated until they exist."
        )
        return False
    return True


def load_checks(
    client: LoupeClient, contract: str, start, end, family: str, frequency: str
) -> dict[str, Any] | None:
    try:
        return client.checks(
            contract=contract,
            start=start,
            end=end,
            family=family,
            frequency=frequency,
        )
    except ApiUnavailable as exc:
        st.error(str(exc))
        return None
    except ApiProblem as problem:
        st.error(f"{problem.title}: {problem}")
        return None


def load_bars(
    client: LoupeClient, contract: str, start, end, frequency: str
) -> dict[str, Any]:
    try:
        return client.bars_daily(
            contract=contract,
            start=start,
            end=end,
            basis="clean",
            frequency=frequency,
        )
    except ApiProblem as problem:
        st.warning(str(problem))
        return {"data": []}
    except ApiUnavailable as exc:
        st.warning(str(exc))
        return {"data": []}


def load_vwap(
    client: LoupeClient, contract: str, start, end
) -> dict[str, Any] | ApiProblem | None:
    try:
        return client.vwap(contract=contract, start=start, end=end)
    except ApiProblem as problem:
        return problem
    except ApiUnavailable as exc:
        return ApiProblem(
            status=503,
            code=None,
            title="Unavailable",
            detail=str(exc),
        )


def main() -> None:
    st.set_page_config(page_title="Loupe", page_icon="🔍", layout="wide")
    client = get_client()

    health = read_health(client)
    if health is None:
        return

    contract_rows = contract_catalogue(client)
    contracts = [row["contract_id"] for row in contract_rows if row.get("contract_id")]
    frequencies = {
        row["contract_id"]: list(row.get("frequencies_available") or [])
        for row in contract_rows
        if row.get("contract_id")
    }
    state = render_sidebar(contracts, frequencies)
    # Demo ingest is the only UI path into the store; the ingested-file list sits with it.
    render_demo(client, health)
    render_header(state)

    if not store_is_ready(health):
        return

    # Before anything that reports a number. A reader must never meet a score without knowing
    # whether the data behind it was planted (`plans/07-demo-corpus.md` done-when 5).
    render_synthetic_notice(health)

    if not state.contract:
        st.info(
            "No contracts loaded yet. Load demo data from the sidebar to see quality for it."
        )
        return
    if not state.frequency:
        st.warning("The selected contract does not report a held quality grain.")
        return

    st.session_state.setdefault("family", "gaps")
    family = st.session_state.get("family") or "gaps"
    checks = load_checks(
        client, state.contract, state.start, state.end, family, state.frequency
    )
    if checks is None:
        return

    bars = load_bars(
        client, state.contract, state.start, state.end, state.frequency
    )
    vwap = load_vwap(client, state.contract, state.start, state.end)
    render_review(
        checks,
        bars,
        vwap,
        scope_identity={
            "contract": state.contract,
            "frequency": state.frequency,
            "start": state.start,
            "end": state.end,
        },
    )


main()
