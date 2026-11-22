# Button pad (XPPen ACK05 or any key-sending pad)

Program each button/dial action in the XPPen driver to send the key below (F13-F24 and Pause are unused by other software). Change any of them in `config.json`: `{"pad": {"keys": {"b2": "f5"}}}`. Open the live map from the tray: **Pad map (second monitor)** (opens on monitor 2, maximized; F11 / double-click = fullscreen; `pad.map_monitor` selects the screen).

| Input | Key to send | Action (all local, no API) |
|---|---|---|
| K1 | F13 | Voice, hold to talk |
| K2 | F14 | Undo (Redo while K7 held) |
| K3 | F15 | That was WRONG: saves feedback on the last voice command (see below) |
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

## Feedback (K3)
Press K3 (or tray > "Last command was wrong") right after a voice command misbehaves. It saves to `data/feedback/feedback.jsonl`: what was heard, how it was routed (local/shortcut/claude), the actions sent, Live's state before and at feedback time, the last 40 log lines and a screenshot. No explanation needed.

Immediate effect: that phrase is remembered as wrong. Next time you say it, the local router is skipped and Claude gets the phrase with a hint that the earlier interpretation was wrong (needs the API key). Claude can't change the code; permanent fixes (router rules, prompt changes) happen when feedback is reviewed in a Claude Code session and shipped as a release. Say "review feedback" there.
