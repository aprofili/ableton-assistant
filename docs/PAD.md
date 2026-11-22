# Button pad (XPPen ACK05 or any key-sending pad)

Program each button/dial action in the XPPen driver to send the key below (F13-F24 and Pause are unused by other software). Change any of them in `config.json`: `{"pad": {"keys": {"b2": "f5"}}}`. Open the live map from the tray: **Pad map (second monitor)** (opens on monitor 2, maximized; F11 / double-click = fullscreen; `pad.map_monitor` selects the screen).

| Input | Key to send | Action (all local, no API) |
|---|---|---|
| K1 | F13 | Voice, hold to talk |
| K2 | F14 | Undo |
| K3 | F15 | Redo |
| K4 (tall) | F16 | Record on/off (shows "Stop recording" while recording) |
| K5 | F17 | Metronome toggle (shows ON/OFF) |
| K6 | F18 | Loop toggle (shows ON/OFF) |
| K7 | F19 | Hold: dial scrolls vertically instead of horizontally |
| K8 | F20 | Previous section marker |
| K9 (wide) | F21 | Play / Pause (one button; label follows transport) |
| K10 | F22 | Next section marker |
| Dial clockwise | F23 | Scroll right (down while K7 held) |
| Dial counter-clockwise | F24 | Scroll left (up while K7 held) |
| Dial press | Pause | Go to start |

Layout (reading order):
```
[K1][K2][K3][ K4 ]
[K5][K6][K7][tall]
[K8][ K9  ][K10]
```
Notes: set the dial to send one key per click. Scrolling sends mouse-wheel events to Live and moves the cursor onto Live's window if it isn't already over it (`pad.auto_hover`). Turning faster scrolls faster. K1 is added as an extra voice trigger alongside the main trigger key.
