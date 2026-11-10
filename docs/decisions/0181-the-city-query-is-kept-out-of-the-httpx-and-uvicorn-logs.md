# 0181. The city query is kept out of the httpx and uvicorn logs by two filters

Status: accepted

Context: Task W1 says the search is rate limited and "the query text is not logged". The code never logs it, but two libraries do: httpx logs `HTTP Request: GET <full url>` at INFO, and uvicorn's access logger logs `GET /v1/geocode?q=<text> HTTP/1.1`. The composition root sends the root logger to a JSON handler at INFO with `log_config=None`, so both lines reach the output with the typed text in them.
Decision:
- `adapters/weather_geocode.py` adds a `logging.Filter` to the `httpx` logger, once, when the module is imported; it drops a record whose message contains the geocoding URL. Other httpx lines (the forecast, Canvas) are unchanged.
- `adapters/log_redaction.py` has `QueryStringFilter`, which cuts the query string off the path argument of a `uvicorn.access` record when the path starts with `/v1/geocode`; `install_query_redaction()` attaches it, and `main()` in `app.py` calls it after `configure_json_logging()`. The line is still logged, without `?q=...`. The web form's own geocode route (card W1, web part) must be added to `QUIET_QUERY_PATHS` when it exists.
- The service logs only a reason code and the exception class.
Alternative: Set the `httpx` logger to WARNING and run uvicorn with `access_log=False` (loses every other access line and every other httpx line for a problem on one route); send the query in a POST body (Open-Meteo's geocoding API is GET only, and our own route is a GET like the other reads); leave it and document it (it breaks the card's stated rule).
Reason: The filters are small, scoped to the one URL, and keep the rest of the log as it was. Run by hand, a geocoding request emitted the httpx line without the filter and nothing with it; the tests hold the with-filter side.
Where: `src/command_center/adapters/weather_geocode.py` (`_QuietRequestLog`), `src/command_center/adapters/log_redaction.py`, `src/command_center/app.py` (`main`); tests `tests/test_weather_geocode_adapter.py::test_the_query_text_reaches_no_log_record`, `tests/test_geocode_logging.py`. `main()` itself is a `pragma: no cover` entry point, so the filter is tested directly and through `install_query_redaction`.
Revisit when: The access log is dropped or reworked, or another route takes free text from the user.
