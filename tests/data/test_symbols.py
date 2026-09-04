"""Symbology. The three-character root is the case that breaks naive parsers."""

from __future__ import annotations

from datetime import date

import pytest

from loupe.data.profiles import KNOWN_ROOTS
from loupe.data.symbols import parse_symbol


@pytest.mark.parametrize(
    ("symbol", "root", "month_code", "contract_month"),
    [
        ("ESZ25", "ES", "Z", date(2025, 12, 1)),
        ("ZNH26", "ZN", "H", date(2026, 3, 1)),
        ("VXZ25", "VX", "Z", date(2025, 12, 1)),
        ("CLG26", "CL", "G", date(2026, 2, 1)),
        ("SBK26", "SB", "K", date(2026, 5, 1)),
        ("GCH26", "GC", "H", date(2026, 3, 1)),
        ("ZCH26", "ZC", "H", date(2026, 3, 1)),
    ],
)
def test_two_character_roots(symbol, root, month_code, contract_month):
    parsed = parse_symbol(symbol, KNOWN_ROOTS)
    assert (parsed.root, parsed.month_code, parsed.contract_month) == (
        root,
        month_code,
        contract_month,
    )


def test_three_character_root():
    """SR3M26 is root SR3, not SR followed by month code 3.

    A parser assuming two characters of root mis-parses a quarter of the corpus.
    """
    parsed = parse_symbol("SR3M26", KNOWN_ROOTS)
    assert parsed.root == "SR3"
    assert parsed.month_code == "M"
    assert parsed.contract_month == date(2026, 6, 1)
    assert parsed.parse_confidence == 1.0


def test_unknown_root_still_parses_at_lower_confidence():
    parsed = parse_symbol("XYZZ25", KNOWN_ROOTS)
    assert parsed.root == "XYZ"
    assert parsed.parse_confidence == 0.7


@pytest.mark.parametrize("symbol", ["garbage", "ES", "ESZ", "ES25", "ESB25"])
def test_unparseable_symbols_are_not_an_error(symbol):
    """STR.UNKNOWN_CONTRACT_FORMAT warns and continues; it never rejects a row."""
    parsed = parse_symbol(symbol, KNOWN_ROOTS)
    assert not parsed.parsed
    assert parsed.parse_confidence == 0.0
    assert parsed.contract_id == symbol
