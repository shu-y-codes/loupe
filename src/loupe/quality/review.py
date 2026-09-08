"""Reviewer-strip cards, overlay marks, picture payloads and aggregated issues.

The Review UI (`specs/loupe-ui-design.md`) must not group `findings[]` in a widget.
This module composes the envelopes `GET /v1/dq/checks` returns. Overlay marks are keyed
on the selected family, not `max_severity`: a minute `CMP.MISSING_TIMESTAMP` can mark a
derived daily session, and `CMP.SESSION_MISSING` can mark a day that has no `mart.bar_daily`
row. Rule triggers, scores and cleaning policy are unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import duckdb

from .catalogue import (
    DUPLICATE_RULES,
    GAPS_RULES,
    INVALID_RULES,
    RULE_SUBJECT_FIELD,
    STRIP_FAMILIES,
    VOLUME_INVALID_RULES,
    strip_family,
)
from .changelog import changelog, latest_run
from .inventory import contract_rows
from .patterns import find_patterns
from .runner import RunScope, scoped
from .scoring import SliceScore, score_slice

FAMILY_LABELS: dict[str, str] = {
    "gaps": "Gaps",
    "duplicates": "Duplicates",
    "invalid": "Invalid values",
    "patterns": "Recurring patterns",
}
FAMILY_UNITS: dict[str, str] = {
    "gaps": "runs",
    "duplicates": "records",
    "invalid": "rows",
    "patterns": "standing",
}
_ACTION_VERB: dict[str, str] = {
    "exclude": "excluded",
    "dedupe_drop": "dropped",
    "coerce": "coerced",
    "impute": "imputed",
}
_RIBBON_SLOTS = 20


@dataclass(frozen=True)
class ReviewPage:
    """The Review envelope, before HTTP shaping."""

    contract_id: str
    score: float | None
    scope_signature: str | None
    dimensions_not_in_scope: list[dict[str, str]]
    frequencies: list[str]
    frequency: str
    frequency_defaulted: bool
    checked: bool
    families: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    overlay: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "score": self.score,
            "scope_signature": self.scope_signature,
            "dimensions_not_in_scope": self.dimensions_not_in_scope,
            "frequencies": self.frequencies,
            "frequency": self.frequency,
            "frequency_defaulted": self.frequency_defaulted,
            "checked": self.checked,
            "families": self.families,
            "issues": self.issues,
            "overlay": self.overlay,
            "meta": self.meta,
        }


def review_checks(
    con: duckdb.DuckDBPyConnection,
    contract_id: str,
    *,
    start: date | None = None,
    end: date | None = None,
    family: str = "gaps",
    basis: str = "clean",
    frequency: str | None = None,
) -> ReviewPage:
    """Cards, overlay, picture and issues for one contract × window × selected family."""
    if family not in STRIP_FAMILIES:
        raise ValueError(f"unknown family {family!r}; expected one of {STRIP_FAMILIES}")

    run_id = latest_run(con)
    if run_id is None:
        resolved = frequency or "minute"
        return _empty(
            contract_id,
            family,
            checked=False,
            reason="No completed validation run.",
            frequency=resolved,
            frequency_defaulted=frequency is None,
        )

    inventory = _score(con, run_id, contract_id)
    resolved = frequency or ("minute" if "minute" in inventory["frequencies"] else "daily")
    if resolved not in inventory["frequencies"]:
        raise ValueError(
            f"frequency {resolved!r} is unavailable for {contract_id}; "
            f"held: {', '.join(inventory['frequencies']) or 'none'}"
        )
    findings = _findings(con, run_id, contract_id, start, end, resolved)
    patterns = find_patterns(
        con,
        contracts=[contract_id],
        start=start,
        end=end,
        run_id=run_id,
        frequency=resolved,
    )
    actions = _actions(con, run_id, contract_id, start, end, resolved)
    score_block = _score(con, run_id, contract_id, resolved)
    families = _cards(findings, patterns)
    issues = _issues(findings, patterns, actions, family)
    overlay = _overlay(
        con, contract_id, family, findings, patterns, start, end, basis, resolved
    )

    return ReviewPage(
        contract_id=contract_id,
        score=score_block["score"],
        scope_signature=score_block["scope_signature"],
        dimensions_not_in_scope=score_block["dimensions_not_in_scope"],
        frequencies=inventory["frequencies"],
        frequency=resolved,
        frequency_defaulted=frequency is None,
        checked=True,
        families=families,
        issues=issues,
        overlay=overlay,
        meta={"run_id": run_id},
    )


def _empty(
    contract_id: str,
    family: str,
    *,
    checked: bool,
    reason: str,
    frequency: str,
    frequency_defaulted: bool,
) -> ReviewPage:
    return ReviewPage(
        contract_id=contract_id,
        score=None,
        scope_signature=None,
        dimensions_not_in_scope=[],
        frequencies=[],
        frequency=frequency,
        frequency_defaulted=frequency_defaulted,
        checked=checked,
        families=[
            {
                "family": name,
                "label": FAMILY_LABELS[name],
                "count": 0,
                "unit": FAMILY_UNITS[name],
                "detail": "Check has not run" if not checked else "Nothing in this window",
            }
            for name in STRIP_FAMILIES
        ],
        issues=[],
        overlay={
            "family": family,
            "ohlcv": [],
            "vwap": {"pattern_hours": [], "name_breaks": family in {"gaps", "patterns"}},
            "picture": {
                "kind": "empty",
                "trade_date": None,
                "caption": reason,
                "rule_ids": [],
            },
        },
        meta={"reason": reason},
    )


def _findings(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    start: date | None,
    end: date | None,
    frequency: str,
) -> list[dict[str, Any]]:
    clauses = [
        "f.run_id = ?",
        "f.contract_id = ?",
        "f.status = 'open'",
        "f.frequency = ?",
    ]
    args: list[Any] = [run_id, contract_id, frequency]
    if start is not None:
        clauses.append("f.trade_date >= ?")
        args.append(start)
    if end is not None:
        clauses.append("f.trade_date <= ?")
        args.append(end)
    rows = con.execute(
        f"""
        SELECT f.rule_id, r.name, f.trade_date, f.frequency, f.affected_rows,
               f.record_id, CAST(f.details AS VARCHAR), f.ts_start_utc, f.ts_end_utc,
               f.contract_id
        FROM dq.dq_finding f JOIN dq.dq_rule r USING (rule_id)
        WHERE {" AND ".join(clauses)}
        ORDER BY f.trade_date, f.rule_id
        """,
        args,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        details = json.loads(row[6]) if row[6] else {}
        out.append(
            {
                "rule_id": row[0],
                "label": row[1],
                "trade_date": row[2],
                "frequency": row[3],
                "affected_rows": int(row[4] or 0),
                "record_id": row[5],
                "details": details,
                "ts_start_utc": row[7],
                "ts_end_utc": row[8],
                "contract_id": row[9],
                "family": strip_family(row[0]),
            }
        )
    return out


def _actions(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    start: date | None,
    end: date | None,
    frequency: str,
) -> dict[str, list[tuple[str, int]]]:
    entries, _total = changelog(
        con, run_id, contracts=[contract_id], start=start, end=end, limit=1000, offset=0
    )
    by_rule: dict[str, dict[str, int]] = {}
    for entry in entries:
        if not entry.rule_id or entry.frequency != frequency:
            continue
        bucket = by_rule.setdefault(entry.rule_id, {})
        bucket[entry.action] = bucket.get(entry.action, 0) + entry.records
    return {rule: list(actions.items()) for rule, actions in by_rule.items()}


def _score(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    frequency: str | None = None,
) -> dict[str, Any]:
    scope = RunScope(
        contract_ids=(contract_id,),
        frequencies=(frequency,) if frequency is not None else None,
    )
    with scoped(con, scope) as (_inputs, _rows, _records):
        pairs = con.execute(
            "SELECT DISTINCT contract_id, frequency FROM dq_scope_records ORDER BY 1, 2"
        ).fetchall()
        slices: list[SliceScore] = [score_slice(con, run_id, c, f) for c, f in pairs]
    rows = contract_rows(con, run_id, slices, contracts=[contract_id])
    if not rows:
        signatures = sorted({s.scope_signature for s in slices if s.scope_signature})
        missing: list[dict[str, str]] = []
        for slice_ in slices:
            for item in slice_.dimensions_not_in_scope:
                if item not in missing:
                    missing.append(item)
        scored = [s.overall for s in slices if s.overall is not None]
        return {
            "score": min(scored) if scored else None,
            "scope_signature": (
                signatures[0] if len(signatures) == 1 else " / ".join(signatures) or None
            ),
            "dimensions_not_in_scope": missing,
            "frequencies": sorted({s.frequency for s in slices}),
        }
    row = rows[0]
    signatures = sorted({s.scope_signature for s in slices if s.contract_id == contract_id})
    missing = []
    for slice_ in slices:
        if slice_.contract_id != contract_id:
            continue
        for item in slice_.dimensions_not_in_scope:
            if item not in missing:
                missing.append(item)
    return {
        "score": row.score,
        "scope_signature": (
            signatures[0] if len(signatures) == 1 else " / ".join(signatures) or None
        ),
        "dimensions_not_in_scope": missing,
        "frequencies": row.frequencies,
    }


def _cards(
    findings: list[dict[str, Any]], patterns: list[Any]
) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("gaps", "duplicates", "invalid")
    }
    for finding in findings:
        if finding["family"] in by_family:
            by_family[finding["family"]].append(finding)
    return [
        _gap_card(by_family["gaps"]),
        _duplicate_card(by_family["duplicates"]),
        _invalid_card(by_family["invalid"]),
        _pattern_card(patterns),
    ]


def _gap_card(rows: list[dict[str, Any]]) -> dict[str, Any]:
    holes = sum(1 for r in rows if r["rule_id"] in {"CMP.MISSING_TIMESTAMP", "CMP.PARTIAL_SESSION"})
    absent = sum(1 for r in rows if r["rule_id"] == "CMP.SESSION_MISSING")
    return {
        "family": "gaps",
        "label": FAMILY_LABELS["gaps"],
        "count": len(rows),
        "unit": FAMILY_UNITS["gaps"],
        "detail": f"{holes} session-open hole{'s' if holes != 1 else ''} · "
        f"{absent} session{'s' if absent != 1 else ''} absent",
    }


def _duplicate_card(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exact = sum(1 for r in rows if r["rule_id"] == "UNQ.EXACT_DUPLICATE")
    conflict = sum(1 for r in rows if r["rule_id"] == "UNQ.KEY_CONFLICT")
    return {
        "family": "duplicates",
        "label": FAMILY_LABELS["duplicates"],
        "count": len(rows),
        "unit": FAMILY_UNITS["duplicates"],
        "detail": f"{exact} exact cop{'ies' if exact != 1 else 'y'} · "
        f"{conflict} key conflict{'s' if conflict != 1 else ''}",
    }


def _invalid_card(rows: list[dict[str, Any]]) -> dict[str, Any]:
    volumes = 0
    prices = 0
    for row in rows:
        if row["rule_id"] in VOLUME_INVALID_RULES or (
            row["rule_id"] == "CMP.NULL_FIELD" and row["details"].get("field") == "volume"
        ):
            volumes += 1
        else:
            prices += 1
    return {
        "family": "invalid",
        "label": FAMILY_LABELS["invalid"],
        "count": len(rows),
        "unit": FAMILY_UNITS["invalid"],
        "detail": f"{prices} price{'s' if prices != 1 else ''} · "
        f"{volumes} volume{'s' if volumes != 1 else ''}",
    }


def _pattern_card(patterns: list[Any]) -> dict[str, Any]:
    count = len(patterns)
    if not patterns:
        detail = "No standing pattern in this window"
    else:
        top = patterns[0]
        detail = top.narrative
    return {
        "family": "patterns",
        "label": FAMILY_LABELS["patterns"],
        "count": count,
        "unit": FAMILY_UNITS["patterns"],
        "detail": detail,
    }


def _issues(
    findings: list[dict[str, Any]],
    patterns: list[Any],
    actions: dict[str, list[tuple[str, int]]],
    selected_family: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for finding in findings:
        family = finding["family"]
        if family != selected_family:
            continue
        key = (family, finding["rule_id"], finding["label"])
        bucket = grouped.setdefault(
            key,
            {
                "family": family,
                "what": finding["label"],
                "days": set(),
                "records": 0,
                "rule_id": finding["rule_id"],
            },
        )
        if finding["trade_date"] is not None:
            bucket["days"].add(finding["trade_date"])
        bucket["records"] += finding["affected_rows"]
    rows = []
    for (_family, rule_id, _label), bucket in grouped.items():
        rows.append(
            {
                "family": bucket["family"],
                "what": bucket["what"],
                "days": len(bucket["days"]),
                "records": bucket["records"],
                "what_we_did": _what_we_did(actions.get(rule_id, [])),
            }
        )
    if selected_family == "patterns":
        for pattern in patterns:
            rows.append(
                {
                    "family": "patterns",
                    "what": pattern.narrative,
                    "days": pattern.distinct_days,
                    "records": pattern.support,
                    "what_we_did": "Reported; not applied",
                }
            )
    family_order = {name: i for i, name in enumerate(STRIP_FAMILIES)}
    return sorted(rows, key=lambda r: (family_order.get(r["family"], 9), -r["days"], r["what"]))


def _what_we_did(actions: list[tuple[str, int]]) -> str:
    if not actions:
        return "Flagged; not auto-dropped"
    return "; ".join(
        f"{_ACTION_VERB.get(action, action)} {n} record{'s' if n != 1 else ''}"
        for action, n in actions
    )


def _overlay(
    con: duckdb.DuckDBPyConnection,
    contract_id: str,
    family: str,
    findings: list[dict[str, Any]],
    patterns: list[Any],
    start: date | None,
    end: date | None,
    basis: str,
    frequency: str,
) -> dict[str, Any]:
    bar_dates = _bar_dates(con, contract_id, start, end, basis, frequency)
    pattern_dates = _pattern_dates(findings, patterns)
    by_date: dict[date, dict[str, Any]] = {}

    def cell(day: date) -> dict[str, Any]:
        row = by_date.get(day)
        if row is None:
            row = {
                "trade_date": day,
                "session": "present" if day in bar_dates else "absent",
                "partial_gap": False,
                "duplicate": False,
                "invalid": False,
                "invalid_volume": False,
                "pattern_member": day in pattern_dates,
                "caption": "",
            }
            by_date[day] = row
        return row

    for day in bar_dates:
        cell(day)

    for finding in findings:
        day = finding["trade_date"]
        if day is None:
            continue
        mark = cell(day)
        rule = finding["rule_id"]
        if rule in GAPS_RULES:
            if rule == "CMP.SESSION_MISSING" and day not in bar_dates:
                mark["session"] = "absent"
                mark["caption"] = mark["caption"] or "Settlement never arrived"
            else:
                mark["partial_gap"] = True
                slots = finding["details"].get("missing_slots") or finding["affected_rows"]
                mark["caption"] = mark["caption"] or f"{slots} missing slots at session open"
        elif rule in DUPLICATE_RULES:
            mark["duplicate"] = True
            mark["caption"] = mark["caption"] or "Kept duplicate at this timestamp"
        elif rule in INVALID_RULES:
            mark["invalid"] = True
            if rule in VOLUME_INVALID_RULES or finding["details"].get("field") == "volume":
                mark["invalid_volume"] = True
                mark["caption"] = mark["caption"] or "Volume defect"
            else:
                mark["caption"] = mark["caption"] or finding["label"]
        if day in pattern_dates:
            mark["pattern_member"] = True

    ohlcv = [_overlay_row(by_date[day]) for day in sorted(by_date)]
    picture = _picture(con, contract_id, family, findings, patterns, bar_dates, frequency, basis)
    pattern_hours = [
        p.bucket for p in patterns if p.dimension == "hour_of_day"
    ]
    return {
        "family": family,
        "ohlcv": ohlcv,
        "vwap": {
            "pattern_hours": pattern_hours if frequency == "minute" else [],
            "name_breaks": family in {"gaps", "patterns", "invalid"},
        },
        "picture": picture,
    }


def _overlay_row(row: dict[str, Any]) -> dict[str, Any]:
    day = row["trade_date"]
    return {
        "trade_date": day.isoformat() if hasattr(day, "isoformat") else str(day),
        "session": row["session"],
        "partial_gap": row["partial_gap"],
        "duplicate": row["duplicate"],
        "invalid": row["invalid"],
        "invalid_volume": row["invalid_volume"],
        "pattern_member": row["pattern_member"],
        "caption": row["caption"],
    }


def _bar_dates(
    con: duckdb.DuckDBPyConnection,
    contract_id: str,
    start: date | None,
    end: date | None,
    basis: str,
    frequency: str,
) -> set[date]:
    source = "derived" if frequency == "minute" else "vendor"
    clauses = ["contract_id = ?", "basis = ?", "source = ?"]
    args: list[Any] = [contract_id, basis, source]
    if start is not None:
        clauses.append("trade_date >= ?")
        args.append(start)
    if end is not None:
        clauses.append("trade_date <= ?")
        args.append(end)
    try:
        rows = con.execute(
            f"SELECT DISTINCT trade_date FROM mart.bar_daily WHERE {' AND '.join(clauses)}",
            args,
        ).fetchall()
    except duckdb.CatalogException:
        return set()
    return {row[0] for row in rows if row[0] is not None}


def _pattern_dates(findings: list[dict[str, Any]], patterns: list[Any]) -> set[date]:
    rule_ids = {p.rule_id for p in patterns}
    if not rule_ids:
        return set()
    return {
        f["trade_date"]
        for f in findings
        if f["rule_id"] in rule_ids and f["trade_date"] is not None
    }


def _picture(
    con: duckdb.DuckDBPyConnection,
    contract_id: str,
    family: str,
    findings: list[dict[str, Any]],
    patterns: list[Any],
    bar_dates: set[date],
    frequency: str,
    basis: str,
) -> dict[str, Any]:
    empty = {
        "kind": "empty",
        "trade_date": None,
        "caption": "This check ran. Nothing in this window.",
        "rule_ids": [],
    }
    if family == "patterns":
        return _pattern_picture(patterns) if patterns else empty
    mine = [f for f in findings if f["family"] == family]
    if family == "gaps":
        mine = [f for f in findings if f["rule_id"] in GAPS_RULES]
    elif family == "duplicates":
        mine = [f for f in findings if f["rule_id"] in DUPLICATE_RULES]
    elif family == "invalid":
        mine = [f for f in findings if f["rule_id"] in INVALID_RULES]
    if not mine:
        return empty
    if family == "gaps":
        return _gap_picture(con, mine, bar_dates)
    if family == "duplicates":
        return _duplicate_picture(con, mine)
    return _invalid_picture(con, mine, contract_id, frequency, basis)


def _gap_picture(
    con: duckdb.DuckDBPyConnection, findings: list[dict[str, Any]], bar_dates: set[date]
) -> dict[str, Any]:
    missing = [f for f in findings if f["rule_id"] == "CMP.MISSING_TIMESTAMP"]
    absent = [
        f
        for f in findings
        if f["rule_id"] == "CMP.SESSION_MISSING" and f["trade_date"] not in bar_dates
    ]
    if missing:
        pick = max(missing, key=lambda f: f["affected_rows"])
        slots = _gap_ribbon(con, pick)
        return {
            "kind": "gaps_ribbon",
            "trade_date": _iso(pick["trade_date"]),
            "caption": (
                f"{pick['affected_rows']} consecutive minute slots missing on "
                f"{pick['trade_date']}."
            ),
            "rule_ids": ["CMP.MISSING_TIMESTAMP"],
            "slots": slots,
        }
    if absent:
        pick = absent[0]
        return {
            "kind": "absent_session",
            "trade_date": _iso(pick["trade_date"]),
            "caption": (
                f"Settlement never arrived on {pick['trade_date']}. "
                "Loupe does not invent a zero-filled bar."
            ),
            "rule_ids": ["CMP.SESSION_MISSING"],
        }
    pick = findings[0]
    return {
        "kind": "gaps_ribbon",
        "trade_date": _iso(pick["trade_date"]),
        "caption": pick["label"],
        "rule_ids": [pick["rule_id"]],
        "slots": _gap_ribbon(con, pick),
    }


def _gap_ribbon(con: duckdb.DuckDBPyConnection, finding: dict[str, Any]) -> list[dict[str, Any]]:
    """A short expected-vs-present ribbon around the hole — not the whole session."""
    start = finding["ts_start_utc"]
    end = finding["ts_end_utc"]
    day = finding["trade_date"]
    contract_id = finding["contract_id"]
    if start is None or day is None or contract_id is None:
        return []
    first = start
    last = end or start
    pad_before = max(0, (_RIBBON_SLOTS - 4) // 4)
    window_start = first - timedelta(minutes=pad_before)
    window_end = window_start + timedelta(minutes=_RIBBON_SLOTS)
    if last > window_end:
        window_end = last + timedelta(minutes=1)
    present = {
        row[0]
        for row in con.execute(
            """
            SELECT date_trunc('minute', ts_utc)
            FROM stage.market_record
            WHERE contract_id = ? AND frequency = 'minute' AND trade_date = ?
              AND date_trunc('minute', ts_utc) >= ?
              AND date_trunc('minute', ts_utc) < ?
            """,
            [contract_id, day, window_start, window_end],
        ).fetchall()
    }
    slots = []
    cursor = window_start
    for _ in range(_RIBBON_SLOTS):
        label = cursor.strftime("%H:%M") if isinstance(cursor, datetime) else str(cursor)
        truncated = (
            cursor.replace(second=0, microsecond=0) if isinstance(cursor, datetime) else cursor
        )
        slots.append({"label": label, "present": truncated in present})
        cursor = cursor + timedelta(minutes=1)
        if cursor >= window_end:
            break
    return slots


def _duplicate_picture(
    con: duckdb.DuckDBPyConnection, findings: list[dict[str, Any]]
) -> dict[str, Any]:
    pick = findings[0]
    dropped_id = pick["record_id"]
    kept_id = pick["details"].get("keeps_record_id")
    ids = [i for i in (kept_id, dropped_id) if i is not None]
    rows: list[dict[str, Any]] = []
    if ids:
        placeholders = ", ".join("?" for _ in ids)
        fetched = con.execute(
            f"""
            SELECT record_id, ts_utc, open, high, low, close, volume, source_row
            FROM stage.market_record WHERE record_id IN ({placeholders})
            ORDER BY source_row
            """,
            ids,
        ).fetchall()
        by_id = {int(r[0]): r for r in fetched}
        if kept_id is not None and int(kept_id) in by_id:
            rows.append(_record_row("kept", by_id[int(kept_id)]))
        if dropped_id is not None and int(dropped_id) in by_id:
            rows.append(_record_row("dropped", by_id[int(dropped_id)]))
    return {
        "kind": "duplicate_rows",
        "trade_date": _iso(pick["trade_date"]),
        "caption": (
            "Cleaning kept the first copy and dropped the rest. "
            "The daily bar is the kept series."
        ),
        "rule_ids": [pick["rule_id"]],
        "rows": rows,
    }


def _record_row(which: str, row: tuple[Any, ...]) -> dict[str, Any]:
    ts = row[1]
    return {
        "which": which,
        "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "open": row[2],
        "high": row[3],
        "low": row[4],
        "close": row[5],
        "volume": row[6],
        "source_row": row[7],
    }


def _invalid_picture(
    con: duckdb.DuckDBPyConnection,
    findings: list[dict[str, Any]],
    contract_id: str,
    frequency: str,
    basis: str,
) -> dict[str, Any]:
    pick = findings[0]
    day = pick["trade_date"]
    evidence = None
    evidence_source = (
        "vendor"
        if frequency == "daily"
        else ("source_record" if pick["record_id"] is not None else "derived")
    )
    if pick["record_id"] is not None:
        row = con.execute(
            """
            SELECT record_id, ts_utc, open, high, low, close, volume, source_row
            FROM stage.market_record WHERE record_id = ?
            """,
            [pick["record_id"]],
        ).fetchone()
        if row:
            evidence = _record_row("accused", row)
            evidence["record_id"] = int(row[0])
    elif day is not None:
        source = "derived" if frequency == "minute" else "vendor"
        try:
            row = con.execute(
                """
                SELECT trade_date, open, high, low, close, volume
                FROM mart.bar_daily
                WHERE contract_id = ? AND trade_date = ? AND basis = ? AND source = ?
                LIMIT 1
                """,
                [contract_id, day, basis, source],
            ).fetchone()
        except duckdb.CatalogException:
            row = None
        if row:
            evidence = {
                "trade_date": _iso(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
            }
    field = pick["details"].get("field") or RULE_SUBJECT_FIELD.get(pick["rule_id"]) or "unknown"
    return {
        "kind": "invalid_cell",
        "trade_date": _iso(day),
        "caption": pick["label"],
        "rule_ids": [pick["rule_id"]],
        "field": field,
        "bar": evidence,
        "evidence_frequency": pick["frequency"] or frequency,
        "evidence_source": evidence_source,
    }


def _pattern_picture(patterns: list[Any]) -> dict[str, Any]:
    top = patterns[0]
    focused = [
        p for p in patterns if p.rule_id == top.rule_id and p.dimension == top.dimension
    ]
    buckets = [
        {
            "label": p.bucket,
            "share_of_findings": p.share_of_findings,
            "share_of_records": p.share_of_records,
            "lift": p.lift,
            "support": p.support,
            "distinct_days": p.distinct_days,
        }
        for p in focused[:8]
    ]
    axis_labels = {
        "hour_of_day": "Hour of day, exchange local",
        "day_of_week": "Day of week",
        "trade_date": "Trade date",
        "contract": "Contract",
        "frequency": "Frequency",
        "batch": "Source file",
    }
    return {
        "kind": "pattern_histogram",
        "trade_date": None,
        "caption": top.narrative,
        "rule_ids": [top.rule_id],
        "rule_id": top.rule_id,
        "dimension": top.dimension,
        "axis_label": axis_labels.get(top.dimension, top.dimension.replace("_", " ").title()),
        "patterns_total": len(patterns),
        "buckets_shown": len(buckets),
        "buckets": buckets,
    }


def _iso(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
