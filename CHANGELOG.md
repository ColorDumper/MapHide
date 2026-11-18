# Changelog

All notable changes to MapHide are documented here.

## [v0.3.0](https://github.com/ColorDumper/MapHide/compare/v0.2.6...v0.3.0) - 2026-11-13

### Added

- Added a map preview to the main screen that shows whether your map is covered. Its animation pauses while another window is in front, so MapHide uses no extra CPU while you play. ([449c02f](https://github.com/ColorDumper/MapHide/commit/449c02fd25fdf81d93208e261ae2ab8ec3aeaea6), [c811908](https://github.com/ColorDumper/MapHide/commit/c8119085f4ca765ea471c5e4e701e041889a5dbf))
- Added the live OBS scene and your key mode to the top of the main screen. ([449c02f](https://github.com/ColorDumper/MapHide/commit/449c02fd25fdf81d93208e261ae2ab8ec3aeaea6), [c811908](https://github.com/ColorDumper/MapHide/commit/c8119085f4ca765ea471c5e4e701e041889a5dbf), [f49923f](https://github.com/ColorDumper/MapHide/commit/f49923f9293d886ec3988a8848a156be13a4a6c0))
- Added a field log to the main screen: a short running record of what MapHide is doing. It never shows your OBS address. ([95d742e](https://github.com/ColorDumper/MapHide/commit/95d742e8bea53810f90f84a18808406652ee0fb9), [c811908](https://github.com/ColorDumper/MapHide/commit/c8119085f4ca765ea471c5e4e701e041889a5dbf))
- Added a test button to the main screen that shows and hides the overlay the same way your key does. ([06e00ff](https://github.com/ColorDumper/MapHide/commit/06e00ff5bf5c5d0c43742a6b907c46b0279612af), [c811908](https://github.com/ColorDumper/MapHide/commit/c8119085f4ca765ea471c5e4e701e041889a5dbf))
- Added a Test Link button to Settings, which checks your OBS details without starting MapHide. ([9e49069](https://github.com/ColorDumper/MapHide/commit/9e490693e007e7373e9127b26e7e57616f7e8c57), [5c4bcb6](https://github.com/ColorDumper/MapHide/commit/5c4bcb678d019823ab014230ab198e33662ad30c))
- Added the number of scenes that carry your overlay source to Settings, shown after Test Link or while connected. ([449c02f](https://github.com/ColorDumper/MapHide/commit/449c02fd25fdf81d93208e261ae2ab8ec3aeaea6), [9e49069](https://github.com/ColorDumper/MapHide/commit/9e490693e007e7373e9127b26e7e57616f7e8c57), [5c4bcb6](https://github.com/ColorDumper/MapHide/commit/5c4bcb678d019823ab014230ab198e33662ad30c))
- Added two themes, Field and Legacy (the previous colors), chosen in Settings. ([f3a99ad](https://github.com/ColorDumper/MapHide/commit/f3a99ad6292374a606bb20b190a31c727fb85627), [5c4bcb6](https://github.com/ColorDumper/MapHide/commit/5c4bcb678d019823ab014230ab198e33662ad30c))
- Added a link to MapHide's GitHub page in Settings, under About. ([5c4bcb6](https://github.com/ColorDumper/MapHide/commit/5c4bcb678d019823ab014230ab198e33662ad30c))
- Added Enter and Esc as ways to finish typing in a text field. ([410d17f](https://github.com/ColorDumper/MapHide/commit/410d17fc8b96cb4143e2d3e663fc7e88a07e5c1f))
- Added `MapHide.exe --quit`, which closes a running MapHide the same way Exit in the tray does. ([af37dce](https://github.com/ColorDumper/MapHide/commit/af37dceca8bc34aa8581a9892c3307c0e95b20aa))
- Added an installer, which adds MapHide to the Start menu and to Installed apps in Windows. Uninstalling asks whether to keep your settings. ([aeb5392](https://github.com/ColorDumper/MapHide/commit/aeb539254f26d2de7f3bed2cdfabd8b20b531218))
- Added a Check for updates button under About in Settings. When a new version is out, Update installs it and reopens MapHide with your settings kept. ([9879289](https://github.com/ColorDumper/MapHide/commit/987928959735c560d70381d3c02b0ef3704c0383))
- Added a Check for updates switch under Behavior in Settings, on by default, which looks for a new version when MapHide opens. The field log says when one is out. ([9879289](https://github.com/ColorDumper/MapHide/commit/987928959735c560d70381d3c02b0ef3704c0383))
- Added a warning when you click Reset while MapHide is running, saying that Reset disconnects MapHide from OBS. ([048d310](https://github.com/ColorDumper/MapHide/commit/048d310dd2fa9fa3ed25c4e7e83ed216459b4ccd))

### Changed

- Changed the app icon to a map with a red X, sharp at every size from the tray to the taskbar. ([2407583](https://github.com/ColorDumper/MapHide/commit/2407583c7106298bbbadeb9778670cf8824b5c24))
- Changed the window to a new design with new fonts. Settings now open over the main screen instead of widening the window. ([348c7b8](https://github.com/ColorDumper/MapHide/commit/348c7b850fb8b3438f5c5740c5c6b852967097df), [c811908](https://github.com/ColorDumper/MapHide/commit/c8119085f4ca765ea471c5e4e701e041889a5dbf), [5c4bcb6](https://github.com/ColorDumper/MapHide/commit/5c4bcb678d019823ab014230ab198e33662ad30c), [4da7733](https://github.com/ColorDumper/MapHide/commit/4da7733890d7fcbf94c4032ed257fab91c1e59e1))
- Changed the empty-password warning to text next to the Password field instead of an icon. ([5c4bcb6](https://github.com/ColorDumper/MapHide/commit/5c4bcb678d019823ab014230ab198e33662ad30c))
- Changed the debug log option to a switch under Behavior in Settings. ([5c4bcb6](https://github.com/ColorDumper/MapHide/commit/5c4bcb678d019823ab014230ab198e33662ad30c))
- Changed the download size to about 27 MB for the installer, or 35 MB for the zip, because of the new window. ([4da7733](https://github.com/ColorDumper/MapHide/commit/4da7733890d7fcbf94c4032ed257fab91c1e59e1), [aeb5392](https://github.com/ColorDumper/MapHide/commit/aeb539254f26d2de7f3bed2cdfabd8b20b531218))
- Changed launching MapHide while it's already running to bring the open window to the front, even from the tray, instead of showing a notice. ([af37dce](https://github.com/ColorDumper/MapHide/commit/af37dceca8bc34aa8581a9892c3307c0e95b20aa), [05c300a](https://github.com/ColorDumper/MapHide/commit/05c300ae686152b909bbdaa5f58c5295c99b079d))
- Changed Settings so only Save keeps a change: closing Settings without Save puts your saved settings back, and Start uses your saved settings instead of saving what's in Settings. Settings shows Unsaved changes while you have any. ([2358b43](https://github.com/ColorDumper/MapHide/commit/2358b4335aa386231aca58623028f00d414de6ac))
- Changed Host, Port and Password to hide again whenever you close Settings or MapHide goes to the tray, so they never stay shown on stream. ([3573b98](https://github.com/ColorDumper/MapHide/commit/3573b9829341115610980b96d2b1e9b6cee0c048))

### Fixed

- Fixed MapHide staying open in the background for several seconds, without hiding the overlay in OBS, when it was closed right after saving settings while connected. ([25cb0b3](https://github.com/ColorDumper/MapHide/commit/25cb0b3195c7613b974093c630543cf03e395869))
- Fixed changing "Connect on startup", or saving settings that don't affect the overlay, briefly dropping the OBS connection and hiding the overlay. ([1639be2](https://github.com/ColorDumper/MapHide/commit/1639be2e4911c8341da5d1b2a2ef1e0044b997cf))
- Fixed the overlay staying visible in OBS when Windows signed out, restarted or shut down while MapHide was running. ([af37dce](https://github.com/ColorDumper/MapHide/commit/af37dceca8bc34aa8581a9892c3307c0e95b20aa))
- Fixed your settings being lost if the PC crashed or lost power while MapHide was saving them. ([3515bc1](https://github.com/ColorDumper/MapHide/commit/3515bc1de537a7ef9d794a54276d4611e5da70d6))
- Fixed Reset in Settings, while MapHide was running, trying to connect with empty settings and ending on a connection error. Reset now stops MapHide. ([8963d99](https://github.com/ColorDumper/MapHide/commit/8963d99ef2c3a455f31a189fedc3ca55e840f3df))
- Fixed MapHide refusing to open after it was closed, saying it was already running, while an earlier "already running" message was still open. ([05c300a](https://github.com/ColorDumper/MapHide/commit/05c300ae686152b909bbdaa5f58c5295c99b079d))
- Fixed MapHide starting again when you saved settings right after pressing Stop. ([18c5f7c](https://github.com/ColorDumper/MapHide/commit/18c5f7c8622fa6a572a6ccbe76e3dea2e5082eea))
- Fixed MapHide only saying it stopped, when you pressed Stop while it was reconnecting and the overlay might still be showing in OBS. ([2d9c46d](https://github.com/ColorDumper/MapHide/commit/2d9c46d9a1c43cd2a803d364cc61b647de8d6a3b))
- Fixed Settings accepting an OBS port outside 1 to 65535, which could never connect. It now says the port must be in that range. ([96b2c32](https://github.com/ColorDumper/MapHide/commit/96b2c32c9ba6438de5f7e628a80347c1f7b07d67))

## v0.2.6 - 2026-10-27

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
- Fixed MapHide still behaving as if the overlay source existed after the only
  scene containing it was deleted or renamed in OBS.
- Fixed the live status line going on saying "Connected to OBS." for up to a
  second after the connection actually dropped.
- The history log no longer says "Overlay shown." or "Overlay hidden." when
  your current scene doesn't contain the source, since nothing changes there.
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
- Fixed MapHide's timing relying on the computer's clock, so a clock
  correction or the daylight-saving change could stop the overlay hiding or
  stop scene changes being noticed for up to an hour.
- Fixed Start and Stop getting stuck if something went wrong while MapHide
  was hiding the overlay on the way out. It now always finishes stopping, and
  warns you if the overlay may still be showing in OBS.
- Fixed MapHide failing to start if the previous debug log was open in another
  program. It now starts normally and tells you the debug log couldn't be
  started.
- Fixed MapHide stopping for good if OBS sent back a reply it couldn't read.
  It now reconnects and carries on.
- Fixed a slow or timed-out OBS request being reported as a scene having been
  removed. It's now treated as the lost connection it is, and MapHide
  reconnects.
- The debug log is more useful when something goes wrong: it now records what
  kind of failure caused a disconnect and where an unexpected error happened,
  and a long stretch with OBS closed adds one line instead of filling the log
  with retries.
- Error messages in the window no longer include file paths, so a screenshot
  of MapHide doesn't show your Windows user name. The debug log hides your
  user folder too.
- The status line now always shows the real state of the OBS connection.
  Hints and warnings (such as key hints, "OBS Host is required.", or "Key
  selected") appear below the log for a few seconds instead of replacing it,
  so a leftover message can no longer sit there while the connection says
  something different.
- If the connection to OBS drops while the overlay is showing, MapHide now
  tells you the overlay may still be showing in OBS until it reconnects (or
  tells you to check OBS if it stops without reconnecting).
- The history log no longer shows the same error twice when MapHide gives up,
  and the "connection lost" message no longer asks you to reconnect when
  MapHide is already doing it for you.
- Fixed MapHide failing to open, with no message, if the settings file held an
  empty or invalid value (such as a blank port). It now opens with default
  settings instead.
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
