---
paths:
  - "src/**/*.py"
  - "scripts/**/*.py"
---
- No narration comments (`# get the user` above `get_user()`). One short docstring per public name;
  comments inside a function explain why, not what.
- snake_case modules named after their main export; aim for <300 lines per file; full type hints
  (pyright strict); pydantic models for anything crossing a boundary.
- Error messages say what failed and why ("Failed to fetch Canvas courses: token rejected (401)"), plus
  a machine-readable reason code where the caller needs one. Define exception classes per failure class.
- No bare `except`, no swallowed errors, no circular imports. `__init__` only assigns dependencies;
  work that can fail goes in a factory function.
- Every outbound HTTP call has an explicit timeout. Datetimes are timezone-aware (UTC internally).
