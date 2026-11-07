# 0017. Scoring tunables are not a parameter yet

Status: accepted

Context: `core.scoring.urgency` turns an event and `now` into a score from 0 to 100 using thresholds (24 hours, 72 hours, 7 days, 2 hours before an event) and score values per kind. `docs/contracts/core.md` lists "scoring tunables passed in as data" as planned.
Decision: The thresholds and score values stay as module constants in `scoring.py`. `urgency(event, now)` takes no configuration argument.
Alternative: Add a `ScoringConfig` parameter (or settings entries) now so the bands can be changed without editing code. We would be guessing the shape of the configuration before anyone has said which numbers they want to change.
Reason: Nobody has asked to tune the scores, a speculative config shape tends to be wrong, and adding a parameter later is a small, contained change because the contract and tests pin the current behaviour.
Where: `src/command_center/core/scoring.py`; the scoring table and the "Planned" list in `docs/contracts/core.md`.
Revisit when: The project manager asks to tune the scoring. Then decide which values become data and where they are configured, and write a new record.
