# Changelog

## 1.3.1

- Maintenance: GitHub Actions workflow tests, merges and releases pushed feature branches automatically.

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
