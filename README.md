# MapHide

MapHide is a lightweight OBS map hider built mainly for dual-PC live streaming setups.

It started as a Rust map hider, but it has grown into a flexible map-hiding tool for any game where streamers need to cover a map, GPS, or similar sensitive screen element. MapHide runs on the gaming PC, listens for your selected keybind, then tells OBS on the streaming PC to show or hide your map-hiding overlay source.

## Demo

Watch MapHide in action here:

[![MapHide Demo Video](https://img.youtube.com/vi/zBLLD3BhpmE/maxresdefault.jpg)](https://www.youtube.com/watch?v=zBLLD3BhpmE)

## Important Setup Note

For a normal dual-PC setup:

- **Gaming PC**: install and run MapHide here
- **Streaming PC**: run OBS here and enable OBS WebSocket here

MapHide is usually **not** meant to run on the streaming PC in a dual-PC setup. The gaming PC is the machine that detects your key press, then sends the command over your local network to OBS on the streaming PC.

## Features

- Lightweight Windows desktop app
- Flexible map/privacy overlay control for many games
- Built for dual-PC OBS workflows
- Works through OBS WebSocket
- Automatically follows the current OBS program scene
- Controls the same source name across multiple OBS scenes
- Hold mode for games where the map is only open while holding a key
- Toggle mode for games where the map opens and closes with key presses
- Configurable hide delay slider to reduce brief map flashes during close animations
- Configurable keybinds
- Auto-connect on startup option
- Hide-to-tray behavior with tray menu
- Dark mode UI
- Sensitive OBS fields hidden by default
- Reset defaults button with double-click confirmation
- Settings saved to the user's AppData folder

## Keybind Support

MapHide keeps keybind support intentionally simple for reliability.

- **Hold mode show key**: `A-Z`
- **Toggle mode show key**: `A-Z`
- **Toggle mode hide key**: `A-Z`, `Esc`, `Shift`, or `Shift + A-Z`

The hide key supports `Esc` and `Shift + letter` because some games use one key to open the map and a different key or shortcut to close it. In toggle mode, setting the show key and hide key to the same key makes each press flip the overlay on or off.

## Anti-cheat

MapHide only **reads** global key state through a standard Windows API — the same mechanism many streaming and macro tools use to check whether a key is held. It does not inject keystrokes, hook into the game, read or write game memory, or touch any game files.

It is an unsigned executable that polls the keyboard continuously, which is behavior a kernel-level anti-cheat could in principle treat as suspicious. Using it is at your own discretion.

## Requirements

- Windows
- OBS Studio on the streaming PC
- OBS WebSocket enabled on the streaming PC
- A source in OBS that you want MapHide to show and hide
- Both PCs on the same local network

OBS WebSocket is built into modern OBS Studio versions, so most users do not need to install a separate WebSocket plugin.

## Dual-PC Setup Guide

### 1. Streaming PC: Enable OBS WebSocket

On the **streaming PC**:

1. Open OBS Studio.
2. Go to `Tools > obs-websocket Settings`.
3. Enable the WebSocket server.
4. Confirm the server port.
5. The default OBS WebSocket port is usually `4455`.
6. Set or confirm the WebSocket password — ideally one you do not use anywhere else.
7. Apply/save the OBS WebSocket settings.

### 2. Streaming PC: Create The Overlay Source

On the **streaming PC**:

1. In OBS, create or add the source you want MapHide to control.
2. Name the source something easy to type exactly, such as `MapHide Overlay`.
3. Add that same source name to every scene where you want MapHide to work.
4. Make sure the source can cover the map area correctly.

If you need overlay assets, you can create your own or use community-made overlays. One useful source is [Sendox on YouTube](https://www.youtube.com/@sendox).

### 3. Streaming PC: Find The Local IP Address

On the **streaming PC**:

1. Open Command Prompt or PowerShell.
2. Run:

```powershell
ipconfig
```

3. Look for the local IPv4 address on your active network adapter.

Example:

```text
IPv4 Address . . . . . . . . . . : YOUR_STREAMING_PC_IP
```

This local IP address is what MapHide should connect to from the gaming PC.

### 4. Streaming PC: Allow OBS Through Windows Firewall

If MapHide cannot connect, Windows Firewall may be blocking OBS WebSocket.

On the **streaming PC**:

1. Open Windows Security.
2. Go to `Firewall & network protection`.
3. Click `Allow an app through firewall`.
4. Make sure OBS Studio is allowed on the network profile you are using.
5. If needed, create an inbound rule for TCP port `4455`.

You usually only need this if both PCs are on the same network, the password is correct, and MapHide still cannot connect.

### 5. Gaming PC: Configure MapHide

On the **gaming PC**:

1. Download and run MapHide.
2. Click `Settings >`.
3. Enter the streaming PC OBS details:
   - **Host**: the streaming PC local IP address
   - **Port**: the OBS WebSocket port, usually `4455`
   - **Password**: the OBS WebSocket password
   - **Source Name**: the exact OBS source name from the streaming PC
4. Choose your keybind mode:
   - Use **hold mode** if your game map is open only while holding a key.
   - Use **toggle mode** if your game map opens and closes with key presses.
5. Adjust the hide delay if needed.
6. Click `Save Settings`.
7. Click `Start`.

### 6. Test The Setup

After clicking `Start`:

1. Open the game on the gaming PC.
2. Open OBS on the streaming PC.
3. Switch between OBS scenes that contain the same overlay source name.
4. Press your selected map keybind.
5. Confirm the overlay appears and hides correctly in OBS.

If the map flashes for a split second when closing, raise the hide delay slightly.

## Config Location

MapHide stores your settings here:

```text
%AppData%\MapHide\config.json
```

Example:

```text
C:\Users\YourName\AppData\Roaming\MapHide\config.json
```

You never need to edit this by hand — MapHide writes it when you click `Save Settings`. If you want to start over, use `Reset Defaults` in the settings panel.

This file is plain text, and that includes your OBS WebSocket password — any program running as your Windows user can read it (OBS stores its own copy the same way). The MapHide-to-OBS connection also crosses your local network unencrypted. For both reasons, use a WebSocket password that you do not reuse anywhere else.

## Debug Log

If MapHide is misbehaving and you want to report it, tick **Write a debug log to the config folder** in the settings panel and reproduce the problem. MapHide then writes what it is doing — connecting, scene changes, show and hide actions, and errors — to:

```text
%AppData%\MapHide\maphide-debug.log
```

The log never contains your OBS password. It is off by default, starts fresh each time you open MapHide (the previous two runs are kept next to it as `maphide-debug.1.log` and `maphide-debug.2.log`), and stays small. Untick the box to stop logging.

## Notes

- The OBS host, port, and password are hidden by default in the UI.
- If OBS is closed after MapHide has connected, MapHide will try to reconnect automatically.
- If the initial OBS settings are incorrect, MapHide will wait for you to fix the settings and save again.
- Closing the window hides MapHide to the system tray.
- To fully close MapHide, right-click the tray icon and click `Exit`.
- Windows may show a SmartScreen or "Unknown publisher" warning when opening the app because it is not code-signed. Click `More info`, then `Run anyway`.
- MapHide can work on a single-PC setup, but it is mainly built for dual-PC streaming. For a single-PC workflow, an OBS script may be a simpler option depending on your setup.

## Troubleshooting

### MapHide says it cannot connect to OBS

Check these in order:

1. Make sure MapHide is running on the **gaming PC**.
2. Make sure OBS is running on the **streaming PC**.
3. On the streaming PC, open `Tools > obs-websocket Settings` and confirm:
   - the WebSocket server is enabled
   - the port is correct
   - the password is correct
4. Make sure the host in MapHide is the **streaming PC local IP address**, not:
   - the gaming PC IP
   - `127.0.0.1`
   - a public internet IP
5. Make sure both PCs are on the same local network.
6. Check Windows Defender Firewall on the **streaming PC**.
   - Make sure OBS Studio is allowed through the firewall on the network profile you are using.
   - If needed, allow inbound TCP traffic on the OBS WebSocket port, usually `4455`.

### MapHide connects, but nothing happens in OBS

Check that:

- The source name matches exactly
- The source exists in the active OBS scene
- The source exists in every scene you want MapHide to follow
- You entered the source name from OBS on the streaming PC
- The correct keybind mode is selected
- The keybind was saved after changing it

### The overlay disappears too fast

Increase the hide delay slider slightly, then click `Save Settings`.

### The overlay stays on screen too long

Lower the hide delay slider slightly, then click `Save Settings`.

### The app closes when I click the X

This is normal behavior. MapHide hides to the system tray instead of fully closing. Use the tray icon menu and click `Exit` to close it fully.

## Version

Current release: `v0.2.5`

## Credits

Created by Color Dumper.
