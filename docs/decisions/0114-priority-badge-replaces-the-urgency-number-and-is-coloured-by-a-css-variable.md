# 0114. The priority badge replaces the urgency number on rows and is coloured by a CSS variable

Status: accepted

Context: Task A2 asks for a priority badge on every item on Today, Week and Month: hue from green (1) to red (10), readable in light and dark, the number always printed. Rows showed the raw 0-100 urgency in a grey badge.
Decision: `Row` gains `priority` (from `Event.priority`, 0110) and `_rows.html` prints it in place of the urgency number, so the three pages change in one place. Each badge sets `style="--p:N"`; CSS computes `--hue: calc(120 - (var(--p) - 1) * 13.333)` (120 is green, 0 is red) and uses it in `hsl()` for background, text and border. Light theme: background lightness 86%, text 16%. Dark theme: background 21%, text 88%. Those lightness gaps keep text well above 4.5:1 at every hue. The number is real text (with a visually hidden "Priority" prefix); the title attribute says "Priority N of 10". An item with no priority (done or ended) shows a dashed "–" with hidden text "No priority". The week column load badge and the month cells keep their urgency sums (`tests/test_web_pages.py` pins the week load badge). The urgent-row styling on `.badge` no longer applies to rows.
Alternative: (a) Keep the urgency number and add the priority beside it: two numbers per row for one idea. (b) Ten fixed colour classes: more CSS and no continuous scale. (c) Compute the colour in Python: the view would carry presentation. (d) Colour only: fails the "never the only signal" rule.
Reason: One derivation (core), one template, and a scale that works in both themes from CSS alone. Contrast was reasoned from the lightness values, not measured in a browser.
Where: `web/views.py` (`Row.priority`), `web/templates/_rows.html`, `web/templates/base.html`; `tests/test_web_priority.py`.
Revisit when: the badge needs a measured contrast check in a browser (yellow-green hues are the closest case), or the week load and month heat should be expressed as priority too.
