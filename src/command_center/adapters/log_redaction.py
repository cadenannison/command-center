"""Keeps the city search text out of uvicorn's access log (decision 0180).

uvicorn logs `GET /v1/geocode?q=Provo` for every request; a filter on `uvicorn.access` cuts the
query string off the paths in QUIET_QUERY_PATHS before any handler formats the line.
"""

import logging

QUIET_QUERY_PATHS = ("/v1/geocode",)
ACCESS_LOGGER = "uvicorn.access"
_PATH_ARG = 2  # uvicorn's access record args: client, method, path, http version, status


class QueryStringFilter(logging.Filter):
    """Rewrites an access record so the query string of a QUIET_QUERY_PATHS path is gone."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) <= _PATH_ARG:
            return True
        path = args[_PATH_ARG]
        if isinstance(path, str) and path.startswith(QUIET_QUERY_PATHS) and "?" in path:
            record.args = (*args[:_PATH_ARG], path.partition("?")[0], *args[_PATH_ARG + 1 :])
        return True


def install_query_redaction() -> None:
    """Attach the filter to uvicorn's access logger once; safe to call twice."""
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(item, QueryStringFilter) for item in access.filters):
        access.addFilter(QueryStringFilter())
