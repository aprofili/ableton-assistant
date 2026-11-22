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
  key{keys, learn_phrases}  one Ableton keyboard shortcut, e.g. "ctrl+shift+t", "f9", "tab"
  osc{address,args}  raw AbletonOSC call if nothing above fits (e.g. /live/song/cue_point/add_or_delete,
                     /live/song/cue_point/set/name [index, name])
  wait{seconds}

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
                            "goto_bar", "goto_cue", "next_cue", "prev_cue", "set_count_in", "set_tempo",
                            "key", "osc", "wait"]},
                        "start_bar": {"type": "number"}, "end_bar": {"type": "number"},
                        "bar": {"type": "number"}, "name": {"type": "string"},
                        "on": {"type": ["boolean", "string"]}, "bars": {"type": "integer"},
                        "bpm": {"type": "number"}, "keys": {"type": "string"},
                        "learn_phrases": {"type": "array", "items": {"type": "string"}},
                        "address": {"type": "string"}, "args": {"type": "array"},
                        "seconds": {"type": "number"},
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


def ask(text, state, known_shortcuts, model="claude-haiku-5-5"):
    """Returns the list of action dicts from Claude."""
    _load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set (put it in .env). Needed only for complex commands.")
    import anthropic

    client = anthropic.Anthropic(timeout=20.0, max_retries=1)
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM.format(known=json.dumps(known_shortcuts), state=json.dumps(state)),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "perform_actions"},
        messages=[{"role": "user", "content": text}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input.get("actions", [])
    return []
