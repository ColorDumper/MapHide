# Changelog

All notable changes to MapHide are documented here.

## v0.2.3 - 2026-08-27

- Reworked packaging to improve compatibility and reduce antivirus false
  positives. MapHide now ships as a folder (run `MapHide.exe` inside it)
  rather than a single executable.
- Added version information to the executable.
- Fixed icon and image loading in the packaged build.
- No changes to map hiding, keybinds, or OBS control.

## v0.2.2 - 2026-04-21

- Hide key now also accepts `Esc`, for games that close the map with the
  Escape key.
- Internal key-handling cleanup (special-keysym mapping, standalone
  hide-key handling).
- README wording updates.

## v0.2.1 - 2026-04-21

- Added dedicated application icons for the window, tray, and runtime,
  loaded from a new `assets/` folder; refreshed `MapHide.ico`.
- Same-key toggle support: in toggle mode, pressing the same key for show
  and hide now alternates the overlay instead of being rejected.
- Removed the restriction that the show key and hide key must differ in
  toggle mode.
- Footer watermark now auto-crops transparent padding before scaling.
- Consolidated status and help text.

## v0.2.0 - 2026-04-21

- Added toggle mode (separate show and hide keys) alongside the original
  hold mode.
- Added an in-app settings panel with configurable keybinds and a
  click-to-capture key picker.
- Added a configurable hide-delay slider, replacing the fixed delay
  constant.
- Added an "auto connect on startup" option.
- OBS host, port, and password fields are now masked by default, each with
  its own "Show" toggle.
- Added "Reset Defaults" with a double-click confirmation.
- Dark-themed UI overhaul.
- Expanded the README setup guide; added the demo video and thumbnail.

## v0.1.1 - 2026-04-07

- Added a hide delay before hiding the overlay on key release, to prevent
  the map briefly flashing during close animations.
- Fixed restoring the window from a minimized (iconified) state via the
  tray icon; previously only restoring from a hidden state worked.

## v0.1.0 - 2026-04-07

- Initial public release.
- GUI and headless (`--headless`) modes.
- Controls an OBS source over OBS WebSocket v5 for dual-PC streaming
  setups: hold a key on the gaming PC to show or hide a map-hiding overlay
  in OBS on the streaming PC.
- Follows the active OBS program scene and controls the same source name
  across scenes.
- Automatic reconnect if OBS becomes unavailable.
- System-tray icon with hide-to-tray behavior.
- Settings stored in `%AppData%\MapHide\config.json`.
