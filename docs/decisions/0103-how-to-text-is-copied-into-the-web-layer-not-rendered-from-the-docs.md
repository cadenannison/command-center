# 0103. The per-source how-to text lives in `web/howto.py`, copied from the docs, not rendered from them

Status: accepted

Context: Each settings card gets a collapsible step-by-step how-to (HTML `details`/`summary`, no JavaScript) taken from `docs/sources.md` and `docs/gmail-setup.md`. Where the docs are unsure of a vendor menu path the text must say "may differ".
Decision: The steps are a plain data module, `HOWTO`, one entry per source, shortened from the docs. Menu paths the docs give for Canvas, Apple, Google Cloud and AI Studio carry "may differ", because those vendors rename menus (`gmail-setup.md` itself notes the newer Google UI). LearningSuite's docs do not say where the iCal link is, so the text says it may differ and does not invent a path. The Canvas URL step repeats the docs' example only. Nothing the user typed is ever put into it.
Alternative: Render the markdown files at request time (a markdown dependency, which needs asking first, and the docs hold repo-relative links and developer commands that make no sense on a page); or link to the docs (they are files in the repo, not served).
Reason: Short static text needs no dependency and cannot echo a value. The cost is two copies of the wording.
Where: `src/command_center/web/howto.py`; `<details class="howto">` in `_card.html`. Tests: `test_every_card_has_a_collapsible_how_to_without_javascript` and the three that check the Canvas, Gemini and Gmail wording.
Revisit when: The docs change a step: update both, or generate one from the other.
