"""The `api` layer: FastAPI `/v1`, matching `specs/api-contract.md`.

Handlers resolve scope, call `data` / `quality` / `insights`, and render envelopes. **No
business maths lives here**: no aggregation, no score arithmetic, no decision about what may
be published (`specs/loupe-solution-design.md` §6). A handler that needed a number the layers
below do not expose is a signal that the number belongs in one of them, and slice 4 moved two
such decisions down rather than computing them here — the batch purge cascade into
`data.purge`, and the frequency-capability refusal into `insights.gate`.
"""

from .app import API_PREFIX, create_app
from .errors import PROBLEM_MEDIA_TYPE, ProblemError

__all__ = ["API_PREFIX", "PROBLEM_MEDIA_TYPE", "ProblemError", "create_app"]
