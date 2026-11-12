# Command Center — Design Spec

Nov 12, 2026 · @Caden

## Tokens

Dark is the default; light is a cool-white variant. Every value ships as a CSS variable and in `tokens.json`. Palettes are user-pickable later; this is the default only.

| Token | Dark | Light |
| --- | --- | --- |
| Backdrop | #07090D with blue, teal and violet orbs | #EEF3F9 with the same orbs, lighter |
| Glass surface | rgba(12,17,25,0.46), blur 18px, saturate 1.4 | rgba(255,255,255,0.68), same blur |
| Text / text 2 / text 3 | #F2F6FB / #B4C0D0 / #8E9DB2 | #0E1622 / #3F4E62 / #566579 |
| Ice (signature) | #8FD3FF | #0A64B0 |
| Edge highlight / hairline | white 28% / white 10% | white 95% / navy 12% |
| Overdue | #FF9AA6 | #B4233C |

- **Source colors (user-assignable):** violet, rose, teal, amber, sky, silver, green, pink. Each has a bright glow value and a darker ink value for labels, so text stays AA in both themes. Defaults: Calendar violet, Canvas rose, LearningSuite teal, Gmail amber, Weather sky, My tasks silver.
- **Priority 1 to 10:** #34C17C, #62C76C, #93CD5E, #BFCF52, #E3C94A, #F2B844, #F69F42, #F58545, #F26A52, #EF4B5C. Text on the pill is always #0A0D12 and the number is always printed.
- **Type:** Sora (self-hosted) for headings, times, pills and badges, with tabular figures. System font for body. Base 14px; text scales 85% to 150%.
- **Shape:** widget radius 18px, controls 10px, chips 8px, pill 11px, calendar blocks 4px. Click targets 32px, except calendar chips (24px) and small buttons (28px).
- **Glow:** inset 1px ring at 42% of the source color, plus outer shadows of 22px at 36% and 64px at 18%, all multiplied by the glow setting (0 to 1.6). Combined widgets blend their sources' colors, one per corner, with an ice ring.
- **Density:** rows 3.1rem comfortable, 2.5rem compact.

## Layout

One window: a transparent unified titlebar, a slim left rail, and a snap grid of widgets under a pinned summary.

- **Titlebar (52px, vibrancy):** sidebar toggle, logo and wordmark, dashboard tabs (Main, School, Work, Calendar, then + for a new dashboard from a template), Now / Next strip, quick capture (⌘K), Done today, Display, Edit. Now / Next hides first when the window narrows.
- **Left rail (76px, collapsible):** Today, Chat, History, Focus at the top; Privacy and Settings at the bottom. "Design rules" is a prototype-only reference page and does not ship. Icons always carry a label.
- **Grid:** 12 columns on a full window, 8 or 4 on smaller ones (smart scale). Row unit 40px, gap 14px. Manual zoom of the whole grid from 70% to 130%.
- **Placement:** widgets auto-arrange with even spacing by default. The user can move any widget freely; a dropped widget can be pinned to its cell, and unpinned widgets flow around pinned ones. The prototype packs by order only; pinning is for the app.
- **Edit mode:** entered with Edit. Drag a header to move, an edge or corner to resize, S / M / L for presets, Remove per widget. Add widget opens the gallery (grouped Overview, Tasks, Events, Other) with source colors. Layouts saves, applies, deletes and exports as JSON. Undo, redo and reset cover every layout change.
- **Calendar tab:** day, week and month views of every source. Events sit on a 7 AM to midnight time grid; tasks and owed replies sit in a Due lane on their day. Selecting an item opens a details panel with notes and actions.
- **Quick capture:** title, date and time together, from fields or typed into the title ("Read ch. 5 Friday 4pm"). Typed values win over the fields.
- **First run:** three steps (template, sources, ready). Any source can be skipped. Main is applied when setup finishes.
- **Conventions:** 12-hour clock, week starts Sunday, overdue pinned first, then soonest; "soon" is the next 48 hours.

## Widget anatomy

Every widget is the same glass shell: header, scrolling body, footer.

- **Header (44px):** source dot, title in Sora, then a quiet status on the right (last synced or source list). In edit mode the status becomes a tier badge such as "W2 · H3 · 5×10".
- **Body:** rows separated by hairlines; group labels (Overdue, Today, Tomorrow, then dates) in small caps.
- **Footer:** last synced on the left, a count on the right ("4 more", "13 open").
- **Task row:** check-off (16px rounded square), title, source and due time, estimate chip, priority pill, expand arrow, link icon that opens the source in a new tab.
- **Event row:** start time in Sora, title, end time and location, calendar chip, expand arrow, link icon. The current event shows a "Now" chip.
- **Expanded item:** grows in place. Holds an editable Notes field, "Why is this a 9?" with each reason and its points, the estimate in minutes, Snooze, and for owed emails an editable draft reply that is never sent automatically.
- **Estimate chip:** filled when set; "+ Add estimate" when empty; dashed outline with a confidence dot when AI-suggested (setting, off by default). Typed numbers are never overwritten.
- **Kinds:** a widget merges sources of one kind only (tasks with tasks, events with events). Owed replies count as tasks when their toggle is on. Needs me is the only cross-kind widget and ranks by the explainable urgency score. Weather, Summary and This week are their own kinds.
- **Summary:** pinned above the grid, collapsible.
- **Shared undo toast:** one toast for check-off, snooze, added tasks and layout edits. After a check-off with an estimate it also asks "It took: Shorter / About right / Longer".

## Size rules

Width and height tiers are independent, so one rule set per widget gives all nine combinations. Tiers are set by grid cells, not pixels.

| Widget | Min | Max | W1 / W2 / W3 (columns) | H1 / H2 / H3 (rows) |
| --- | --- | --- | --- | --- |
| Needs me, Tasks, Events, Canvas, LearningSuite, Owed replies, My tasks | 3×5 | 12×16 | 1–3 / 4–6 / 7+ | 1–5 / 6–9 / 10+ |
| This week | 3×4 | 12×10 | 1–3 / 4–6 / 7+ | 1–4 / 5–7 / 8+ |
| Weather | 2×3 | 6×9 | 1–2 / 3–4 / 5+ | 1–4 / 5–6 / 7+ |

| Tier | Tasks shows | Events shows |
| --- | --- | --- |
| W1 narrow | Title and priority pill | Start time and title |
| W2 standard | Adds source, due time, estimate chip | Adds end time and location |
| W3 wide | Adds notes preview and inline actions | Adds calendar name and a day strip |
| H1 short | Top 3 and "N more" | Now and next |
| H2 medium | Up to 6, grouped by day | The rest of today |
| H3 tall | Full list and a workload bar | All of today, tomorrow, free time |

Size presets: S 3×5, M 4×8, L 7×10, clamped to each widget's min and max. Open question: at W3 + H1 the notes preview makes rows taller, so about 2.5 rows show instead of 3.

## States

Each widget handles its own state, so one failing source never blanks the dashboard.

| State | What the widget shows |
| --- | --- |
| Loading | Three shimmer bars in place of rows |
| Empty | "All clear. Nothing due." |
| Error | "Can't reach Canvas." in the overdue color, one line on what to check, Retry |
| Stale | Old data stays visible under "Showing older data. Last synced 3 hours ago." with Retry |
| Not connected | "LearningSuite isn't connected yet." with Connect, which opens Setup |

- **Privacy mode:** titles, notes, locations and drafts are replaced by solid bars. Times, counts and pills stay.
- **High contrast:** surfaces turn opaque, blur is removed, hairlines strengthen, and text 3 is raised to text 2.
- **Focus:** hides everything except Needs me and Events.
- **Contrast:** all text meets WCAG AA in both themes, including source labels and 11px captions.

## Motion

Motion is short and confirms an action; nothing loops except the loading shimmer.

- **Durations:** 140ms for hover and press, 240ms for toasts and panels, 420ms for check-off. Easing is cubic-bezier(.2, .8, .2, 1).
- **Check-off:** the box fills ice blue, the check appears, the box pulses to 106% with a soft ring, the title strikes through, then the row leaves after about 460ms.
- **Drag (for the app):** a picked-up widget lifts with a short ease and shows a snapped drop outline; neighbours slide aside over 240ms instead of jumping. The prototype swaps instantly.
- **Reduced motion:** with prefers-reduced-motion, all animation and transitions are off and check-off is immediate.

## Chat, History, Settings

Three rail screens share one centered column (900px max) in the same glass language.

- **Chat:** the AI assistant. Header shows the active provider with a Change link to Settings. Assistant answers are short text followed by the real item rows they refer to, so check-off, snooze, notes and drafts work inside the conversation. A composer sits at the bottom with suggested prompts above it. The assistant reads items and suggests actions; it never sends email or changes a source. With no provider chosen, the composer is replaced by a prompt to open Settings.
- **History:** a ledger of completed and dismissed items, grouped by day, newest first. Each day shows counts and total estimated time. Rows show source, time, estimate and a Done or Dismissed chip; today's items can be restored. Search and All / Done / Dismissed filters sit in the header. Dismiss is a new action beside Snooze in an expanded item.
- **Settings:** a section list on the left, one card on the right.
  - Appearance: theme, glow, font size (85% to 150%), compact rows, high contrast. The titlebar Display menu stays as a shortcut to the same values.
  - AI: provider (Off, Ollama on this Mac, Gemini, OpenAI-compatible) with only that provider's fields, then opt-in toggles for daily summary, draft replies and suggested estimates. All are off by default, and a line states what a cloud provider receives.
  - Paired devices: this Mac, paired devices with Unpair, and Pair a device, which shows a six-digit code that expires in 10 minutes.
  - Sources: status and last sync per source, Connect or Disconnect, the owed-replies-as-tasks toggle, and a link back into Setup.

## Later

These are specified by the brief but not in the [prototype](https://claude.ai/artifact/7qyjWjjwU1fsEXZtFCXCgS) yet.

| Item | Intent |
| --- | --- |
| Plan my day (later) | Ghost blocks on the timeline proposing when to do today's tasks; nothing is scheduled until confirmed |
| Per-source trust drawer (later) | What each source can read, when it last synced, and a disconnect control |
| Free placement and pinning | As described under Layout and Motion |
| Time-blocking | Drag a task onto the calendar grid to block time; undo through the shared toast |
| Command palette | ⌘K grows from quick capture into search and commands |
| Shortcut hints | Togglable, never covering content |
| End-of-day wrap-up | Review of done, snoozed and carried-over items |
| Notifications | In-app and macOS, with quiet hours |
| Menu-bar mini view | Now / Next and the top of Needs me |
| AI-suggested estimates | Shown only as a sample chip today |
| Gmail client ID step | Setup shows a plain Google sign-in; the build uses a bring-your-own client |
| Persistence | Source colors, new dashboards and connections reset on reload in the prototype |
| More sources and platforms | Stocks, Outlook, user-pickable palettes, then a simplified iPhone layout from the same tokens |

Not in scope: keyboard-first email triage.
