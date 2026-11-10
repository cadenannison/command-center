# 0151. The reason tooltip sits on a wrapper because the badge's own title is pinned

Status: accepted

Context: `tests/test_web_priority.py` (decision 0114) asserts the badge's `title="Priority N of 10"` and the "No priority: done or ended" text. Task B2 has `tests: new-only`, so those assertions cannot change.
Decision: The reason goes in a `<span class="why" title="...">` around the badge. The inner badge keeps its title and gets `pointer-events: none`, so the browser shows the wrapper's tooltip (the reason) on hover instead of the old one. The reason is also written out in the details panel, which is the place for touch and keyboard users, who get no hover.
Alternative: Change the badge's `title` to the reason and edit the pinned test; put the reason only in the details panel.
Reason: Editing an existing test to fit a new design is not allowed (AGENTS.md), and a details-only reason would hide it from the quick hover look the card asks for.
Where: `src/command_center/web/templates/_rows.html` (badge macro), `src/command_center/web/templates/base.html` (`.why`), `tests/test_web_items.py`.
Revisit when: `tests/test_web_priority.py` is next allowed to change; fold the two titles into one.
