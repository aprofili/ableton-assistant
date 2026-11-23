"""Local command router: free text -> list of action dicts, no network.

Returns None when any part of the utterance isn't understood, so the caller
can fall back to the Claude API with the full utterance.
"""
import re

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_FILLER = re.compile(
    r"\b(hey|ok|okay)?\s*claude\b|\b(please|can you|could you|go ahead and|now|just|then)\b"
)
_RANGE_JOIN = re.compile(r"(\d+)\s+(?:and|to|through|thru|until|till|into)\s+(?:bar\s+|measure\s+)?(\d+)")
_SPLIT = re.compile(r"\band then\b|\bthen\b|\band\b|[,;]")


def normalize(text):
    t = text.lower().replace("-", " ")
    t = re.sub(r"[^a-z0-9 .,;]", " ", t)
    t = re.sub(r"\.(?!\d)", " ", t)

    def words_to_nums(m):
        w = m.group(0)
        return str(_NUMBER_WORDS[w])

    t = re.sub(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", words_to_nums, t)
    # "twenty 4" style compounds are rare for bar numbers; join "20 4" -> 24
    t = re.sub(r"\b([2-9]0) ([1-9])\b", lambda m: str(int(m.group(1)) + int(m.group(2))), t)
    t = t.replace("measures", "bars").replace("measure", "bar")
    t = _FILLER.sub(" ", t)
    t = _RANGE_JOIN.sub(r"\1 to \2", t)
    return re.sub(r"\s+", " ", t).strip()


def _on_off(seg):
    if re.search(r"\b(off|disable|stop|mute|kill)\b", seg):
        return False
    if re.search(r"\b(on|enable|start)\b", seg):
        return True
    return "toggle"


_SECTION = r"(?:section|marker|locator|cue)"
_NOUN = r"(?:" + _SECTION + r"\b\s*)+"
_NAMED = r"(?:called|named|saying|that says|labeled|labelled|with the name|for)?"


def _title(s):
    return s.strip().title()


_UP = r"turn up|raise|increase|boost|bring up|louder|more volume|up"
_DOWN = r"turn down|lower|reduce|decrease|bring down|quieter|softer|less volume|down"


def _match_audio(seg):
    if re.search(r"\bclipping\b|\bclip\b|\bcheck (?:the )?levels\b|\bcheck (?:for )?peaks\b", seg):
        return [{"type": "check_levels", "seconds": 3}]
    m = re.fullmatch(r"(?:turn|bring) (?:it|this|that) (up|down)(?: by (\d+(?:\.\d+)?) ?(?:d b|db|decibels?))?", seg)
    if m:
        db = float(m.group(2)) if m.group(2) else 2.0
        return [{"type": "track_volume", "track": "selected", "db": db if m.group(1) == "up" else -db}]
    m = re.fullmatch(r"(" + _UP + "|" + _DOWN + r")(?: the)?(?: volume| level| gain)?(?: (?:on|of|for))?(?: the)?"
                     r"(?: (.+?))?(?: by (\d+(?:\.\d+)?) ?(?:d b|db|decibels?))?", seg)
    if m:
        up = re.fullmatch(_UP, m.group(1)) is not None
        track = (m.group(2) or "selected").replace(" track", "").strip() or "selected"
        track = re.sub(r"^(?:a |the |my )", "", track)
        if track in ("it", "this", "that", "selected", "current", "this one"):
            track = "selected"
        db = float(m.group(3)) if m.group(3) else 2.0
        return [{"type": "track_volume", "track": track, "db": db if up else -db}]
    if re.search(r"\b(?:create|make|add|new|set up)\b", seg) and re.search(r"\btrack\b", seg) and \
            (re.search(r"\baudio\b|\brode ?caster\b|\brode\b", seg) or re.search(r"\b(?:mic|channel|input)\s*\d+", seg)):
        ch = re.search(r"\b(?:mic|channel|input|ch)\s*(\d+)", seg)
        nm = re.search(r"\b(?:called|named|name|for (?!the\b|a\b|my\b|rode\b))\s*(.+?)(?:\s+(?:from|on|with|using|input|channel|mic|rode)\b.*)?$", seg)
        name = _title(nm.group(1)) if nm and nm.group(1).strip() else None
        a = {"type": "new_input_track"}
        if name:
            a["name"] = name
        if ch:
            a["channel"] = ch.group(1)
        return [a]
    return None


def _match(seg):
    """Match one normalized segment. Returns list of actions or None."""
    got = _match_audio(seg)
    if got:
        return got
    m = re.search(r"\b(?:make|add|create|insert|put|drop)\b.*?\b" + _NOUN + _NAMED +
                  r"\s*(.+?)\s+(?:at|on) (?:the )?(?:bar )?(\d+)\b", seg)
    if m and m.group(1).strip():
        return [{"type": "add_section", "bar": int(m.group(2)), "name": _title(m.group(1))}]
    m = re.search(r"\b(?:make|add|create|insert|put|drop)\b.*?\b" + _NOUN + r"(?:at|on) (?:the )?(?:bar )?(\d+)\s*" +
                  _NAMED + r"\s*(.+)$", seg)
    if m and m.group(2).strip():
        return [{"type": "add_section", "bar": int(m.group(1)), "name": _title(m.group(2))}]
    m = re.search(r"\b(?:name|call|rename|label)\s+(?:this|the current|current)\s+" + _SECTION + r"\s*(?:to|as)?\s*(.+)$", seg)
    if m and m.group(1).strip():
        return [{"type": "name_section", "name": _title(m.group(1))}]

    m = re.search(r"\bplay from (?:the )?(?:bar )?(\d+)\b", seg)
    if m:
        return [{"type": "goto_bar", "bar": int(m.group(1))}, {"type": "play"}]

    m = re.search(r"\b(?:loop|region)\b\D*?(\d+)\s+to\s+(\d+)", seg)
    if m:
        return [{"type": "set_loop", "start_bar": int(m.group(1)), "end_bar": int(m.group(2))}]

    m = re.search(r"\b(?:go to|jump to|move to|locate|set position to)\s+(?:the )?(?:bar )?(\d+)\b", seg)
    if m:
        return [{"type": "goto_bar", "bar": int(m.group(1))}]

    play = [{"type": "play"}] if re.search(r"\b(?:play|start playing|roll)\b", seg) else []
    if re.search(r"\b(?:go to|jump to|back to|from|at) (?:the )?(?:top|start|beginning)(?: of)? (?:the |my |this )?(?:loop|loop region|looped section)\b", seg):
        return [{"type": "goto_loop_start"}] + play
    if re.search(r"\b(?:go to|jump to|back to|from) (?:the )?(?:top|start|beginning)\b", seg):
        return [{"type": "goto_bar", "bar": 1}] + play

    if re.search(r"\b(?:metronome|click)\b", seg):
        return [{"type": "metronome", "on": _on_off(seg)}]

    if re.search(r"\bloop\b", seg) and re.search(r"\b(on|off|enable|disable)\b", seg):
        return [{"type": "loop", "on": _on_off(seg) is True}]

    m = re.search(r"\bcount in\b\D*?(\d+|none|off)\b", seg) or re.search(r"\b(\d+) bars? count in\b", seg)
    if m:
        v = m.group(1)
        return [{"type": "set_count_in", "bars": 0 if v in ("none", "off") else int(v)}]

    m = re.search(r"\btempo\b\D*?(\d{2,3}(?:\.\d+)?)", seg)
    if m:
        return [{"type": "set_tempo", "bpm": float(m.group(1))}]

    if re.search(r"\bnext (?:section|marker|locator|cue)\b", seg):
        return [{"type": "next_cue"}]
    if re.search(r"\b(?:previous|last|prior) (?:section|marker|locator|cue)\b", seg):
        return [{"type": "prev_cue"}]

    if re.fullmatch(r"(?:press |hit )?undo(?: that)?", seg):
        return [{"type": "undo"}]
    if re.fullmatch(r"(?:press |hit )?redo(?: that)?", seg):
        return [{"type": "redo"}]

    if re.fullmatch(r"(?:press |hit )?(?:stop|pause|halt)(?: playback| playing| it| the song)?", seg):
        return [{"type": "stop"}]
    if re.fullmatch(r"(?:press |hit )?(?:play|start|start playing|start playback|roll)(?: playback| it| the song)?", seg):
        return [{"type": "play"}]
    if re.fullmatch(r"(?:press |hit )?continue(?: playback| playing)?", seg):
        return [{"type": "continue"}]
    return None


def route(text, shortcuts=None):
    """Return (actions, source) or (None, None). source is 'local' or 'shortcut'."""
    norm = normalize(text)
    if not norm:
        return None, None
    if shortcuts:
        hit = shortcuts.match(norm)
        if hit:
            return [{"type": "key", "keys": hit["keys"]}], "shortcut"
    actions = []
    used_shortcut = False
    for seg in (s.strip() for s in _SPLIT.split(norm)):
        if not seg:
            continue
        hit = shortcuts.match(seg) if shortcuts else None
        if hit:
            actions.append({"type": "key", "keys": hit["keys"]})
            used_shortcut = True
            continue
        got = _match(seg)
        if got is None:
            return None, None
        actions.extend(got)
    if not actions:
        return None, None
    return actions, ("shortcut" if used_shortcut else "local")
