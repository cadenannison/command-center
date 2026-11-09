# 0092. The `desktop` extra is darwin-only: remove the unmarked rumps line

Status: accepted

Context: CI runs `uv sync --all-extras` on Linux and failed building `pyobjc-core` ("PyObjC requires macOS to build"). `rumps` pulls in `pyobjc-framework-cocoa`, then `pyobjc-core`. `pyproject.toml` listed `rumps` twice under `desktop`: once without a marker and once with `; sys_platform == 'darwin'`. The unmarked line applies on every platform, so it defeated the marker, and `uv.lock` recorded both specifiers. Record 0008 says the extra is marked darwin-only so Linux CI still installs; the file did not do that.
Decision: Delete the unmarked `"rumps>=0.4.0",` line from the `desktop` extra, leaving only `"rumps>=0.4.0; sys_platform == 'darwin'"`, and re-lock with `uv lock` so the duplicate specifier leaves `uv.lock`. No version changes. This edits a dependency declaration, which AGENTS.md reserves for the human; the change was made by the project owner after it was proposed here.
Alternative: (a) Change CI to `uv sync --extra distributed --extra postgres` and skip `desktop`: leaves the broken extra for anyone on Linux who runs `--all-extras`, and `mise run setup` also uses `--all-extras`. (b) Run the Linux CI jobs on macOS: slower and costlier, and hides the mistake.
Reason: it is the smallest change that makes the declaration say what 0008 already decided. The code was already safe on Linux: `rumps` is imported only in `adapters/menubar_rumps.py`, and the other desktop modules are rumps-free (0057).
Where: `pyproject.toml` (`[project.optional-dependencies] desktop`), `uv.lock` (the `command-center` package's `requires-dist` and `desktop` extra).
Revisit when: `rumps` is replaced or dropped, or the desktop launcher gains a non-macOS implementation.
