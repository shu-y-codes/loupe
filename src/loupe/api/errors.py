"""RFC 7807 problem details, and the mapping from layer errors onto them.

The layers below raise domain errors that know nothing about HTTP
(`loupe.data.errors`, `loupe.quality.errors`). This module is the single place where those
become status codes, so a handler never chooses one inline and the error vocabulary stays
in one file.

`code` carries the same `STR.*` / `CAP.*` families the findings use, which is what lets the
UI render transport errors and data-quality findings through one component
(`specs/api-contract.md` §2.2). It is deliberately not the HTTP status: two different
refusals can share a 422 and still need to be told apart by a client.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

#: RFC 7807 says a problem response carries its own media type, not `application/json`.
PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemError(Exception):
    """A refusal that already knows how it should be rendered.

    Raised by handlers for the cases the contract names. Anything raised below the API is
    translated by a handler registered in `app.py` rather than by being caught here, so the
    layers stay ignorant of HTTP.
    """

    def __init__(
        self,
        *,
        status: int,
        title: str,
        detail: str,
        code: str,
        type_: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.code = code
        self.type = type_
        self.meta = meta


def problem_response(request: Request, problem: ProblemError) -> JSONResponse:
    """Render a problem, with `instance` taken from the request that produced it."""
    body: dict[str, Any] = {
        "type": problem.type,
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
        "instance": _instance(request),
        "code": problem.code,
    }
    if problem.meta is not None:
        body["meta"] = problem.meta
    return JSONResponse(
        status_code=problem.status, content=body, media_type=PROBLEM_MEDIA_TYPE
    )


def _instance(request: Request) -> str:
    """Path plus query — `/v1/analytics/vwap?contract=GCJ26` as the contract's example shows."""
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422 body is not RFC 7807; this makes it so.

    The per-field errors are kept under `meta.errors` rather than dropped: a client that
    wants to highlight the offending parameter still can, and the human-readable `detail`
    still reads as one sentence.
    """
    errors = exc.errors()
    detail = "; ".join(_one_error(e) for e in errors) or "Request validation failed."
    return problem_response(
        request,
        ProblemError(
            status=422,
            title="Invalid request",
            detail=detail,
            code="STR.INVALID_REQUEST",
            type_="/errors/invalid-request",
            meta={"errors": [_safe_error(e) for e in errors]},
        ),
    )


def _one_error(error: dict[str, Any]) -> str:
    location = ".".join(str(part) for part in error.get("loc", ()) if part != "query")
    message = error.get("msg", "invalid")
    return f"{location}: {message}" if location else message


def _safe_error(error: dict[str, Any]) -> dict[str, Any]:
    """Drop the `ctx` key, which can hold an exception object JSON cannot render."""
    return {k: v for k, v in error.items() if k in ("loc", "msg", "type")}
