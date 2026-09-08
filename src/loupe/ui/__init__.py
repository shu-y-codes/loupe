"""The `ui` layer: Streamlit pages and a thin API client.

Owns pages and clients. Owns no SQL, no rule logic and no aggregation — those belong to
`data`, `quality` and `insights`, and the client is the only way this package reaches them
(`specs/loupe-solution-design.md` §6).

`app.py` is the entry (Review default, Overview sibling) and draws on import, so it is
deliberately not imported here; run it with
`streamlit run src/loupe/ui/app.py`, or point `AppTest` at it.
"""

from .client import ApiProblem, ApiUnavailable, LoupeClient
from .runtime import EM_DASH, get_client, use_client

__all__ = [
    "EM_DASH",
    "ApiProblem",
    "ApiUnavailable",
    "LoupeClient",
    "get_client",
    "use_client",
]
