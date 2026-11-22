"""Registry of single-key-press Ableton actions.

data/shortcuts.json          built-in, curated
data/learned_shortcuts.json  added automatically when the Claude fallback
                             identifies a request that is just one key press

Anything in here is handled locally next time, with no API call.
docs/SHORTCUTS.md is regenerated from both files on every change.
"""
import json
import os
import re
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN = os.path.join(ROOT, "data", "shortcuts.json")
LEARNED = os.path.join(ROOT, "data", "learned_shortcuts.json")
DOC = os.path.join(ROOT, "docs", "SHORTCUTS.md")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


class Shortcuts:
    def __init__(self):
        self.reload()

    def reload(self):
        self.items = _load(BUILTIN) + _load(LEARNED)

    def match(self, normalized_text):
        for it in self.items:
            for p in it["phrases"]:
                if _norm(p) == normalized_text:
                    return it
        return None

    def known_summary(self):
        return [{"phrases": it["phrases"], "keys": it["keys"]} for it in self.items]

    def learn(self, keys, phrases, description=""):
        """Record a new single-key action. Returns True if something was added."""
        phrases = [p for p in (_norm(p) for p in phrases) if p]
        keys = keys.strip().lower()
        if not keys or not phrases:
            return False
        learned = _load(LEARNED)
        for it in self.items:
            if it["keys"].lower() == keys:
                new = [p for p in phrases if p not in {_norm(x) for x in it["phrases"]}]
                if not new:
                    return False
                if it in learned or any(l["keys"].lower() == keys for l in learned):
                    for l in learned:
                        if l["keys"].lower() == keys:
                            l["phrases"].extend(new)
                else:
                    learned.append({"id": f"learned-{len(learned) + 1}", "phrases": new, "keys": keys,
                                    "description": description or it.get("description", ""),
                                    "source": "learned", "added": date.today().isoformat()})
                break
        else:
            learned.append({"id": f"learned-{len(learned) + 1}", "phrases": phrases, "keys": keys,
                            "description": description, "source": "learned",
                            "added": date.today().isoformat()})
        with open(LEARNED, "w", encoding="utf-8") as f:
            json.dump(learned, f, indent=2)
        self.reload()
        write_doc(self.items)
        return True


def write_doc(items=None):
    items = items if items is not None else _load(BUILTIN) + _load(LEARNED)
    lines = [
        "# Single-key-press Ableton actions",
        "",
        "These are handled locally with no Claude API call. Generated from",
        "`data/shortcuts.json` (built-in) and `data/learned_shortcuts.json`",
        "(added automatically when the fallback finds a request that is just one key press).",
        "",
        "| Say | Keys | What it does | Source |",
        "|---|---|---|---|",
    ]
    for it in items:
        lines.append(
            f"| {' / '.join(it['phrases'])} | `{it['keys']}` | {it.get('description', '')} | {it.get('source', 'builtin')} |"
        )
    lines.append("")
    with open(DOC, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    write_doc()
