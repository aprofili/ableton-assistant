# ableton-assistant

Hands-free voice control for Ableton Live 12 on Windows. Hold a key (or a Bluetooth/USB button that sends a key), say a command, release. It runs in Live. Nothing talks back: beeps plus translucent on-screen popups.

```
trigger -> mic -> local Whisper -> router
                                    |- one-key shortcut registry   (local, free)
                                    |- local command grammar       (local, free, via AbletonOSC)
                                    '- Claude API fallback         (project-specific / fuzzy)
```

## Install (new computer)

1. Download the latest release zip (Releases page) and extract it somewhere permanent, e.g. `C:\Users\you\source\repos\ableton-assistant`. Don't copy a `.venv` folder from another PC.
2. Double-click `install.bat`. It installs Python 3.12 if needed, the packages, the AbletonOSC remote script, the speech model, and a Desktop shortcut.
3. Restart Live, then Preferences > Link, Tempo & MIDI > Control Surface > **AbletonOSC**.
4. Double-click **Ableton Assistant** on the Desktop. A mic icon appears in the system tray (check the `^` overflow).
5. Right-click the tray icon: pick your **Microphone**, set the **Trigger** (default Scroll Lock, hold to talk), and optionally **Edit API key (.env)** (`ANTHROPIC_API_KEY=sk-ant-...`).

Per-machine and never in the repo: `.venv`, `config.json` (mic, trigger), `.env` (API key), `logs/`.

## Update

Automatic: the running service checks GitHub releases every 6 h (tray > Auto-update / Check for updates now), installs a newer release over this folder (keeps `.venv`, `config.json`, `.env`, logs, learned shortcuts, feedback), re-runs pip if requirements changed, restarts, and rolls back if the new version crashes on start. Needs the repo to be public, or `GITHUB_TOKEN=<fine-grained read-only token>` in `.env`.

Manual:

Extract the new release zip over the existing folder (your `.venv`, `config.json`, `.env` are untouched), then double-click `install.bat` again and use tray > Restart assistant.

## What runs locally (no API call)

- `loop bars 5 to 9`, `create a loop region from measures 5 to 9` (start of bar 5 to start of bar 9; set `bar_range_inclusive` in `config.json` to include bar 9)
- `metronome on|off`, `loop on|off`, `play`, `stop`, `continue`, `undo`, `redo`
- `go to bar 17`, `play from bar 17`, `go to the start`, `next section`, `previous section`
- `count in two bars`, `tempo 128`
- `make a section marker saying verse at measure 10`, `name this section chorus`
- Several at once: `loop bars 5 to 9, metronome on and press play`
- Single-key actions in `docs/SHORTCUTS.md`

Anything else goes to the Claude API (needs the key). Single-key actions it identifies are saved to `data/learned_shortcuts.json` and run locally afterwards.

## Button pad

XPPen ACK05 (or any key-sending pad): voice button, play/pause, undo/redo, record, metronome, loop, section jumps, dial scroll (hold K7 for vertical), plus a live pad map window for a second monitor. Key assignments and setup: `docs/PAD.md`.

## RØDECaster / levels

Voice: track volume up/down, clipping check, new armed input tracks. See `docs/RODE.md`.

## Triggers

`hold` records while held, `toggle` is press-start/press-stop, `tap` ends on ~1 s of silence (for one-event buttons). Pick a key nothing else uses. `Ctrl+Alt+Space` is taken by the Claude desktop app.

## Development

`python -m unittest discover -s tests` (offline, mock AbletonOSC). Console mode with logs: `run.bat`. CLI: `python -m assistant --text "loop bars 5 to 9" --dry-run`, `--check`, `--list-devices`, `--select-mic`, `--learn-trigger`.

Releases: bump `VERSION` and `CHANGELOG.md`, tag `vX.Y.Z`, run `scripts/make_release.sh`.
