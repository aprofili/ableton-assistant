"""Claude fallback: only used when the local router can't handle an utterance."""
import json
import os

SYSTEM = """You control Ableton Live 12 (Windows) for a musician who is talking hands-free. \
Translate the transcribed voice command into actions by calling perform_actions. Never reply with text.

Transcription may contain errors (e.g. "metro gnome", "chorus" heard as "course"); infer the intent.
Bars are 1-indexed bar numbers as shown in Live's ruler. "Sections" are the locators listed in the
state (name + bar). Resolve section names to bars from the state, matching loosely.
A bar range "A to B" means from the start of bar A to the start of bar B (set_loop start_bar=A end_bar=B)
unless the user clearly says to include the last bar.

Action types:
  set_loop{start_bar,end_bar}  set loop region and turn loop on
  loop{on}  metronome{on: true|false|"toggle"}  play  continue  stop  undo  redo
  goto_bar{bar}  goto_cue{name}  next_cue  prev_cue  set_count_in{bars: 0|1|2|4}  set_tempo{bpm}
  add_section{bar,name}  create a locator at a bar and name it (renames it if one already exists there)
  name_section{name}  name the section the playhead is currently in (creates a locator there if none precedes it)
  track_volume{track, db}  change a track's fader by db (+/-); track = name from state or "selected"
  check_levels{seconds}  watch meters while playing and report clipping (shown on screen)
  arm_track{on: bool}  arm/disarm the selected track for recording
  new_input_track{name, channel}  new armed audio track whose input is external channel N (RØDECaster inputs)
  key{keys, learn_phrases}  one Ableton keyboard shortcut, e.g. "ctrl+shift+t", "f9", "tab"
  osc{address,args}  raw AbletonOSC call if nothing above fits (e.g. /live/song/cue_point/add_or_delete,
                     /live/song/cue_point/set/name [index, name])
  wait{seconds}

If the transcript is not a command for Live (chatter with bandmates, a fragment, noise), return an empty
actions list. Never guess at a command that wasn't clearly given.

Prefer high-level actions over osc/key. Order actions as they should execute.

Single-key learning: if the request is exactly ONE default Ableton Live keyboard shortcut (one key or one
chord, nothing else needed), return it as a single key action and put 2-4 short natural phrasings a user
might say for it in learn_phrases. It will then run locally next time without an API call. Only do this when
you are confident of the default shortcut. Don't use key for anything that high-level actions or osc cover.
Multi-step or project-specific requests are never learned.

Known one-key shortcuts already handled locally (don't re-learn these):
{known}

Current Live state:
{state}
"""

TOOL = {
    "name": "perform_actions",
    "description": "Execute a list of actions in Ableton Live in order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": [
                            "set_loop", "loop", "metronome", "play", "continue", "stop", "undo", "redo",
                            "goto_bar", "goto_cue", "arm_track", "next_cue", "prev_cue", "set_count_in", "set_tempo",
                            "add_section", "name_section", "track_volume", "check_levels", "new_input_track",
                            "key", "osc", "wait"]},
                        "start_bar": {"type": "number"}, "end_bar": {"type": "number"},
                        "bar": {"type": "number"}, "name": {"type": "string"},
                        "on": {"type": ["boolean", "string"]}, "bars": {"type": "integer"},
                        "bpm": {"type": "number"}, "keys": {"type": "string"},
                        "learn_phrases": {"type": "array", "items": {"type": "string"}},
                        "address": {"type": "string"}, "args": {"type": "array"},
                        "seconds": {"type": "number"}, "track": {"type": "string"}, "db": {"type": "number"},
                        "channel": {"type": "string"},
                    },
                    "required": ["type"],
                },
            }
        },
        "required": ["actions"],
    },
}


def _load_env():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def build_system(known_shortcuts, state):
    # str.replace, not str.format: the prompt contains literal braces like {start_bar,end_bar}
    return SYSTEM.replace("{known}", json.dumps(known_shortcuts)).replace("{state}", json.dumps(state))


def ask(text, state, known_shortcuts, model="claude-haiku-5-5", hint=None):
    """Returns the list of action dicts from Claude."""
    _load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set (put it in .env). Needed only for complex commands.")
    import anthropic

    client = anthropic.Anthropic(timeout=20.0, max_retries=1)
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=build_system(known_shortcuts, state),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "perform_actions"},
        messages=[{"role": "user", "content": text + (f"\n\n[{hint}]" if hint else "")}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input.get("actions", [])
    return []
