# Changelog

## 1.10.2
- Hold+dial now needs the button held for 1 s (`pad.hold_delay`); letting go sooner is a normal tap. Hold labels/icons appear only once it kicks in; no tap on release after a hold. MOD and voice stay immediate.

## 1.10.1
- Pad map icons replaced with Lucide icons (ISC license, docs/LUCIDE_LICENSE.txt), flattened to vectors in assistant/icons_data.py.

## 1.10.0
- Pad map uses vector icons instead of text (mic, record, loop, mute/solo headphones, transport, undo/redo, etc.), drawn in code so they scale. The dial shows one scroll icon (horizontal arrow, vertical with MOD) instead of two labels; while a button is held it shows a short caption (e.g. bar / beat / ±5 BPM). Text remains as a fallback.

## 1.9.2
- Pad map stretches to fill the whole window with auto-sized text (shape is approximate); removed the "(hold)" hints from K1/K3 and "(turn dial)" from hold labels.

## 1.9.1
- K5 = mute selected track, MOD+K5 = solo selected track (popup shows the result). Capture MIDI removed from the pad (still a voice command).

## 1.9.0
- Hold + dial on more buttons (MOD while holding = bigger/finer step): K2 tempo (1 / 5 BPM), K9 playhead (bar / beat), K4 select track, K5 selected-track volume, K7 selected-track pan, K6 move loop, K8 loop start, K10 loop end (bar / beat). A tap still does the button's normal action, on release.
- Pad map shows hold wording only while the button is held (like MOD); the dial labels change too.
- Pad map status is now a green check / red cross in the corner; hint text removed.

## 1.8.1
- K2: tap tempo, hold + dial = tempo, MOD+K2 = metronome toggle. K5 = Capture MIDI. Count-in toggle removed.

## 1.8.0
- Hold K5 + turn the dial = tempo in whole BPM (popup shows it). K5 now toggles the metronome on release, and only if the dial wasn't used. Framework for more hold+dial buttons (`HOLD_SCROLL`).

## 1.7.10
- Reverted default model to small.en (distil-small.en was no faster and less accurate on short commands); loop phrases added to the Whisper prompt.
- Corner popup now also appears for commands handled locally (what was done + what was heard) and for 'Not understood'.

## 1.7.9
- Faster transcription: default model distil-small.en (falls back to small.en if it can't load), CPU threads = physical cores (`whisper.cpu_threads`).

## 1.7.8
- K2 = Tap tempo, MOD+K2 = Capture MIDI.

## 1.7.7
- MOD+K8 = Undo, MOD+K10 = Redo (replacing go to start/end). K2 is now unassigned.

## 1.7.6
- Pad map remembers its window position, size and maximized state across restarts (data/ui_state.json).

## 1.7.5
- Fix the remaining one-time pad map flicker after a press: the action's own state query returned the old value through the push path; pushes are now ignored during the post-press hold and confirmed at 0.75 s.

## 1.7.4
- After dictating to Claude, the chat is kept scrolled to the bottom while the reply streams (stops after `pad.claude_follow_seconds`=240, when you move the mouse, or when another window takes focus; `pad.claude_follow_bottom` to disable).

## 1.7.3
- Fix pad map state flicker (play/pause/play): polled reads no longer overwrite newer pushes or optimistic flips, and the state dict is updated per key instead of replaced.

## 1.7.2
- Dictation to Claude uses its own Whisper prompt (names like Claude, GitHub) instead of the Ableton command prompt.

## 1.7.0
- Driverless pad: the assistant sends the XPPen raw-mode init packet itself (child process, timeout) and re-sends it on reconnect / when the pad is seen in keyboard mode.
- Dial press (or click on the map's dial centre) = talk to Claude: press to record, press again to stop; the transcript is typed into the Claude desktop app and submitted. Config: `pad.claude_exe` (default claude.exe), `pad.claude_submit` (default true).

## 1.6.0
- Pad is read directly from its raw HID reports (no driver key mappings needed): K1-K10, dial press, dial ticks. Driver key combos are ignored while HID reports arrive and used as fallback otherwise.
- Pad map is clickable (MOD toggles on click).

## 1.5.4
- Pad map is clickable: buttons and the dial (left/right half) do the same action as the pad. Clicking MOD toggles it (sticky); the physical pad still uses hold.

## 1.5.3
- Tray menu regrouped: Settings / Updates / Tools submenus; top level keeps Listening, Pad map, Last command wrong, Microphone, Restart, Quit.
- Raw HID tap for the XP-Pen pad (logs/pad_hid.log) as groundwork for bypassing the driver.
- Auto-restart when code files change on disk.
- Scroll burst logging.

## 1.5.2
- Dial scroll behaves like a real wheel: one tick, one notch, no coasting (stale ticks dropped), mild speed-up only on fast spins.
- Each scroll burst focuses Live and parks the cursor on the arrangement/clip area. Config: `pad.scroll_step`, `pad.scroll_max_mult`, `pad.scroll_point`.

## 1.5.1
- Fix: K7 view switch (Tab) did nothing because focusing Live tapped Alt, which opened Live's menu bar and swallowed the key. Focus is now a no-op when Live is already in front and no longer taps Alt first.
- Pad map reacts instantly: Live pushes state changes (AbletonOSC listeners), the display flips optimistically on press, unavailable properties no longer stall polling, redraw only on change.

## 1.5.0
- Learning: when Claude solves a command, the solved example is saved as a template with number/name slots (`data/learned_macros.json`) and runs locally next time ("create a section marker at bar 13 and call it drum loop" -> any bar, any name). "That was wrong" deletes the macro behind a command. Section creation with "and call it ..." is also built into the local router. Claude API timing is logged.
- Pad: any button press brings Live to the front first if it isn't (`pad.focus_mode`: `focus_and_act` default, or `focus_only`).
- Popups (listening, results) now appear bottom-left above the taskbar; `overlay.position` = `bottom_left` or `top_center`.
- Pad: K3 is now a general MOD key. MOD+: K1 wrong, K2 redo, K4 session record, K5 count-in, K6 punch in/out cycle, K7 clip/device view, K8 go to start, K9 continue from stop, K10 go to end, dial scrolls vertically. K7 switches Session/Arrangement; K9 is Play/Stop.
- Pad map: no curved dial arrows; open state persists across restarts.

## 1.4.1
- Pad keys are now Ctrl+Alt+Shift+F1..F12 (single-key remaps still work); modifier-aware matching. Dial press is not programmable on the ACK05 driver.
- Fix: pad modifiers no longer leak into wheel scrolling (Alt+wheel resized tracks).
- Fix: dial scroll lag (window search and SendInput ran on the keyboard hook thread); now queued to a worker, merged, with the Live window cached.
- Pad map redrawn to match the ACK05 shape.

## 1.4.0

- Voice: track volume +/- dB by name or selected track, clipping check (popup with offending tracks), new armed audio track with external input channel (RØDECaster workflow). See `docs/RODE.md`.
- Claude prompt knows the new actions (track_volume, check_levels, new_input_track).

## 1.3.0

- Auto-update: the running service checks GitHub releases (every 6 h, or tray > Check for updates now), installs newer releases over the folder, restarts, and rolls back if the new version fails to start. Tray toggle "Auto-update". Private repo needs `GITHUB_TOKEN` in `.env`.

## 1.2.0

- "That was wrong" feedback (pad K3, tray menu): saves heard text, actions, Live state, log tail and a screenshot to `data/feedback/`; the phrase is routed to Claude with a hint next time.
- Fix: "play from the start of my loop" jumps to the loop start (and play commands now actually start playback).
- Redo moved to K7 + K2 (K3 is now the feedback button).

## 1.1.0

- Button pad support (XPPen ACK05 or any pad that sends keys): voice, undo/redo, record, metronome, loop, previous/next section, play/pause (state-aware), dial scroll with K7 as vertical modifier, dial press to start. See `docs/PAD.md`.
- Live pad map window (tray: Pad map) shaped like the ACK05, labels follow Live state; opens maximized on the second monitor.
- Trigger accepts extra keys; new actions `playpause`, `record`, `loop toggle`; OSC queries are thread-safe.

## 1.0.0
- System tray app (no console window): status icon, right-click menu for microphone, trigger key/mode, Claude fallback, beeps, notifications, start with Windows, log, API key, settings, restart, quit.
- Hold-to-talk (or toggle / tap) trigger on any key or button; local Whisper (faster-whisper) transcription.
- Local command router over AbletonOSC: loop bars A to B, metronome, play/stop/continue, go to bar, next/previous section, count-in, tempo, undo/redo, add/name section markers, several commands per utterance.
- Single-key shortcut registry (`data/shortcuts.json`, `data/learned_shortcuts.json`, `docs/SHORTCUTS.md`) that learns one-key actions found by the Claude fallback.
- Claude API fallback (Haiku) for project-specific commands, with Live state (tempo, loop, sections) as context.
- Translucent click-through on-screen popups on every monitor: listening (with level meter) and Claude API progress/result.
- Windows installer (`install.bat`): Python, packages, AbletonOSC remote script (patched for count-in), speech model, desktop shortcut.
