# 0009. pyright over ty

Status: accepted

Context: The kit suggests `ty`, which is beta, pin-exact, and lacks first-class Pydantic and FastAPI support. This project is built on both.
Decision: Use pyright in strict mode (`mise run typecheck`).
Consequences: pyright's PyPI wrapper needs a Node runtime, so mise pins Node. Revisit when ty reaches a stable release with Pydantic support.
