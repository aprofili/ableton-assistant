# RØDECaster Pro II

## Works now (Ableton side, local, no API)
| Say | Does |
|---|---|
| "turn up the vocals", "more volume on guitar by 3 dB", "lower the bass" | Fader +/- (default 2 dB; track name loose-matched) |
| "louder", "turn it down" | Same on the selected track |
| "am I clipping", "check levels", "make sure I'm not clipping" | Watches every track and Master meter for 3 s while playing; popup lists tracks at/over `rode.clip_threshold` |
| "create a new audio track called vocals from mic 2" | New armed audio track, input set to Ext. In, channel 2 |

Input channel naming is the one unknown: Live labels external inputs per your audio driver (e.g. "1/2", "3/4"). If a channel isn't found, the log lists what Live offers; map it in `config.json`:
`{"rode": {"channels": {"2": "3/4"}}}`. Fader steps are ~0.025 of the fader range per dB (accurate near 0 dB). Clipping uses the meter scale where 0.85 is about 0 dBFS.

## Not done: controlling the RØDECaster itself (its gain, faders, mute)
RØDE publishes no API for this. What exists: the device can be driven over MIDI (Stream Deck integration uses MIDI to trigger smart pads, record/pause/stop, listen and mute buttons for channels 1-6); the RØDECaster App/RØDE Central configures it. Whether fader or gain levels can be set over MIDI is not documented, so I did not guess. Once you can connect it: check System > MIDI on the device, then tell me which MIDI port name appears on the PC and I'll wire mute/listen/pads (and test whether faders respond).

Sources: RØDE help article on Stream Deck control of the Pro II (MIDI commands), RØDE MIDI Control user guide.
