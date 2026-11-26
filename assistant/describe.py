"""Human-readable one-liners for action lists (used by the on-screen popups)."""


def _onoff(v):
    return "toggle" if v == "toggle" else ("on" if v else "off")


def describe_action(a):
    t = a.get("type")
    if t == "set_loop":
        return f"Loop bars {a['start_bar']:g}–{a['end_bar']:g}"
    if t == "loop":
        return f"Loop {_onoff(a.get('on', True))}"
    if t == "metronome":
        return f"Metronome {_onoff(a.get('on', 'toggle'))}"
    if t == "play":
        return "Play"
    if t == "continue":
        return "Continue"
    if t == "stop":
        return "Stop"
    if t == "undo":
        return "Undo"
    if t == "redo":
        return "Redo"
    if t == "goto_bar":
        return f"Go to bar {a['bar']:g}"
    if t == "arm_track":
        return "Arm track for recording" if a.get("on", True) else "Disarm track"
    if t == "goto_cue":
        return f"Go to “{a['name']}”"
    if t == "next_cue":
        return "Next section"
    if t == "prev_cue":
        return "Previous section"
    if t == "set_count_in":
        n = a["bars"]
        return "Count-in off" if n == 0 else f"Count-in {n} bar{'s' if n != 1 else ''}"
    if t == "new_drum_mic_track":
        return "New Drums group (L in 3 / R in 5)"
    if t == "double_track":
        return "Double track (group, L/R)"
    if t == "time_signature":
        return f"Time signature {a['num']}/{a['den']}"
    if t == "set_tempo":
        return f"Tempo {a['bpm']:g}"
    if t == "add_section":
        return f"Marker “{a['name']}” at bar {a['bar']:g}"
    if t == "name_section":
        return f"Name section “{a['name']}”"
    if t == "track_volume":
        return f"{a.get('track', 'selected')} {a['db']:+g} dB"
    if t == "check_levels":
        return "Check levels"
    if t == "new_guitar_track":
        return "New Guitar track + Guitar Rig preset"
    if t == "new_input_track":
        return "New armed track" + (f" “{a['name']}”" if a.get("name") else "") + (f" (input {a['channel']})" if a.get("channel") else "")
    if t == "key":
        return f"Key {a['keys']}"
    if t == "osc":
        return f"OSC {a['address']}"
    return str(t)


def describe(actions):
    parts = [describe_action(a) for a in actions if a.get("type") != "wait"]
    return "  •  ".join(parts) if parts else "Not a command"
