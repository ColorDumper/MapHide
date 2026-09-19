# Changelog

All notable changes to MapHide are documented here.

## Unreleased

- Added a guard against two copies of MapHide running at once. Launching it
  again while it's already running just brings the existing window (or its
  "already running" notice) to the front instead of starting a second copy.
- Added an "Auto reconnect" toggle in the settings panel.
- Added a warning icon next to the Password field when it's empty, since an
  OBS WebSocket server without a password lets anyone on your network
  control it.
- Fixed the overlay sometimes staying visible in OBS after closing MapHide
  (or pressing Ctrl+C in headless mode) when the source lived in more than
  one scene. MapHide now waits for it to actually finish hiding everywhere
  before exiting.
- Fixed a hide that was still counting down (waiting out the hide delay)
  being lost if the OBS connection dropped at that moment - it now still
  lands once reconnected.
- Fixed toggle mode occasionally firing an extra, unwanted toggle right
  after a reconnect, or while a key was being held down.
- Fixed a quick key tap sometimes being missed if it happened while MapHide
  was mid-request to OBS.
- Fixed Stop not taking effect immediately if MapHide was in the middle of
  waiting to retry a dropped OBS connection.
- MapHide now retries its very first connection attempt, not just later
  ones, when OBS simply isn't open yet instead of giving up.
- Fixed a deleted or renamed OBS scene sometimes disconnecting MapHide
  entirely instead of just being dropped from what it tracks.
- MapHide now notices if you add the overlay source to your current scene,
  without needing to switch away and back.
- Hotkey toggles stay fast and flicker-free with many OBS scenes: each
  scene's state is now tracked individually, so only the active scene needs
  a write on a toggle, and the rest catch up quietly in the background.
- The debug log now records your active settings at startup (except the
  password and OBS address), and reports if it failed to start instead of
  staying silent.
- Reworked the in-app history log, fixed the live status line flickering,
  tidied up window sizing, and brought back the footer watermark.
- Further internal cleanup, with no other change to how MapHide works.

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
