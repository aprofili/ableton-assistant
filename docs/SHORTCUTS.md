# Single-key-press Ableton actions

These are handled locally with no Claude API call. Generated from
`data/shortcuts.json` (built-in) and `data/learned_shortcuts.json`
(added automatically when the fallback finds a request that is just one key press).

| Say | Keys | What it does | Source |
|---|---|---|---|
| switch view / toggle view / session view / arrangement view / switch between session and arrangement | `tab` | Toggle Session / Arrangement view | builtin |
| save / save project / save the project / save set | `ctrl+s` | Save the Live Set | builtin |
| new audio track / add audio track / insert audio track | `ctrl+t` | Insert audio track | builtin |
| new midi track / add midi track / insert midi track | `ctrl+shift+t` | Insert MIDI track | builtin |
| duplicate / duplicate that / duplicate selection | `ctrl+d` | Duplicate selection | builtin |
| record / start recording / arm record / toggle record | `f9` | Toggle Arrangement Record | builtin |
| toggle playback / play pause / play stop | `space` | Start/stop playback (toggle). Plain 'play' and 'stop' use OSC instead, which is not a toggle. | builtin |
