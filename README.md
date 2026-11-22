# ableton-assistant

Hands-free voice control for Ableton Live 12 on Windows.

Hold a key (or press a Bluetooth/USB button that sends a key), say a command, release. The command runs in Live. Nothing talks back; you get short beeps (high = listening, chime = done, low = failed).

```
trigger key/button -> mic (chosen up front) -> local Whisper -> router
                                                   |-- one-key shortcut registry   (local, free)
                                                   |-- local command grammar        (local, free, via AbletonOSC)
                                                   '-- Claude API fallback          (project-specific / fuzzy)
```

## Install

1. Double-click `install.bat` (downloads Python from python.org if needed, packages, the AbletonOSC remote script, the speech model).
2. In Live: Preferences > Link, Tempo & MIDI > Control Surface > pick **AbletonOSC**. Live shows "AbletonOSC: Listening for OSC on port 11000".
3. For the Claude fallback only: create `.env` with `ANTHROPIC_API_KEY=sk-ant-...`. Everything in the first-test list runs without it.
4. `run.bat --select-mic` to pick the command microphone (saved). Choose a WASAPI/MME entry, not ASIO.
5. `run.bat --learn-trigger` and press your button/key. Default is `Scroll Lock`, hold to talk (not `ctrl+alt+space`, which the Claude desktop app uses).
6. Double-click `start_hidden.vbs` to start with no console window. The assistant lives in the system tray (right-click for microphone, trigger, log, API key, quit, start-with-Windows). `run.bat` starts it with a visible console for debugging.

Useful: `run.bat --check` (Ableton connection), `run.bat --text "loop bars 5 to 9, metronome on, play"` (no mic), `run.bat --text "..." --dry-run`.

## Trigger modes (`config.json` -> `trigger.mode`)

- `hold`: records while held (needs press and release events)
- `toggle`: press to start, press again to stop
- `tap`: press once, recording ends after ~1 s of silence (for cheap one-event buttons)

Pick keys nothing else uses (F13-F24, or a combo). The trigger key is not suppressed, so it also reaches Ableton.

## What runs locally (no API call)

- `loop bars 5 to 9` / `create a loop region from measures 5 to 9`
- `metronome on|off`, `loop on|off`, `play`, `stop`, `continue`, `undo`, `redo`
- `go to bar 17`, `play from bar 17`, `go to the start`, `next section`, `previous section` (sections = locators)
- `count in two bars`, `tempo 128`
- Several in one breath: `loop bars 5 to 9, metronome on and press play`
- Single-key actions in `docs/SHORTCUTS.md`

Bar ranges: "5 to 9" means the start of bar 5 to the start of bar 9 (as the loop brace reads on the ruler). Set `bar_range_inclusive` to `true` in `config.json` to include bar 9. Bar math uses the song's time signature at the moment of the command (no mid-song signature changes).

## Single-key shortcut learning

`data/shortcuts.json` holds built-in one-key actions; `data/learned_shortcuts.json` holds learned ones. When a request falls through to Claude and Claude identifies it as exactly one default Live shortcut, the phrase and key are saved and `docs/SHORTCUTS.md` is regenerated. Next time it runs locally. Project-specific requests ("loop the first half of the section I named Bridge") always stay on the API.

## Files

- `assistant/router.py` local grammar; `shortcuts.py` registry; `claude_api.py` fallback
- `assistant/ableton.py` AbletonOSC client + actions; `keys.py` shortcut sender (focuses Live first)
- `assistant/audio.py`, `stt.py`, `trigger.py`, `app.py`
- `tests/` offline tests against a mock AbletonOSC (`python -m unittest discover -s tests`)
