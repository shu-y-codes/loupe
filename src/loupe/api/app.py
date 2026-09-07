"""The FastAPI application factory.

`create_app` is a factory rather than a module-level singleton so tests can hand it an
in-memory connection, and so opening the real database is not a side effect of importing
this module.

Everything below the API raises domain errors that know nothing about HTTP. The handlers
registered here are where those become RFC 7807 problem responses, which keeps the
translation in one readable list instead of scattered through `try` blocks.
"""

from __future__ import annotations

import sys

import duckdb
from duckdb import CatalogException
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from loupe.data import LoupeDataError, apply_schema, connect, seed_reference
from loupe.data.connection import database_path
from loupe.data.errors import UnsupportedFileFormat
from loupe.quality import seed_quality
from loupe.quality.errors import LoupeQualityError

from .deps import Database
from .errors import ProblemError, problem_response, validation_problem
from .routes import analytics, dq, ingest, insights, reference

API_PREFIX = "/v1"

DESCRIPTION = """
Data quality and market insights for historical futures data.

**Conventions.** All timestamps are UTC on the wire. Dates are *trade dates* (session
dates), never calendar dates. `basis` is `raw` or `clean`; `frequency` is `minute` or
`daily`. Every endpoint is synchronous — writes return the finished result, never a poll
handle. Errors are RFC 7807 problem details carrying a `code` from the same vocabulary as
data-quality findings: `STR.*` for a request the loader cannot structurally accept, `CAP.*`
for a well-formed request the ingested data cannot support.
""".strip()


def create_app(
    connection: duckdb.DuckDBPyConnection | None = None,
    *,
    bootstrap: bool = True,
) -> FastAPI:
    """Build the app over `connection`, or over the default store when none is given.

    `bootstrap` applies the schema and seeds reference data **and the rule catalogue**, so any
    way of starting this app produces a store it can actually serve.

    **It defaults on, and that is a reversal.** It was off, on the grounds that creating tables
    as a side effect of starting a server would hide a misconfigured `LOUPE_DB` behind an empty
    but healthy-looking store. That risk is real and the answer to it was wrong: it made the
    documented `uvicorn loupe.api.app:create_app --factory` produce an app that refused every
    request until someone found the other factory name, which is a worse failure and a far more
    likely one. The resolved store path is printed on the way up instead, so a misconfigured
    `LOUPE_DB` is *visible* rather than prevented by refusing to work.

    Pass `bootstrap=False` for the case the original reasoning cared about: inspecting a store
    that should already exist, where creating one silently would be the wrong answer.

    The rule catalogue used to be a separate step, on the grounds that rules are rows and which
    rules a deployment wants is its decision. That is true and it is still true — `seed_rules`
    is idempotent and re-seedable, and nothing here stops a deployment disabling or retuning a
    row afterwards. What it is not is a reason to ship a half-open store: without it every
    upload is refused with `RulesNotSeeded`, so the documented `uvicorn` command produced an app
    that answered `/v1/health` cheerfully and could not ingest a file. Seeding the declared
    catalogue is the honest default for a bootstrap that claims to make a store usable.
    """
    con = connection if connection is not None else connect()
    if bootstrap:
        apply_schema(con)
        seed_reference(con)
        seed_quality(con)
        if connection is None:
            # Named, not hidden. This is what stops a mistyped `LOUPE_DB` looking like an
            # empty corpus: the path is in the server log before the first request.
            print(f"loupe: store ready at {database_path()}", file=sys.stderr)

    app = FastAPI(
        title="Loupe API",
        version="1.0.0",
        description=DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
    )
    app.state.database = Database(con)

    for router in (reference.router, ingest.router, analytics.router, dq.router,
                   insights.router):
        app.include_router(router, prefix=API_PREFIX)

    _register_error_handlers(app)
    return app


def bootstrapped_app() -> FastAPI:
    """`create_app()`, kept as a name because the README and older commands point at it.

    It was the only way to reach `bootstrap=True` from `uvicorn --factory`, which calls its
    target with no arguments. Bootstrapping is the default now, so this is an alias — retained
    because a documented command that stops working is its own kind of setup step.
    """
    return create_app()


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return validation_problem(request, exc)

    @app.exception_handler(UnsupportedFileFormat)
    def _format(request: Request, exc: UnsupportedFileFormat) -> JSONResponse:
        return problem_response(
            request,
            ProblemError(
                status=415,
                title="Unsupported file format",
                detail=str(exc),
                code="STR.UNSUPPORTED_FORMAT",
                type_="/errors/unsupported-file-format",
            ),
        )

    @app.exception_handler(LoupeDataError)
    def _data(request: Request, exc: LoupeDataError) -> JSONResponse:
        # A data-layer error that reached here was not anticipated by a handler. It is still
        # the client's request that provoked it, so it is a 422 rather than a 500 — but the
        # code says which layer refused, so an unmapped case is findable rather than opaque.
        return problem_response(
            request,
            ProblemError(
                status=422,
                title="Request could not be processed",
                detail=str(exc),
                code="STR.DATA_ERROR",
                type_="/errors/data-error",
            ),
        )

    @app.exception_handler(CatalogException)
    def _catalog(request: Request, exc: CatalogException) -> JSONResponse:
        # A store nobody has bootstrapped. Every table this app reads lives in a schema
        # `apply_schema` creates, so a missing catalog entry on a fresh file is the ordinary
        # first-run state rather than a defect — and answering it with a 500 carrying a raw
        # `Catalog Error` tells a new user the app is broken when the truth is that it has not
        # been set up. 503 rather than 4xx: the request was fine, the server is not ready yet.
        #
        # The underlying message leads the detail rather than being replaced by a guess, so a
        # genuinely missing relation on a healthy store still reads as what it is.
        return problem_response(
            request,
            ProblemError(
                status=503,
                title="Store not initialised",
                detail=(
                    f"{exc} Apply the schema and seed reference data once before using the "
                    "app (see the README, Setup); GET /v1/health reports whether that has "
                    "happened."
                ),
                code="CAP.STORE_NOT_INITIALISED",
                type_="/errors/store-not-initialised",
            ),
        )

    @app.exception_handler(LoupeQualityError)
    def _quality(request: Request, exc: LoupeQualityError) -> JSONResponse:
        return problem_response(
            request,
            ProblemError(
                status=409,
                title="Quality layer refused",
                detail=str(exc),
                code="CAP.QUALITY_UNAVAILABLE",
                type_="/errors/quality-unavailable",
            ),
        )
