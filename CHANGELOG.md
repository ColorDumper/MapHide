# Changelog

All notable changes to MapHide are documented here.

## v0.2.5 - 2026-09-05

- The title bar is now dark to match the rest of the window, and the window
  no longer flashes white for a moment when it opens or when you restore it
  from the tray.
- When the streaming PC stops responding mid-session, MapHide now notices in
  about a second instead of three and reconnects that much sooner.
- Added an optional debug log. Tick "Write a debug log to the config folder"
  in the settings panel before reproducing a problem, and MapHide records what
  it is doing to a file next to your settings. It is off by default and never
  includes your OBS password.
- A settings file with an out-of-range port or hide delay, or a keybind
  MapHide cannot use, is now corrected when it loads instead of causing errors.
- Updated bundled third-party components.
- Further internal cleanup, with no change to how MapHide works.

## v0.2.4 - 2026-09-04

- Fixed the overlay staying on screen after the connection to OBS dropped.
  MapHide now sets the source to match your keybind every time it connects,
  so a lost connection no longer leaves the map covered.
- Fixed the overlay being left visible in a scene after switching away from
  it, and coming back visible after OBS restarts.
- Fixed the overlay flickering during scene transitions. The source is now
  kept in step in every scene that contains it, so changing scenes needs no
  work and never catches the incoming scene uncovered.
- Fixed toggle mode when one key both shows and hides: pressing it quickly
  could finish with the map open and the overlay already gone.
- Fixed the Start and Stop buttons showing the wrong state after saving
  settings while MapHide was running.
- Fixed the taskbar icon, which was blurry and briefly showed a placeholder
  on first launch.
- A connection that drops mid-session is now reported as a lost connection
  rather than as an OBS error.
- Redrew the footer mark at the size it is shown at, and trimmed unused
  space from the bottom and right of the settings window.
- Fixed headless mode (`--headless`) exiting with an error half a second
  after starting, instead of running until you stop it.
- A large internal cleanup. Nothing about how MapHide works has changed.

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
- README wording updates.

## v0.2.1 - 2026-04-21

- Added proper application icons for the window and the system tray.
- Same-key toggle support: in toggle mode, pressing the same key for show
  and hide now alternates the overlay instead of being rejected.
- Removed the restriction that the show key and hide key must differ in
  toggle mode.
- Consolidated status and help text.

## v0.2.0 - 2026-04-21

- Added toggle mode (separate show and hide keys) alongside the original
  hold mode.
- Added an in-app settings panel with configurable keybinds and a
  click-to-capture key picker.
- Added a configurable hide-delay slider; the delay was previously fixed.
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
