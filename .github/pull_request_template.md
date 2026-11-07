## What and why
<!-- One paragraph. Link the decision record if this changes a boundary or the /v1 API. -->

## Checklist
- [ ] `mise run check` passes locally
- [ ] A test exists that fails without this change
- [ ] Contracts / `docs/MAP.md` updated if an interface changed; `mise run gen:build` run
- [ ] No test deleted, skipped or weakened; `.test-floor` raised if tests were added
- [ ] No secrets, tokens or personal data in the diff, logs or fixtures
- [ ] New dependency (if any) was asked for and verified on PyPI
- [ ] A change to a `/v1` path or schema is additive, or has a decision record (mobile client)
