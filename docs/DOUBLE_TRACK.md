# "Double this" (action `double_track`)

Voice: "double this", "double track", "double it", "I want to double this".

Turns the selected track (name N) into a group named N holding two tracks:
- **L** - the original (clips kept), hard left (pan -1).
- **R** - a copy with the same devices/effects, all clips deleted, hard right (pan +1).
- Only R (the new track) is armed for recording; every other track, including L, is disarmed. Rule for ALL new tracks: arm only the new one.
- Group volume = three quarters of unity gain (about -2.5 dB): `/live/track/set/volume` = 0.85*0.75^0.25 (Live: 0.85 = 0 dB).

How it is done (Actions.a_double_track in assistant/ableton.py):
1. Read the selected track index `ti` and its name (OSC).
2. Click an empty arrangement spot (keyboard focus must be in the arrangement lanes), reselect `ti` by OSC, press Ctrl+G
   (fallback: Alt+E, G) -> group at `ti`, original at `ti+1`. Group tracks only acts on the selected track(s); a
   multi-track selection needs header focus, so grouping the original alone first is the reliable path.
3. Select `ti+1`, Ctrl+D -> duplicate lands inside the group at `ti+2` (devices kept, clips copied).
4. Clear clips on `ti+2`: session slots via `/live/clip_slot/delete_clip`; arrangement clips via Ctrl+A (time range
   over all content on all tracks), Down (collapses to one track), then Up/Down until `/live/view/get/selected_track`
   equals `ti+2`, then Delete. Never press Delete unless the selected track is `ti+2`.
5. Group volume ~ -2.5 dB; arm R only, disarm everything else (`/live/track/set/arm`).
6. Names via `/live/track/set/name` (group=N, L, R); pans via `/live/track/set/panning` (-1 / +1; Live shows 50L/50R).

Notes: Live's pan field range is 50L..50R, so -1/+1 is hard pan. Edit menu: Group Tracks (Ctrl+G), Duplicate (Ctrl+D).
Needs Live in front; the action focuses it.

