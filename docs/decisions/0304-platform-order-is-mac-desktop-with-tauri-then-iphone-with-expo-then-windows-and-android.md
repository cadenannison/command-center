# 0304. Platform order is Mac desktop with Tauri, then iPhone with Expo, then Windows and Android

Status: accepted

Context: Decision 0001 describes the two modes and 0008 a macOS menu-bar launcher; a separate mobile repo uses /v1. The new UI (decision 0300) should become the desktop app and later the phone app. The order in which platforms are built needs to be written down so the UI is not shaped around the wrong one first.
Decision: Platform order is: (1) the Mac desktop app, wrapping the `ui/` build in Tauri, replacing the rumps menu-bar launcher when it is ready; (2) the iPhone app with Expo (React Native), in the separate mobile repo, sharing the generated typed client and the /v1 contract; (3) Windows and Android afterwards (Tauri for Windows, Expo for Android). No stack change is implied: the web UI stays Vite and React, the API stays FastAPI, and the order says nothing about what is built first inside `ui/`. Each platform gets its own task cards and its own records; this one fixes only the order.
Alternative: iPhone first (rejected: the desktop is where the data is collected and the app is used most; the phone is a view on it). Electron for desktop (rejected for now: much larger and less sandboxed than Tauri; revisit if Tauri blocks a needed capability). A web app only (rejected: no menu-bar presence or local secret access).
Reason: Mac is the daily-use platform and the one already supported by the menu-bar launcher, so a UI that works there delivers value first.
Consequences: Tauri and Expo are not approved dependencies by this record (decision 0301 governs every dependency; each needs its own approval). The UI avoids browser-only assumptions that would not hold inside a Tauri webview, and keeps the CSP of decision 0301 compatible with it.
Where: no code yet. `docs/mobile.md` and `docs/mobile-api-notes.md` describe the phone repo's side.
Revisit when: The Mac desktop task is planned, or a user need moves another platform up.
