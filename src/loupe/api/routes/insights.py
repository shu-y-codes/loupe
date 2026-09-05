"""Insights routes (`specs/api-contract.md` §7).

**Empty in slice 4, by sequencing rather than by scope.** `GET /v1/insights/patterns` and
`GET /v1/insights/suggestions` are v1 in the contract and stay v1. Nothing backs them yet:
pattern lift and suggestion rationale are built in slice 6
([plans/06-rec-suggestions-demo.md](../../../../plans/06-rec-suggestions-demo.md) done-when
3 and 4), which runs after this one. Shipping the routes here would mean putting that maths
in a handler, which is the one thing `plans/04-api.md` forbids.

The router exists so slice 6 adds two handlers to a mounted, tagged surface rather than
touching the app factory. It is mounted and currently carries no routes — the OpenAPI
document simply has no `/v1/insights/*` paths until slice 6 lands.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/insights", tags=["insights"])
