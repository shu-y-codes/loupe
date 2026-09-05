"""Errors raised by the quality layer. Nothing here knows about HTTP."""

from __future__ import annotations


class LoupeQualityError(Exception):
    """Base class for every failure the quality layer raises deliberately."""


class RulesNotSeeded(LoupeQualityError):
    """`dq.dq_rule` is empty, so a rule pass would silently evaluate nothing.

    Seeding is explicit rather than automatic: a run that quietly seeded its own rules would
    make `ruleset_hash` a statement about this process rather than about the database.
    """

    def __init__(self) -> None:
        super().__init__(
            "no rules are seeded in dq.dq_rule; call loupe.quality.seed_quality(con) first"
        )
