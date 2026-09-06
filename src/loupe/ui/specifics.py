"""The Specifics module: why your attention is needed, how you address it.

A table first, always — Why / Impact / Address — and charts under it only where that persona
will actually look at them (`specs/loupe-ui-design.md`). Risk gets no tick drill-down, Trader
gets no rule authoring, Analyst gets the deep view.

**Address is text, and there are no apply or override controls anywhere in this module.**
Findings and suggestions are report-only this release (`specs/loupe-solution-design.md` §12),
so the absence of those buttons is a decision this file has to keep, not an omission.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from . import charts
from . import help as helptext
from .client import ApiProblem, LoupeClient
from .runtime import EM_DASH, percentage, score_text

#: Suggestions land with the reports they serve (`plans/06-rec-suggestions-demo.md`). Until
#: then the Address cell says so. Writing the sentences here instead would put copy that
#: belongs to `quality` into a widget, which is the one thing this slice must not do.
_ADDRESS_PENDING = (
    "Suggested action ships with the suggestions report. The finding above is the evidence; "
    "this release reports and does not apply."
)

#: How the three corroboration states of `specs/dq-rules-and-scoring.md` §8.7 are introduced in
#: the **Why** cell (`specs/loupe-ui-design.md`). Labels only — the sentence after the dash is
#: the API's `reason`, rendered exactly as given, because the finding's qualification is decided
#: in `quality` and a widget that reworded it could soften what it says.
#:
#: A finding with no `corroboration` object gets no second line at all. That is the fourth
#: answer: corroboration does not apply here, which is not the same as "we could not check".
_CORROBORATION_LABEL = {
    "confirmed": "range confirmed against the tape",
    "disputed": "range disputed",
    "not_comparable": "not corroborated",
}


# --------------------------------------------------------------------- shared


def _findings_frame(findings: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Rule": f["rule_id"],
                "When": f.get("trade_date") or EM_DASH,
                "What": _what(f),
                "Severity": f["severity"],
            }
            for f in findings
        ]
    )


def _what(finding: dict[str, Any]) -> str:
    """The finding's own evidence, in one line. Never a tooltip — this cell *is* the
    explanation (`specs/loupe-ui-design.md`, Skip)."""
    details = finding.get("details")
    if isinstance(details, dict):
        for key in ("message", "reason", "what", "summary"):
            if details.get(key):
                return str(details[key])
        pairs = ", ".join(f"{k} {v}" for k, v in list(details.items())[:3])
        if pairs:
            return pairs
    rows = finding.get("affected_rows")
    return f"{rows} row(s) affected" if rows else finding["rule_id"]


def _address(client: LoupeClient, contract: str) -> str:
    """Suggestion text from `quality`, or an honest account of why there is none yet."""
    try:
        body = client.suggestions(contract=contract)
    except ApiProblem:
        return _ADDRESS_PENDING
    except Exception:  # noqa: BLE001 - a missing report must not take the page down
        return _ADDRESS_PENDING
    items = body.get("data") or []
    if not items:
        return "No suggestion for this contract in the current run."
    return str(items[0].get("rationale") or items[0].get("text") or _ADDRESS_PENDING)


def why_impact_address(
    client: LoupeClient, contract: str, findings: list[dict[str, Any]], excluded_pct: float | None
) -> pd.DataFrame:
    """The table every persona sees first.

    One row per open finding, worst first. **Impact** is the finding's own `affected_rows`
    plus the share of records cleaning excluded for the contract — both measured upstream.

    **Why** carries the corroboration state where the finding has one. Two findings that look
    identical can call for opposite responses — a settlement outside a range the tape confirms
    is ordinary, while one outside a range the tape *disputes* means the range is the broken
    field — so the qualification belongs beside the finding rather than a click away.
    """
    address = _address(client, contract)
    rows = []
    for finding in findings[:10]:
        rows.append(
            {
                "Why": _why(finding),
                "Impact": _impact(finding, excluded_pct),
                "Address": address,
            }
        )
    return pd.DataFrame(rows)


def _why(finding: dict[str, Any]) -> str:
    """The finding, and what the tape makes of it (`specs/loupe-ui-design.md`, Specifics).

    The state arrives on the finding itself (`specs/api-contract.md` §6.2), so this cell renders
    what it was given and computes nothing — which is the point: a widget deriving the state
    from `REC.*` findings itself would be a second, quietly different reading of them.
    """
    headline = f"{finding['rule_id']} · {finding.get('trade_date') or EM_DASH}"
    corroboration = finding.get("corroboration")
    if not isinstance(corroboration, dict):
        return headline
    label = _CORROBORATION_LABEL.get(corroboration.get("state", ""))
    if not label:
        return headline
    return f"{headline}\n{label} — {corroboration.get('reason', '')}".rstrip(" —")


def _impact(finding: dict[str, Any], excluded_pct: float | None) -> str:
    rows = finding.get("affected_rows") or 0
    share = f" · {percentage(excluded_pct)} of records excluded" if excluded_pct else ""
    return f"{rows} record(s){share}"


def _render_table(frame: pd.DataFrame) -> None:
    """No `column_config` help here on purpose: Why / Impact / Address are the explanation."""
    if frame.empty:
        st.success("Nothing open for this contract in the current window.")
        return
    st.dataframe(frame, hide_index=True, width="stretch")


def _changelog_panel(client: LoupeClient, contract: str, start, end) -> None:
    """What cleaning decided, as counts — the audit trail behind the clean series."""
    st.markdown("**Changelog**")
    st.caption(helptext.JARGON["changelog"])
    try:
        body = client.changelog(contract=contract, start=start, end=end)
    except ApiProblem as problem:
        st.warning(str(problem))
        return
    entries = body.get("data") or []
    if not entries:
        st.caption("No cleaning decisions for this contract in this window.")
        return
    frame = pd.DataFrame(
        [
            {
                "When": e.get("trade_date") or EM_DASH,
                "Rule": e.get("rule_id") or EM_DASH,
                "Action": e["action"],
                "Records": e["records"],
            }
            for e in entries
        ]
    )
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            name: st.column_config.Column(name, help=helptext.COLUMNS[name])
            for name in frame.columns
            if name in helptext.COLUMNS
        },
    )


def _bars(client: LoupeClient, contract: str, start, end, basis: str = "clean") -> list[dict]:
    try:
        return client.bars_daily(
            contract=contract, start=start, end=end, basis=basis
        ).get("data", [])
    except ApiProblem as problem:
        st.warning(str(problem))
        return []


# ---------------------------------------------------------------------- Risk


def render_risk(client: LoupeClient, contract: str, findings, start, end, excluded) -> None:
    """Closing-day callouts, share excluded, raw vs clean. No tick log, no outlier hunting."""
    _render_table(why_impact_address(client, contract, findings, excluded))

    left, right = st.columns(2)
    with left:
        st.markdown("**Daily OHLCV** · quality on the candle")
        charts.candles(_bars(client, contract, start, end))
    with right:
        st.markdown("**Raw vs clean close**")
        try:
            compare = client.compare(
                contract=contract, start=start, end=end, compare="basis"
            )
            charts.raw_vs_clean(compare.get("data", []))
        except ApiProblem as problem:
            st.warning(str(problem))


# -------------------------------------------------------------------- Trader


def render_trader(client: LoupeClient, contract: str, findings, start, end, excluded) -> None:
    """One contract, warnings, changelog, and the VWAP refused in place when daily-only."""
    _render_table(why_impact_address(client, contract, findings, excluded))

    st.markdown("**Warnings**")
    if findings:
        st.dataframe(
            _findings_frame(findings)[["Rule", "When", "What"]],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No open warnings in this window.")

    _changelog_panel(client, contract, start, end)

    left, right = st.columns(2)
    with left:
        st.markdown("**Daily OHLCV** · clean")
        bars = _bars(client, contract, start, end)
        charts.candles(bars)
        charts.volume(bars)
    with right:
        st.markdown("**Rolling 15-minute VWAP**")
        st.caption(helptext.JARGON["vwap"])
        _vwap_panel(client, contract, start, end)


def _vwap_panel(client: LoupeClient, contract: str, start, end) -> None:
    """The panel stays and explains itself; it never silently renders empty.

    A daily-only contract cannot have a 15-minute line, and the API says so with a structured
    `CAP.FREQUENCY_UNAVAILABLE` rather than an empty series — the distinction slice 3 built
    the capability state to preserve. Collapsing it back into a blank chart here would throw
    that away at the last step.
    """
    try:
        body = client.vwap(contract=contract, start=start, end=end)
    except ApiProblem as problem:
        if problem.code == "CAP.FREQUENCY_UNAVAILABLE":
            st.info(f"**Needs minute bars.** {problem}")
        else:
            st.warning(str(problem))
        return
    charts.vwap_line(body.get("data", []))


# ------------------------------------------------------------------- Analyst


def render_analyst(client: LoupeClient, contract: str, findings, start, end, excluded) -> None:
    """The deep view: findings log, raw neighbourhood, patterns and suggestions as text."""
    _render_table(why_impact_address(client, contract, findings, excluded))

    st.markdown("**Findings log** · read-only")
    if not findings:
        st.caption("No open findings for this contract in this window.")
        return

    frame = _findings_frame(findings)
    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Severity": st.column_config.Column("Severity", help=helptext.COLUMNS["Severity"])
        },
        on_select="rerun",
        selection_mode="single-row",
        key=f"findings-{contract}",
    )
    rows = (getattr(event, "selection", None) or {}).get("rows") or []
    selected = findings[rows[0]] if rows else None

    _neighbourhood(client, contract, selected)
    _patterns_and_suggestions(client, contract)
    _changelog_panel(client, contract, start, end)

    st.markdown("**Daily OHLCV** · finding as overlay")
    charts.candles(_bars(client, contract, start, end, basis="raw"))


def _neighbourhood(client: LoupeClient, contract: str, finding: dict[str, Any] | None) -> None:
    """Raw rows around the selected finding. Collapsed until one is selected; never an editor.

    **Daily grain only in v1** (`specs/loupe-ui-design.md`, Analyst Specifics). No route
    returns raw market records, so `bars/daily` on the raw basis is the whole mechanism. A
    minute-grain finding says which grain it is showing rather than rendering an empty table —
    the difference between "we cannot show this" and "there is nothing here".
    """
    st.markdown("**Raw neighbourhood**")
    st.caption(helptext.JARGON["raw neighbourhood"])
    if finding is None:
        st.caption("Select a finding above to open its neighbourhood.")
        return

    if finding.get("frequency") != "daily":
        st.info(
            f"This is a {finding.get('frequency') or 'non-daily'}-grain finding. The raw "
            "neighbourhood is daily-grain in this release, so the evidence in **What** above "
            "and the charts below are the record for it."
        )
        return

    day = finding.get("trade_date")
    if not day:
        st.caption("This finding is not pinned to a trade date.")
        return
    window = pd.Timestamp(day)
    try:
        rows = client.bars_daily(
            contract=contract,
            start=(window - pd.Timedelta(days=3)).date(),
            end=(window + pd.Timedelta(days=3)).date(),
            basis="raw",
        ).get("data", [])
    except ApiProblem as problem:
        st.warning(str(problem))
        return
    if not rows:
        st.caption("No raw rows around this finding.")
        return
    frame = pd.DataFrame(rows)[
        [c for c in ("trade_date", "open", "high", "low", "close", "volume") if c in rows[0]]
    ]
    frame["← flagged"] = [
        "←" if str(r.get("trade_date")) == str(day) else "" for r in rows
    ]
    st.dataframe(frame, hide_index=True, width="stretch")
    st.caption("Not an editor · report-only")


def _patterns_and_suggestions(client: LoupeClient, contract: str) -> None:
    """Both are slice 6 reports. Shown as text when present, explained when not."""
    left, right = st.columns(2)
    with left:
        st.markdown("**Patterns** · lift")
        st.caption(helptext.JARGON["lift"])
        _report(client, "patterns", contract)
    with right:
        st.markdown("**Suggestions** · report-only")
        _report(client, "suggestions", contract)


def _report(client: LoupeClient, name: str, contract: str) -> None:
    try:
        body = client.get(f"/insights/{name}", contract=contract)
    except ApiProblem:
        st.caption(
            f"The {name} report is not in this build. It ships with the reconciliation and "
            "suggestions slice."
        )
        return
    except Exception:  # noqa: BLE001
        st.caption(f"The {name} report is unavailable.")
        return
    items = body.get("data") or []
    if not items:
        st.caption(f"No {name} for this contract.")
        return
    st.dataframe(pd.DataFrame(items), hide_index=True, width="stretch")


# ------------------------------------------------------------------ entry point

_RENDERERS = {"Risk": render_risk, "Trader": render_trader, "Analyst": render_analyst}


def render_specifics(
    persona: str,
    client: LoupeClient,
    contract: str | None,
    start,
    end,
    summary: dict[str, Any] | None = None,
) -> None:
    """Draw Specifics for the selected contract. No apply or override controls, in any branch."""
    st.subheader("Specifics")
    st.caption("why attention is needed · how you address it")

    if not contract:
        st.info("Select a contract in the Summary table above.")
        return

    st.markdown(f"**Selected: {contract}**")
    _headline(contract, summary)

    try:
        findings = client.findings(
            contract=contract, start=start, end=end, status="open", limit=200
        ).get("data", [])
    except ApiProblem as problem:
        st.warning(str(problem))
        findings = []

    excluded = _excluded_share(summary, contract)
    _RENDERERS[persona](client, contract, findings, start, end, excluded)


def _headline(contract: str, summary: dict[str, Any] | None) -> None:
    row = _row(summary, contract)
    if row is None:
        return
    freqs = ", ".join(row.get("frequencies", [])) or EM_DASH
    st.caption(
        f"Score {score_text(row.get('score'))} · {row.get('finding_count', 0)} open "
        f"finding(s) · {freqs} loaded"
    )


def _row(summary: dict[str, Any] | None, contract: str) -> dict[str, Any] | None:
    for row in (summary or {}).get("contracts", []):
        if row["contract_id"] == contract:
            return row
    return None


def _excluded_share(summary: dict[str, Any] | None, contract: str) -> float | None:
    """Share of records cleaning excluded, from the summary envelope's own counts."""
    records = (summary or {}).get("records") or {}
    total = records.get("total") or 0
    excluded = records.get("excluded") or 0
    if not total or not excluded:
        return None
    return round(100 * excluded / total, 1)
