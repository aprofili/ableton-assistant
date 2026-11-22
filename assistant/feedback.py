"""'That was wrong' feedback: records what was heard, what ran, Live's state and the log tail.

data/feedback/feedback.jsonl   one JSON entry per press (plus an optional screenshot per entry)
data/feedback/bad.json         phrase -> action lists marked wrong; the next time the same phrase is
                               heard it skips the local router and goes to Claude with a "that was wrong" hint.
"""
import json
import os
import time

from . import config as cfgmod

DIR = os.path.join(cfgmod.ROOT, "data", "feedback")
LOG = os.path.join(cfgmod.ROOT, "logs", "assistant.log")


def _bad_path():
    return os.path.join(DIR, "bad.json")


def load_bad():
    try:
        with open(_bad_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def bad_for(norm_text):
    return load_bad().get(norm_text, [])


def _log_tail(n=40):
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            return [l.rstrip() for l in f.readlines()[-n:]]
    except OSError:
        return []


def _screenshot(stamp):
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
        img.thumbnail((1920, 1080))
        path = os.path.join(DIR, f"{stamp}.jpg")
        img.convert("RGB").save(path, quality=70)
        return os.path.basename(path)
    except Exception:
        return None


def record(last, state_now, norm_text, version, screenshot=True):
    """last: dict(text, source, actions, before, ts). Returns the saved entry."""
    os.makedirs(DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": version,
        "heard": last.get("text"),
        "source": last.get("source"),
        "actions": last.get("actions"),
        "state_before": last.get("before"),
        "state_at_feedback": state_now,
        "log_tail": _log_tail(),
        "screenshot": _screenshot(stamp) if screenshot else None,
        "verdict": "wrong",
    }
    with open(os.path.join(DIR, "feedback.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    bad = load_bad()
    lst = bad.setdefault(norm_text, [])
    if last.get("actions") and last["actions"] not in lst:
        lst.append(last["actions"])
        del lst[:-3]
    with open(_bad_path(), "w", encoding="utf-8") as f:
        json.dump(bad, f, indent=2)
    return entry
