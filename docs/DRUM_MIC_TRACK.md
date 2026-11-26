# "New drum mic track" (action `new_drum_mic_track`)

Voice: "new drum mic track", "make a drum mic track", "drum mics".

Result: group **Drums** (fader 0.75) holding **L** (Ext. In channel 3, hard left) and **R** (Ext. In channel 5, hard right).
Each of L and R has devices in this order: Compressor (defaults), EQ Eight, Utility (the standard new-track devices).
The group has no devices. Only R (the newest track) is armed (rule: any new track arms only the new one); monitoring Auto.

How (Actions.a_new_drum_mic_track in assistant/ableton.py):
1. `a_new_input_track({name L, channel 3})`: new audio track, exclusive arm, Ext. In 3, monitoring Auto, selected.
2. Delete the template devices (`/live/track/delete_device`) then load via the browser search (ctrl+f, type name, Down,
   Enter; each appends to the end of the chain, and the plain name "Compressor"/"EQ Eight"/"Utility" returns the
   native device first): Compressor, EQ Eight, Utility. (Loading Compressor after the template leaves it last; there is
   no keyboard way to move a device, so rebuild the chain in order.)
3. Pan L -1. Group L alone (see DOUBLE_TRACK.md; Ctrl+G, fallback Alt+E G), then Ctrl+D inside the group -> R (identical
   devices, no clips).
4. R input channel 5, names Drums/L/R, pans -1/+1, group volume 0.75, arm only R.
