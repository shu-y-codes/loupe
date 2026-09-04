"""Contract symbology.

The corpus uses the clean CME form with a two-digit year (`ESZ25`, `SR3M26`, `ZNH26`).
`SR3` is a three-character root, so a parser assuming two characters of root mis-parses a
quarter of the corpus (`specs/sample-corpus.md` §3.2). The parse is therefore
right-anchored: two year digits, one month code, and whatever precedes them is the root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTH_CODES: dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}

_SYMBOL = re.compile(r"^(?P<root>[A-Z0-9]{1,5}?)(?P<month>[FGHJKMNQUVXZ])(?P<year>\d{2})$")

# Century for a two-digit year. Every contract in the corpus is 2021-2026; a feed reaching
# back before 2000 would need the year window widened, not the parser rewritten.
_CENTURY = 2000


@dataclass(frozen=True)
class ParsedSymbol:
    """A contract symbol broken into its parts, with a confidence in the break."""

    contract_id: str
    root: str | None
    month_code: str | None
    contract_month: date | None
    parse_confidence: float

    @property
    def parsed(self) -> bool:
        return self.root is not None


def parse_symbol(contract_id: str, known_roots: set[str] | None = None) -> ParsedSymbol:
    """Split a contract symbol into root, month code and delivery month.

    `known_roots` raises confidence from 0.7 to 1.0 when the recovered root is one we have
    reference data for. An unparseable symbol is not an error: it is
    `STR.UNKNOWN_CONTRACT_FORMAT`, which warns and continues.
    """
    match = _SYMBOL.match(contract_id.strip().upper())
    if match is None:
        return ParsedSymbol(contract_id, None, None, None, 0.0)

    root = match.group("root")
    month_code = match.group("month")
    year = _CENTURY + int(match.group("year"))
    contract_month = date(year, MONTH_CODES[month_code], 1)

    confidence = 1.0 if known_roots and root in known_roots else 0.7
    return ParsedSymbol(contract_id, root, month_code, contract_month, confidence)
