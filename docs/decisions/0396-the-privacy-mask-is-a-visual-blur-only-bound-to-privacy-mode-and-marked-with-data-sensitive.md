# 0396. The privacy mask is a visual blur only, bound to privacy_mode and marked with data-sensitive

Status: accepted

Context: Display setting `privacy_mode` already exists in the stored document and had no control. The mask must not claim more than it does (0333, 0381, 0382).
Decision: The rail's Privacy button toggles `privacy_mode` through `useDisplaySettings().update`, so it is saved with the rest of the document. `applySettings` sets `data-privacy="on"` on the root element when it is on and removes it otherwise. CSS (`index.css`) blurs `[data-sensitive]` under `:root[data-privacy="on"]` and lifts the blur on `:hover`, on `:focus-within`, and for text inside a focus-visible link, button or tabindex element. The DOM text and accessible names are not changed. Marked: event titles and locations, task and needs-me titles and their reason texts (server text that can name people or items), week-widget item titles and the Now/Next title, the summary headline, priorities and heads-up, and the legacy `/today` row titles. Not marked: times, counts, priorities, weather. The Privacy button's description says it is a visual mask only. It protects nothing beyond how the screen looks: the text is still in the page, in screenshots of the DOM, to screen readers and to other software.
Alternative: Replace the text with bullets in the DOM (rejected: it changes accessible names and would hide data from the user's own screen reader). Hide the whole page (rejected by the card).
Reason: Shoulder-surfing protection that costs nothing in accessibility, with copy that does not overclaim.
Where: `ui/src/shell/rail.tsx`, `ui/src/features/display/display-apply.ts`, `ui/src/styles/index.css`, the `data-sensitive` attributes in the dashboard widgets, `ui/src/shell/sensitive.test.tsx`.
Revisit when: a widget shows notes, people or sender names (mark them), or the mask needs a per-widget opt-out.
