# 0125. Notes are private plain text: never logged, never sent to the AI, rendered escaped

Status: accepted for the summary and the history view; chat may send a note once the user opts in (decision 0163)

Context: A note is free text the user wrote about an item and may hold anything. It sits next to titles and due dates, which the summary feature does see.
Decision: A note is 1 to 4000 characters of plain text (`MAX_NOTE`, blank after trimming is refused). The 422 for a bad note says `note must be 1 to 4000 characters` and does not echo the text (decision 0023). The ledger engine is created with `hide_parameters=True`, so a database error carries neither the note nor the title (decision 0027); no route or service logs a note. The note is not an `Event` field (only `has_note` is), so redaction and the summary prompt never receive it, and `tests/test_items_ledger_api.py` checks that a summary provider is not sent it. It is read back only through `GET /v1/history`, which returns it as a JSON string and never as markup. This task adds no web view of notes; whoever builds one must render it with Jinja2's default escaping (a task for the web layer, which this task did not touch). A note is replaced by a new `PUT` and removed by `DELETE`, which is harmless when there is none.
Alternative: Allow markdown or HTML (a new escaping surface for no stated need); let the summary use notes (breaks the rule that the AI sees titles, due dates and trimmed subjects only, AGENTS.md rule 6).
Reason: The safest note is one that has exactly one path out, the user's own history view.
Where: `src/command_center/core/ledger.py` (`NoteInput`, `MAX_NOTE`), `api/items.py`, `storage/sqlite_items.py` (`create_item_ledger`); tests in `tests/test_items_ledger_api.py`.
Revisit when: Notes need formatting or search; both widen who can read them.
