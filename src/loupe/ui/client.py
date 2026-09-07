"""The only thing in `ui` that knows the API exists.

One module holds the base URL, the verbs and the error translation, for two reasons. It is
the layer boundary `specs/loupe-solution-design.md` §6 draws — `ui` owns pages and thin
clients, never SQL or rule logic — and it is the seam the page tests stub, which is what lets
`streamlit.testing.v1.AppTest` assert view assembly without a server or a database.

Talking HTTP rather than importing `loupe.api` is deliberate. Importing the app would be one
process and no port, but it would fuse the two layers and make the thin-client boundary
untestable *as* a boundary — the pages would keep working if someone reached past the client
into `quality`, and nothing would notice.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

#: Where the API is. The README's `uvicorn` command serves exactly this.
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"

#: Seconds. Ingest is synchronous by decision (`specs/api-contract.md` §4.4) and a large
#: upload validates inside the request, so this is generous on purpose.
DEFAULT_TIMEOUT = 120.0


class ApiUnavailable(RuntimeError):
    """The API did not answer. Distinct from an error it *did* answer with."""


@dataclass(frozen=True)
class ApiProblem(RuntimeError):
    """An RFC 7807 problem the API returned, carried whole.

    A refusal is information, not a failure to render: `CAP.FREQUENCY_UNAVAILABLE` on a
    daily-only contract is the VWAP panel's content, not an empty chart. Pages catch this and
    explain in place, so the `code` and `detail` survive the trip.
    """

    status: int
    code: str | None
    title: str
    detail: str | None
    meta: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.detail or self.title


def base_url() -> str:
    """`LOUPE_API_URL`, or the local default. Read per call so tests can repoint it."""
    return os.environ.get("LOUPE_API_URL", DEFAULT_BASE_URL).rstrip("/")


def _params(values: dict[str, Any]) -> dict[str, Any]:
    """Drop unset filters, and spell dates and lists the way the contract does."""
    out: dict[str, Any] = {}
    for key, value in values.items():
        if value is None or value == [] or value == "":
            continue
        if isinstance(value, (list, tuple, set)):
            out[key] = ",".join(str(v) for v in sorted(value))
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


class LoupeClient:
    """Thin HTTP client. Every method is one call and returns the parsed envelope."""

    def __init__(self, url: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.url = (url or base_url()).rstrip("/")
        self.timeout = timeout

    # ---------------------------------------------------------------- plumbing

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = httpx.request(
                method, f"{self.url}{path}", timeout=self.timeout, **kwargs
            )
        except httpx.HTTPError as exc:  # no server, DNS, timeout
            raise ApiUnavailable(
                f"No answer from {self.url}. Is the API running? "
                f"`uvicorn loupe.api.app:create_app --factory`"
            ) from exc
        if response.status_code >= 400:
            raise _problem(response)
        return response.json()

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=_params(params))

    # ------------------------------------------------------------- reference

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def contracts(self, **params: Any) -> dict[str, Any]:
        return self.get("/contracts", **params)

    # ------------------------------------------------------------- analytics

    def bars_daily(self, **params: Any) -> dict[str, Any]:
        return self.get("/analytics/bars/daily", **params)

    def vwap(self, **params: Any) -> dict[str, Any]:
        return self.get("/analytics/vwap", **params)

    def compare(self, **params: Any) -> dict[str, Any]:
        return self.get("/analytics/compare", **params)

    # ------------------------------------------------------------ data quality

    def summary(self, **params: Any) -> dict[str, Any]:
        return self.get("/dq/summary", **params)

    def metrics(self, **params: Any) -> dict[str, Any]:
        return self.get("/dq/metrics", **params)

    def findings(self, **params: Any) -> dict[str, Any]:
        return self.get("/dq/findings", **params)

    def changelog(self, **params: Any) -> dict[str, Any]:
        return self.get("/dq/changelog", **params)

    def run_rules(self, **params: Any) -> dict[str, Any]:
        """`POST /v1/dq/runs` — re-validate a scope, corpus-wide when unscoped (§6.4).

        The demo needs this and so does anyone who uploads a second granularity: an upload runs
        the rules scoped to *its own batch*, so cross-frequency reconciliation cannot be in
        scope at that moment — the run has not seen the other grain yet.
        """
        return self._request("POST", "/dq/runs", params=_params(params))

    def suggestions(self, **params: Any) -> dict[str, Any]:
        """Slice 6 (`plans/06-rec-suggestions-demo.md` done-when 4).

        The method exists so the Analyst view has one place to call; until the route lands it
        raises `ApiProblem` with a 404, which the page renders as "not in this build" rather
        than as an empty suggestions list. Stubbing the text here instead would put copy in a
        widget that belongs to `quality`.
        """
        return self.get("/insights/suggestions", **params)

    # ---------------------------------------------------------------- ingest

    def batches(self, **params: Any) -> dict[str, Any]:
        """`GET /v1/ingest/batches` — the sidebar inventory reads this, not the sample directory."""
        return self.get("/ingest/batches", **params)

    def purge_batch(self, batch_id: str) -> dict[str, Any]:
        """`DELETE /v1/ingest/batches/{id}` — the way back out of a demo.

        Injected defects have to be removable without deleting the store, or nobody presses the
        button that plants them.
        """
        return self._request("DELETE", f"/ingest/batches/{batch_id}")

    def preview(self, filename: str, content: bytes) -> dict[str, Any]:
        return self._request(
            "POST", "/ingest/preview", files={"file": (filename, content)}
        )

    def create_batch(
        self,
        filename: str,
        content: bytes,
        *,
        validate: bool = True,
        origin: str = "upload",
    ) -> dict[str, Any]:
        """Ingest a file. A re-upload of the same bytes is refused with something to say.

        `specs/api-contract.md` §4.3 answers a duplicate with **409 and the existing batch** —
        idempotent re-upload, surfaced rather than silently duplicated. That body is a batch
        summary, not a problem document, so the blanket "4xx means problem" rule in `_request`
        would turn the most informative refusal in the app into a bare `Conflict` with no
        detail at all: the user is told no, and not that their file is already loaded.

        So it is translated here, keeping the batch the server named. Found by
        `tests/integration/`, which is the only tier with a real client on one side of the
        wire and the real API on the other.
        """
        try:
            return self._request(
                "POST",
                "/ingest/batches",
                files={"file": (filename, content)},
                params={"validate": validate, "origin": origin},
            )
        except ApiProblem as problem:
            if problem.status != 409:
                raise
            existing = problem.meta or {}
            batch_id = existing.get("batch_id")
            raise ApiProblem(
                status=409,
                code="STR.DUPLICATE_FILE",
                title="Already ingested",
                detail=(
                    "These exact bytes were already loaded"
                    + (f" as batch {batch_id}" if batch_id else "")
                    + ". Nothing was ingested a second time."
                ),
                meta=existing,
            ) from None


def _problem(response: httpx.Response) -> ApiProblem:
    """Translate RFC 7807 into something a page can explain in place."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    # A 4xx body is *usually* RFC 7807, but not always: §4.3's duplicate-file refusal answers
    # 409 with the existing batch summary. Keeping the whole body as `meta` when it carries no
    # `title` means a caller can still say something specific instead of rendering a status
    # code — `create_batch` is the one that does.
    problem_shaped = "title" in body or "detail" in body
    return ApiProblem(
        status=response.status_code,
        code=body.get("code"),
        title=body.get("title") or response.reason_phrase or "Request failed",
        detail=body.get("detail"),
        meta=body.get("meta") if problem_shaped else (body or None),
    )
