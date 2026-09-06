"""Labelled defect injection, with a manifest that says exactly what was done.

    python -m loupe.demo.injection data/samples/ESZ25.csv --out data/demo/ESZ25_injected.csv

The sample minute corpus is effectively defect-free — 5,295,239 rows and four of the seven
`error` rules find nothing at all in it (`specs/sample-corpus.md` §7.1, §8). A demo that leads
with real findings is the right demo, and the corpus supplies plenty: the timezone trap,
settlements outside the traded range, off-tick settlements. What it cannot supply is the defect
types it happens not to contain, and a rule with no example is a rule nobody can see work.

**Three rules this module keeps, and each is a rule about honesty rather than about code.**

*Never corrupt a pristine sample.* Injection reads one file and writes another; it refuses to
write over its source, and the manifest records the SHA-256 of both. A corrupted sample that
nobody labelled is indistinguishable from a vendor defect, and it would end up quoted in a spec.

*Every defect is labelled before it exists.* The manifest is not a description written
afterwards — each injector returns the label for what it did in the same statement that does
it, and the file is written from that pass. There is no way to inject something the manifest
does not carry, because the injector cannot mutate a row without returning its label.

*The manifest is ground truth a test can fail against.* It names the rule each defect should
trip, so `tests/demo/` can run the real engine over the injected file and assert that the
findings and the labels agree. That is the difference between a demo prop and a test asset: a
prop only has to look wrong, and this has to *be* wrong in a stated way.

Deterministic throughout. Injection sites are chosen by position from a seeded ordering rather
than at random, so two runs over one input produce the same file and the same manifest, and a
demo rehearsed on Monday is the demo given on Friday.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

#: Where injection is allowed to land. Every row a defect touches is named in the manifest by
#: its **output** row number, which is what a finding's `source_row` will carry.
Row = dict[str, str]

#: The column that carries a row's identity through the mutations, stripped before writing.
#:
#: Row *positions* move: a duplicate inserted at row 20 pushes everything after it down one, and
#: a deleted run pulls it up five. A manifest built from the index an injector was handed would
#: therefore be right when it was written and wrong by the time the file was. That is worse than
#: no manifest — a wrong label sends a reader to an innocent row and quietly exonerates the
#: guilty one. So defects are anchored to identity and the row numbers are resolved once, at the
#: end, from where every row actually ended up.
_UID = "__uid"


@dataclass(frozen=True)
class Defect:
    """One injected defect, labelled with the rule it is meant to trip."""

    defect_id: str
    rule_id: str
    kind: str
    contract_id: str
    source_row: int = field(
        metadata={"note": "1-based row in the OUTPUT file, matching stage.market_record"}
    )
    timestamp: str | None = None
    field_name: str | None = None
    original: str | None = None
    injected: str | None = None
    note: str = ""

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Manifest:
    """Ground truth for one injected file. Written beside it, never inside it."""

    source: str
    source_sha256: str
    output: str
    output_sha256: str
    rows_in: int
    rows_out: int
    seed: int
    defects: list[Defect]

    @property
    def rule_ids(self) -> set[str]:
        return {d.rule_id for d in self.defects}

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_sha256": self.source_sha256,
            "output": self.output,
            "output_sha256": self.output_sha256,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "seed": self.seed,
            "defects": [d.as_json() for d in self.defects],
        }


@dataclass(frozen=True)
class InjectionReport:
    """What one run produced — the two paths and the manifest between them."""

    output_path: Path
    manifest_path: Path
    manifest: Manifest


class RefusedToOverwrite(RuntimeError):
    """The output would land on the input. Refused rather than resolved (see the module note)."""


# ------------------------------------------------------------------------------- injectors
#
# Each takes the rows and the index it was given, mutates in place, and returns the label for
# what it did — or `None` when the chosen row cannot carry that defect, in which case the caller
# tries the next candidate rather than forcing one. A row already at zero volume cannot be given
# a negative one, and pretending otherwise would put a defect in the manifest that is not in the
# file.


def _negative_volume(rows: list[Row], index: int, contract: str) -> _Pending | None:
    row = rows[index]
    volume = row.get("volume")
    if not volume or not volume.strip("-").isdigit() or int(volume) <= 0:
        return None
    row["volume"] = str(-int(volume))
    return _defect(
        "VAL.NEGATIVE_VOLUME", "negate_volume", contract, row,
        field_name="volume", original=volume, injected=row["volume"],
        note="A count of contracts traded has no negative value.",
    )


def _high_below_low(rows: list[Row], index: int, contract: str) -> _Pending | None:
    row = rows[index]
    high, low = row.get("high"), row.get("low")
    if not high or not low or float(high) <= float(low):
        return None
    row["high"], row["low"] = low, high
    return _defect(
        "CON.HIGH_LT_LOW", "swap_high_and_low", contract, row,
        field_name="high", original=high, injected=row["high"],
        note="The bar's range is inverted, so no other range test is meaningful.",
    )


def _close_out_of_range(rows: list[Row], index: int, contract: str) -> _Pending | None:
    row = rows[index]
    high = row.get("high")
    if not high:
        return None
    original = row.get("close")
    row["close"] = f"{float(high) + 5.0:.2f}"
    return _defect(
        "CON.CLOSE_OUT_OF_RANGE", "close_above_high", contract, row,
        field_name="close", original=original, injected=row["close"],
        note="An intraday close is a trade and must sit inside the session's own range.",
    )


def _null_field(rows: list[Row], index: int, contract: str) -> _Pending | None:
    row = rows[index]
    original = row.get("close")
    if original in (None, ""):
        return None
    row["close"] = ""
    return _defect(
        "CMP.NULL_FIELD", "blank_close", contract, row,
        field_name="close", original=original, injected="",
        note="An empty cell parses, so it loads and is flagged; a non-numeric string is a "
             "STR.* reject instead.",
    )


def _price_magnitude(rows: list[Row], index: int, contract: str) -> _Pending | None:
    row = rows[index]
    original = row.get("close")
    if not original:
        return None
    row["close"] = f"{float(original) * 10:.2f}"
    return _defect(
        "VAL.PRICE_MAGNITUDE", "decimal_shift_10x", contract, row,
        field_name="close", original=original, injected=row["close"],
        note="The classic decimal shift: a price ten times its plausible band.",
    )


#: Injectors that edit one row in place, in the order they are offered a site.
_IN_PLACE: tuple[Callable[[list[Row], int, str], _Pending | None], ...] = (
    _negative_volume,
    _high_below_low,
    _close_out_of_range,
    _null_field,
    _price_magnitude,
)


def _exact_duplicate(rows: list[Row], index: int, contract: str) -> tuple[list[Row], _Pending]:
    """Repeat one row verbatim — `UNQ.EXACT_DUPLICATE`, which cleaning resolves by itself."""
    copy = dict(rows[index])
    copy[_UID] = f"{copy[_UID]}+dup"
    rows.insert(index + 1, copy)
    return rows, _defect(
        "UNQ.EXACT_DUPLICATE", "repeat_row", contract, copy,
        note="Identical across every field. The lowest source_row is kept and the rest are "
             "dedupe_drop-ed (spec §14).",
    )


def _key_conflict(rows: list[Row], index: int, contract: str) -> tuple[list[Row], _Pending]:
    """Repeat one timestamp with a *different* close — the case with no principled winner."""
    copy = dict(rows[index])
    copy[_UID] = f"{copy[_UID]}+conflict"
    original = copy.get("close") or "0"
    copy["close"] = f"{float(original) + 1.25:.2f}"
    rows.insert(index + 1, copy)
    return rows, _defect(
        "UNQ.KEY_CONFLICT", "conflicting_close_on_one_timestamp", contract, copy,
        field_name="close", original=original, injected=copy["close"],
        note="Two different values for one key. Every row in the conflict is excluded: there "
             "is no principled winner inside one file.",
    )


def _missing_run(
    rows: list[Row], index: int, contract: str, length: int = 5
) -> tuple[list[Row], _Pending]:
    """Delete a contiguous run of rows — a mid-session gap, reported as one finding."""
    removed = rows[index : index + length]
    first = removed[0]
    del rows[index : index + length]
    # The deleted rows are gone, so there is nothing left to anchor to. The row that now
    # follows the gap is the anchor — it is where a reader should look — and the label carries
    # the timestamp of the first slot that went missing rather than that row's own.
    survivor = rows[index] if index < len(rows) else rows[-1]
    started_at = first.get("timestamp") or first.get("date")
    return rows, replace(
        _defect(
            "CMP.MISSING_TIMESTAMP",
            f"delete_{len(removed)}_consecutive_rows",
            contract,
            survivor,
            note=f"{len(removed)} expected grid slots with no record, starting at "
            f"{started_at}. One finding per run, with affected_rows set to the slot count.",
        ),
        timestamp=started_at,
    )


def _out_of_order(rows: list[Row], index: int, contract: str) -> tuple[list[Row], _Pending]:
    """Swap two adjacent rows so `ts_utc` decreases as `source_row` increases."""
    rows[index], rows[index + 1] = rows[index + 1], rows[index]
    return rows, _defect(
        "TIM.OUT_OF_ORDER", "swap_adjacent_rows", contract, rows[index + 1],
        note="ts_utc decreases as source_row increases within one contract and frequency.",
    )


# ------------------------------------------------------------------------------------ core


@dataclass(frozen=True)
class _Pending:
    """A defect that knows *which row* it touched but not yet where that row ended up."""

    rule_id: str
    kind: str
    contract_id: str
    anchor: str
    timestamp: str | None
    field_name: str | None = None
    original: str | None = None
    injected: str | None = None
    note: str = ""

    def resolve(self, source_row: int) -> Defect:
        return Defect(
            defect_id="d_"
            + hashlib.sha1(
                f"{self.rule_id}|{self.kind}|{self.anchor}".encode()
            ).hexdigest()[:12],
            rule_id=self.rule_id,
            kind=self.kind,
            contract_id=self.contract_id,
            source_row=source_row,
            timestamp=self.timestamp,
            field_name=self.field_name,
            original=self.original,
            injected=self.injected,
            note=self.note,
        )


def _defect(
    rule_id: str,
    kind: str,
    contract: str,
    row: Row,
    **extra: Any,
) -> _Pending:
    return _Pending(
        rule_id=rule_id,
        kind=kind,
        contract_id=contract,
        anchor=row[_UID],
        timestamp=row.get("timestamp") or row.get("date"),
        **extra,
    )


def inject(
    source: Path,
    output: Path,
    *,
    seed: int = 20260906,
    manifest_path: Path | None = None,
    rules: tuple[str, ...] | None = None,
) -> InjectionReport:
    """Write a defective copy of `source` to `output`, with a manifest beside it.

    Refuses to write over its input. That refusal is the whole point: an injected file is
    labelled data and a sample is evidence, and once the two are the same file nobody can tell
    which numbers in a spec were measured and which were manufactured.

    `rules` narrows the injection to named rule IDs, so a demo can plant one defect type and
    show it end to end without the other eight competing for the screen.
    """
    source, output = Path(source), Path(output)
    if output.resolve() == source.resolve():
        raise RefusedToOverwrite(
            f"{output} is the source file. Injection writes a copy and never edits a sample "
            "in place; pass a different --out."
        )

    raw = source.read_bytes()
    with source.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows: list[Row] = [dict(row) for row in reader]
    rows_in = len(rows)
    if rows_in < 40:
        raise ValueError(
            f"{source} holds {rows_in} rows; injection needs at least 40 so the sites do not "
            "overlap and each defect stays attributable to one rule."
        )

    contract = rows[0].get("contract") or rows[0].get("contract_symbol") or "?"
    for index, row in enumerate(rows):
        row[_UID] = str(index)
    defects = _resolve(rows, _apply(rows, contract, seed=seed, rules=rules))

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        # `extrasaction="ignore"` is what keeps `__uid` out of the file: it is scaffolding for
        # the manifest and has no business in data anyone loads.
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    manifest = Manifest(
        source=source.name,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        output=output.name,
        output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        rows_in=rows_in,
        rows_out=len(rows),
        seed=seed,
        defects=defects,
    )
    path = manifest_path or output.with_suffix(output.suffix + ".manifest.json")
    path.write_text(json.dumps(manifest.as_json(), indent=2, sort_keys=False) + "\n")
    return InjectionReport(output_path=output, manifest_path=path, manifest=manifest)


def _apply(
    rows: list[Row], contract: str, *, seed: int, rules: tuple[str, ...] | None
) -> list[_Pending]:
    """Choose sites and run the injectors, structural ones last.

    The order is not cosmetic. Every in-place injector addresses a row by index, so they all run
    before anything inserts or deletes and none of them is handed a position that has already
    moved. What makes the *manifest* correct, though, is not the order but `_UID`: the row
    numbers are resolved after the last mutation, from where each row actually ended up.
    """
    rng = random.Random(seed)
    # Spread across the file rather than clustered, for two reasons. An injected file should
    # still look like a plausible feed, and a pattern report should not read the injection
    # itself as the dominant concentration. The stride also has to leave enough sites that
    # every injector gets one after the exclusion radius below has thinned them — too few and
    # the last rule silently gets none, which would make `INJECTABLE_RULES` a claim the
    # manifest does not keep.
    stride = max(3, len(rows) // 24)
    sites = list(range(stride, len(rows) - 12, stride))
    rng.shuffle(sites)
    wanted = set(rules) if rules else None
    pending: list[_Pending] = []

    for injector in _IN_PLACE:
        if wanted is not None and _RULE_OF[injector] not in wanted:
            continue
        for index in list(sites):
            defect = injector(rows, index, contract)
            if defect is not None:
                pending.append(defect)
                sites.remove(index)
                break

    for structural, rule_id in _STRUCTURAL:
        if wanted is not None and rule_id not in wanted:
            continue
        if not sites:
            break
        index = sites.pop()
        rows, defect = structural(rows, index, contract)
        pending.append(defect)
        # Retire the neighbourhood. A duplicate inserted beside a row whose volume was negated
        # would put two defects within a few rows of each other, and a finding in that
        # neighbourhood could no longer be attributed to one label.
        sites = [site for site in sites if abs(site - index) > 12]

    return pending


def _resolve(rows: list[Row], pending: list[_Pending]) -> list[Defect]:
    """Turn identities into output row numbers, once, after every mutation has happened.

    `source_row` is 1-based and counts the data rows the loader will number, not the header —
    `stage.market_record.source_row` is what a finding cites, and the manifest has to speak the
    same coordinate or it cannot be checked against one.
    """
    positions = {row[_UID]: index + 1 for index, row in enumerate(rows)}
    resolved = [
        item.resolve(positions[item.anchor])
        for item in pending
        if item.anchor in positions
    ]
    return sorted(resolved, key=lambda d: d.source_row)


#: Structural injectors — the ones that change how many rows there are — in the order they are
#: offered a site, after every in-place injector has taken one.
_STRUCTURAL: tuple[tuple[Callable[..., Any], str], ...] = (
    (_exact_duplicate, "UNQ.EXACT_DUPLICATE"),
    (_key_conflict, "UNQ.KEY_CONFLICT"),
    (_out_of_order, "TIM.OUT_OF_ORDER"),
    (_missing_run, "CMP.MISSING_TIMESTAMP"),
)

#: Which rule each in-place injector is meant to trip, so `rules=` can select without the
#: caller knowing the function names.
_RULE_OF: dict[Callable[..., Any], str] = {
    _negative_volume: "VAL.NEGATIVE_VOLUME",
    _high_below_low: "CON.HIGH_LT_LOW",
    _close_out_of_range: "CON.CLOSE_OUT_OF_RANGE",
    _null_field: "CMP.NULL_FIELD",
    _price_magnitude: "VAL.PRICE_MAGNITUDE",
}

#: Every rule this module can plant. Named so a test can assert the manifest covers what it
#: claims to, rather than trusting whatever the run happened to produce.
INJECTABLE_RULES: frozenset[str] = frozenset(_RULE_OF.values()) | {
    "UNQ.EXACT_DUPLICATE",
    "UNQ.KEY_CONFLICT",
    "TIM.OUT_OF_ORDER",
    "CMP.MISSING_TIMESTAMP",
}


def load_manifest(path: Path) -> Manifest:
    """Read a manifest back — the ground truth a test asserts findings against."""
    payload = json.loads(Path(path).read_text())
    return Manifest(
        source=payload["source"],
        source_sha256=payload["source_sha256"],
        output=payload["output"],
        output_sha256=payload["output_sha256"],
        rows_in=payload["rows_in"],
        rows_out=payload["rows_out"],
        seed=payload["seed"],
        defects=[Defect(**d) for d in payload["defects"]],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("source", type=Path, help="A clean CSV to derive a defective copy from.")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the copy.")
    parser.add_argument("--seed", type=int, default=20260906)
    parser.add_argument(
        "--rule",
        action="append",
        dest="rules",
        help="Restrict to one rule id; repeatable. Default: every injectable rule.",
    )
    args = parser.parse_args(argv)
    try:
        report = inject(
            args.source, args.out, seed=args.seed, rules=tuple(args.rules) if args.rules else None
        )
    except (RefusedToOverwrite, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {report.output_path} ({report.manifest.rows_out} rows)")
    print(f"manifest {report.manifest_path}: {len(report.manifest.defects)} labelled defect(s)")
    for defect in report.manifest.defects:
        print(f"  row {defect.source_row:>7}  {defect.rule_id:<24} {defect.kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
