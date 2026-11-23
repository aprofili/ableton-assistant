# Button pad (XPPen ACK05 or any key-sending pad)

Program each button/dial action in the XPPen driver to send the combo below (Ctrl+Alt+Shift + a function key: nothing else uses these; single keys like `f20` also work). Change any of them in `config.json`: `{"pad": {"keys": {"b2": "ctrl+alt+shift+f5"}}}`. Open the live map from the tray: **Pad map (second monitor)** (opens on monitor 2, maximized; F11 / double-click = fullscreen; `pad.map_monitor` selects the screen).

| Input | Key to send | Action | With MOD (K3) held |
|---|---|---|---|
| K1 | Ctrl+Alt+Shift+F1 | Voice, hold to talk | That was WRONG (saves feedback, see below) |
| K2 | Ctrl+Alt+Shift+F2 | Tap tempo | Capture MIDI |
| K3 | Ctrl+Alt+Shift+F3 | **MOD**: hold it to change what the other inputs do | |
| K4 (tall) | Ctrl+Alt+Shift+F4 | Record (arrangement) on/off | Session record on/off |
| K5 | Ctrl+Alt+Shift+F5 | Metronome toggle | Count-in on/off (1 bar) |
| K6 | Ctrl+Alt+Shift+F6 | Loop toggle | Punch cycle: in on, out on, in off, out off |
| K7 (tall) | Ctrl+Alt+Shift+F7 | Session / Arrangement view (Tab) | Clip / Device detail view (Shift+Tab) |
| K8 | Ctrl+Alt+Shift+F8 | Previous section marker | Undo |
| K9 (wide) | Ctrl+Alt+Shift+F9 | Play / Stop (plays from the start marker) | Continue from where it stopped |
| K10 | Ctrl+Alt+Shift+F10 | Next section marker | Redo |
| Dial clockwise | Ctrl+Alt+Shift+F11 | Scroll right | Scroll down |
| Dial counter-clockwise | Ctrl+Alt+Shift+F12 | Scroll left | Scroll up |
| Dial press | (not programmable on the ACK05 driver) | none | |

Layout (reading order):
```
[K1][K2][K3][ K4 ]
[K5][K6][K7][tall]
[K8][ K9  ][K10]
```
Notes: pressing any button while Live isn't in front brings Live forward, then runs the action (`pad.focus_mode`: `focus_and_act` default; `focus_only` makes that first press only focus Live). Set the dial to send one key per click. Scrolling sends mouse-wheel events to Live and moves the cursor onto Live's window if it isn't already over it (`pad.auto_hover`). Turning faster scrolls faster. K1 is added as an extra voice trigger alongside the main trigger key (it does not fire while MOD is held). The pad map reopens automatically if it was open when the assistant last ran.

## Feedback (MOD+K1)
Hold MOD and press K1 (or tray > "Last command was wrong") right after a voice command misbehaves. It saves to `data/feedback/feedback.jsonl`: what was heard, how it was routed (local/shortcut/claude), the actions sent, Live's state before and at feedback time, the last 40 log lines and a screenshot. No explanation needed.

Immediate effect: that phrase is remembered as wrong. Next time you say it, the local router is skipped and Claude gets the phrase with a hint that the earlier interpretation was wrong (needs the API key). Claude can't change the code; permanent fixes (router rules, prompt changes) happen when feedback is reviewed in a Claude Code session and shipped as a release. Say "review feedback" there.
