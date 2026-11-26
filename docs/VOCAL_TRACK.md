# "New vocal track" (action `new_vocal_track`)

Voice: "new vocal track", "give me a vocal track"; add "with record monitoring on" for monitoring Auto.

New armed audio track "Vocal" (only it armed), Ext. In 3, Favorites rack "Vocal Base 2" first in the chain, then EQ Eight, Utility.
Record monitoring defaults to Off; "monitoring on" means Auto (only said when the speakers are off). Same rule for the
drum mic track (docs/DRUM_MIC_TRACK.md). Guitar tracks keep monitoring Auto.

How: `a_new_input_track` (channel 3, monitor_state 2 or 1) then `_build_chain(ti, ["Vocal Base 2.adg"])`: delete the template
devices (OSC delete_device), then browser-search load in order (ctrl+f, type, Down, Enter; each appends): the preset
("Vocal Base 2.adg", first search hit), EQ Eight, Utility. The guitar action uses
the same chain builder so Guitar Rig is up front too.

Note: Adam corrected the preset to "Vocal Base 2" (not "Vocal Base"). Searching "Vocal Base 2.adg" returns it as the first hit.
