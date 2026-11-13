# 0395. Chat, History, Focus and Settings are placeholder pages until their cards land

Status: accepted

Context: Card S1 adds the routes before the pages exist, and says not to build them.
Decision: `/chat`, `/history`, `/focus` and `/settings` render `PlaceholderPage`: an `<h1>` with the page name and one line, "<Name> is coming soon." No controls, no fetches, nothing that looks like a working feature.
Alternative: Leave the rail items out until the pages exist (rejected: the rail's shape is the point of the card). Disable the links (rejected: a disabled link is dropped from the tab order and gives no reason).
Reason: Honest, reachable routes that later cards replace one by one.
Where: `ui/src/shell/pages.tsx`, `ui/src/router.tsx`.
Revisit when: each page's card lands; replace its route component and delete its placeholder use.
