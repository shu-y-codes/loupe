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
from loupe.ui.runtime import get_client
from loupe.ui.specifics import render_specifics
from loupe.ui.summary import render_summary


def contract_roots(client: LoupeClient) -> dict[str, str]:
    """`contract_id` → root, for the inventory's Root column. A lookup, not a rollup."""
    try:
        body = client.contracts()
    except (ApiProblem, ApiUnavailable):
        return {}
    return {
        row["contract_id"]: row.get("root") or ""
        for row in body.get("data", [])
        if row.get("contract_id")
    }


def settlement_trend(client: LoupeClient, start, end) -> list[dict[str, Any]]:
    """Daily completeness per trade date — settlement reliability, defined in the UI spec.

    `group_by=day` alone averages the dimensions together, which is a general DQ trend and not
    this tile; the `dimension` filter is what makes the sparkline mean what its label says.
    """
    try:
        body = client.metrics(
            group_by="day", dimension="completeness", frequency="daily", start=start, end=end
        )
    except (ApiProblem, ApiUnavailable):
        return []
    return body.get("data", [])


def store_is_ready(client: LoupeClient) -> bool:
    """Ask `/health` before anything else, so an unprepared store gets a sentence.

    A store with no schema answers every analytic call with a 500 — `dq.dq_run` does not
    exist to be queried. Rendering that as a stack trace would blame the reader for a setup
    step nobody told them about, so the page checks first and says what to run.
    """
    try:
        health = client.health()
    except ApiUnavailable as exc:
        st.error(str(exc))
        return False
    except ApiProblem as problem:
        st.error(f"{problem.title}: {problem}")
        return False

    if not health.get("schema_applied"):
        st.warning(
            "**The store has no schema yet.** Apply it once before using the app:\n\n"
            "```python\n"
            "from loupe.data import apply_schema, connect, seed_reference\n"
            "from loupe.quality import seed_quality\n"
            "con = connect(); apply_schema(con); seed_reference(con); seed_quality(con)\n"
            "```"
        )
        return False
    if not health.get("rules_seeded"):
        st.warning(
            "**The rule catalogue is not seeded.** Run `seed_quality(con)` — quality rules "
            "are rows, so nothing can be validated until they exist."
        )
        return False
    return True


def load_summary(client: LoupeClient, start, end) -> dict[str, Any] | None:
    try:
        return client.summary(start=start, end=end)
    except ApiUnavailable as exc:
        st.error(str(exc))
        return None
    except ApiProblem as problem:
        st.error(f"{problem.title}: {problem}")
        return None


def main() -> None:
    st.set_page_config(page_title="Loupe", page_icon="🔍", layout="wide")
    client = get_client()

    state = render_sidebar(client)
    render_header(state.persona)

    if not store_is_ready(client):
        return

    summary = load_summary(client, state.start, state.end)
    if summary is None:
        return

    selected = render_summary(
        state.persona,
        summary,
        settlement_trend(client, state.start, state.end),
        contract_roots(client),
    )

    # Selection drives Specifics; it survives a rerun so switching persona keeps the contract.
    if selected:
        st.session_state["contract"] = selected
    contract = st.session_state.get("contract")

    st.markdown("---")
    render_specifics(state.persona, client, contract, state.start, state.end, summary)


main()
