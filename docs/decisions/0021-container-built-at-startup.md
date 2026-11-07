# 0021. The service container is built at application startup, not at import

Status: accepted

Context: The card gives `api.create_app(container)` and `app.build_container()`. `app.create_app()` already exists with no arguments and is used by `scripts/gen_docs.py` and `tests/test_smoke.py`. `build_container()` opens the database (creating its directory and tables), so building it eagerly would write to `~/.command-center` whenever the app is constructed, including by `gen:build` and tests.
Decision: `api.create_app` takes a `Container` or a zero-argument factory. A factory is called in the FastAPI lifespan, so the container exists once the server starts. `app.create_app()` keeps its no-argument signature and passes `build_container` as the factory. `main()` passes a factory built from one `Settings` and runs uvicorn on `settings.host` and `settings.port`.
Alternative: Build the container in `app.create_app()`, which touches disk at construction; a module-level container, which is a global.
Reason: Constructing the app stays free of side effects, so `gen:build` and import-time checks need no home directory, keychain or database.
Where: `src/command_center/api/factory.py`, `src/command_center/api/deps.py`, `src/command_center/app.py`.
Revisit when: The container needs async setup or teardown (closing the database), or workers share it.
