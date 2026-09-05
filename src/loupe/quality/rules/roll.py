"""Roll and expiry — `ROL.*`. These exist to *reduce* noise.

Without them the last two weeks of every contract generate completeness alerts for entirely
normal market behaviour: volume migrates to the next month and the expiring contract goes
quiet. Both are `info`, both sit in the `completeness` dimension, and neither excludes
anything.

`ROL.THIN_NEAR_EXPIRY` reports the same window the completeness rules suppress inside. The
window is computed once per run in `windows.resolve_roll_windows` from this rule's own
`params`, so the finding that explains the suppression and the suppression itself cannot
drift apart.
"""

from __future__ import annotations

from ..registry import RECORDS, Finding, RuleContext, rule


@rule("ROL.THIN_NEAR_EXPIRY")
def thin_near_expiry(ctx: RuleContext) -> list[Finding]:
    """Volume has collapsed in the final sessions before expiry."""
    findings: list[Finding] = []
    for window in ctx.inputs.roll_windows.values():
        findings.append(
            ctx.finding(
                contract_id=window.contract_id,
                frequency=window.frequency,
                trade_date=window.end,
                affected_rows=1,
                details={
                    "window_start": str(window.start),
                    "window_end": str(window.end),
                    "expiry_basis": window.expiry_basis,
                    "median_session_volume_inside": window.median_volume_inside,
                    "median_session_volume_before": window.median_volume_before,
                    "days": ctx.param("days"),
                    "collapse_ratio": ctx.param("collapse_ratio"),
                    "effect": "completeness checks are suppressed inside this window",
                },
            )
        )
    return sorted(findings, key=lambda f: (f.contract_id or "", f.frequency or ""))


@rule("ROL.NO_SUCCESSOR")
def no_successor(ctx: RuleContext) -> list[Finding]:
    """A contract runs to expiry with no later-dated contract of the same root in the corpus.

    Reported because the roll cannot be followed, not because anything is wrong with the data
    that is present: an analyst asking for a continuous series needs to know the chain ends
    here rather than receiving a series that quietly stops.
    """
    days = int(ctx.param("days", 30))
    rows = ctx.con.execute(
        f"""
        WITH slices AS (
          SELECT r.contract_id, r.frequency, r.root,
                 max(r.trade_date) AS last_session,
                 any_value(coalesce(r.last_trade_date, NULL)) AS listed_expiry
          FROM {RECORDS} r
          WHERE r.root IS NOT NULL AND {ctx.frequency_filter()}
          GROUP BY 1, 2, 3
        ),
        present AS (
          SELECT DISTINCT r.contract_id, c.root, c.contract_month
          FROM {RECORDS} r
          JOIN ref.contract c ON c.contract_id = r.contract_id
          WHERE c.contract_month IS NOT NULL
        )
        SELECT s.contract_id, s.frequency, s.last_session,
               coalesce(s.listed_expiry, s.last_session) AS expiry,
               s.root
        FROM slices s
        JOIN ref.contract self ON self.contract_id = s.contract_id
        WHERE self.contract_month IS NOT NULL
          AND abs(datediff('day', s.last_session,
                           coalesce(s.listed_expiry, s.last_session))) <= ?
          AND NOT EXISTS (
            SELECT 1 FROM present p
            WHERE p.root = s.root AND p.contract_month > self.contract_month
          )
        ORDER BY 1, 2
        """,
        [days],
    ).fetchall()
    return [
        ctx.finding(
            contract_id=contract_id,
            frequency=frequency,
            trade_date=last_session,
            details={
                "last_session": str(last_session),
                "expiry": str(expiry),
                "root": root,
                "days": days,
                "reason": "no later-dated contract of this root is present in the corpus",
            },
        )
        for contract_id, frequency, last_session, expiry, root in rows
    ]
