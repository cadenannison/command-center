# Decision records

One file per decision, named `NNNN-short-title.md`. The format, the "superseded by" rule and the
index (`docs/generated/decision-index.md`, built by `mise run gen:build`) are in
`scripts/gen_decision_index.py`. Only files that match `NNNN-*.md` are decisions; this README and
`tooling-versions.md` are not.

## Numbering: unused numbers are reserved gaps

The project manager hands each task card a range of numbers (for example "use 0245-0249 only").
A card uses what it needs, from the low end up. **A number that is left unused inside a range is a
reserved gap, not a free slot.** Do not fill it, do not renumber to close it, and do not take a
number from a range your card did not give you: another session may be writing it at the same
time, and a record is cited by number from code, tests and other records, so a number never moves.
A gap in the index is expected. To change a decision, write a new record that supersedes the old
one (see `AGENTS.md`); never reuse a number.

Ranges on disk today (each block is contiguous; the numbers between blocks are reserved gaps):

| Range | Used |
|---|---|
| 0001-0058 | 0001-0058 |
| 0060 | 0060 |
| 0070-0095 | 0070-0095 |
| 0100-0106 | 0100-0106 |
| 0110-0116 | 0110-0116 |
| 0120-0131 | 0120-0131 |
| 0140-0141 | 0140-0141 |
| 0150-0153 | 0150-0153 |
| 0160-0172 | 0160-0172 |
| 0180-0184 | 0180-0184 |
| 0190-0192 | 0190-0192 (task G1: Gmail wording, credential-storage wording) |
| 0200-0203 | 0200-0203 |
| 0210-0213 | 0210-0213 |
| 0220-0225 | 0220-0225 |
| 0230-0233 | 0230-0233 |
| 0240-0244 | 0240-0244 (task R1) |
| 0245-0249 | 0245-0249 (task R2) |
| 0250-0258 | 0250-0258 (agent-cost aids 0250-0254, redaction 0255, task C3 0256-0258) |
| 0260-0262 | 0260-0262 (task R1, round 3) |
| 0270 | 0270 (task C4) |
| 0280-0284 | 0280-0284 (task R3: redaction keeps agenda content) |
| 0285-0289 | 0285-0289 (task T1: tooling and doc fixes) |
| 0290-0292 | 0290-0292 (task C5: chat key shapes) |
| 0300-0304 | 0300-0304 (task K1: TypeScript UI foundation) |
| 0310 | 0310 (task H2: redact timing budget) |
| 0315-0316 | 0315-0316 (task P1a: pnpm pin and workspace settings, config files without dependencies) |
| 0320-0324 | 0320-0324 (task P1b: typed client, today agenda, design tokens and theme, lockfile guard, TypeScript pin) |
| 0325 | 0325 (task P1c: reduced motion) |
| 0330-0336 | 0330-0336 (task D1: design reference, widgets, urgency, privacy copy, Dismiss, accessibility, assistant) |
| 0340-0343 | 0340-0343 (task T1: design tokens and display settings, Sora, dev-only gallery, token details) |
| 0345-0346 | 0345-0346 (tasks T1b, T1c: tailwind-merge text-caption and contrast test, four AA token values) |
| 0350 | 0350 (task R1: widget registry and layout model, compaction, auto-arrange, columns, source rules) |
| 0355-0358 | 0355-0358 (task R2: layout validation, dashboard and display tables with revisions, phone read-only policy, container wiring) |
| 0360-0363 | 0360-0363 (task R3: dashboard grid geometry, editing, saving, route and data; 0364 unused) |
| 0370-0371 | 0370-0371 (task W1a: urgency reasons, GET /v1/tasks) |
| 0372 | 0372 (task W1a2: undated open tasks in GET /v1/tasks) |
| 0373-0374 | 0373-0374 (task W1b: Tasks widget on the dashboard grid; edit-mode heading, drag handle and focus fixes) |
| 0375-0377 | 0375-0377 (task U1+U3+U4: refetch keeps the view, Weather widget, Week widget) |
| 0378-0380 | 0378-0380 (task U2+polish: Events widget, previous window kept on a date change, weather copy, merge guard, test zone, save-status role) |
| 0381-0382 | 0381-0382 (task U5: Summary card pinned above the grid, column tiers, fetch once per day; privacy copy and its code-reading test) |
| 0383-0384 | 0383-0384 (task E1: edit toolbar, widget gallery, widget menu, reset templates; export and the deferred undo and redo shortcuts) |
| 0385-0386 | 0385-0386 (task U6a: Needs me inclusion rule and constants; GET /v1/needs-me and the old attention scorer left in place) |
| 0387-0388 | 0387-0388 (task U6b: Needs me widget keeps the server's order and reads time from `at`; a delayed live-region announcement is dropped when a newer one is made) |

Reserved gaps between those blocks: 0059, 0061-0069, 0096-0099, 0107-0109, 0117-0119, 0132-0139,
0142-0149, 0154-0159, 0173-0179, 0185-0189, 0193-0199, 0204-0209, 0214-0219, 0226-0229, 0234-0239, 0259, 0263-0269, 0271-0279, 0293-0299, 0305-0309, 0311-0314, 0326-0329, 0337-0339, 0359, 0364.

The table is read from the files, so it shows where numbers were used, not how wide each card's
allocation was: a block may have been given more numbers than it used. If you need a number and
your card gave you none, ask the project manager.
