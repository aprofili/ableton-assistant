"""Learned voice macros: when Claude solves a command, turn the solved example into a template so the
same kind of command runs locally next time (no API call).

Example: heard "create a section marker at bar 13 and call it drum loop" and Claude returned
add_section{bar: 13, name: "drum loop"}. Learned template:
    create a section marker at bar {n0} and call it {t0}     ->  add_section{bar: {n0}, name: {t0}}
Next time "create a section marker at bar 21 and call it verse two" matches and runs locally.

Safety: a template is only saved if every number / name in Claude's actions appears exactly once in what
was heard (so slots are unambiguous), enough fixed words remain to avoid over-matching, and replaying the
template on the original phrase reproduces Claude's actions exactly. "That was wrong" deletes the macro
that produced a command.
"""
import copy
import json
import os
import re
from datetime import date

from . import config as cfgmod

STORE = os.path.join(cfgmod.ROOT, "data", "learned_macros.json")

NUM_FIELDS = {"bar", "start_bar", "end_bar", "bpm", "db", "bars", "seconds", "channel"}
TEXT_FIELDS = {"name", "track"}
_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def _case(value, span):
    if value == span:
        return "lower"
    if value == span.title():
        return "title"
    if value == span.capitalize():
        return "sentence"
    if value == span.upper():
        return "upper"
    return None


def _apply_case(span, mode):
    return {"lower": span, "title": span.title(), "sentence": span.capitalize(), "upper": span.upper()}[mode]


def _compile(template, slots):
    parts, pos = [], 0
    for m in re.finditer(r"\{([nt]\d+)\}", template):
        parts.append(re.escape(template[pos:m.start()]))
        parts.append(r"(\d+(?:\.\d+)?)" if m.group(1)[0] == "n" else r"(.+?)")
        pos = m.end()
    parts.append(re.escape(template[pos:]))
    return re.compile("^" + "".join(parts) + "$")


def _fill(node, vals):
    if isinstance(node, dict):
        return {k: _fill(v, vals) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, vals) for v in node]
    if isinstance(node, str):
        m = re.fullmatch(r"\{([nt]\d+)\}", node)
        if m:
            return vals[m.group(1)]
    return node


def _instantiate(macro, norm):
    rx = _compile(macro["template"], macro["slots"])
    m = rx.match(norm)
    if not m:
        return None
    vals = {}
    for (sid, spec), raw in zip(macro["slots"].items(), m.groups()):
        if sid[0] == "n":
            v = float(raw)
            vals[sid] = int(v) if spec.get("int") and v == int(v) else v
        else:
            vals[sid] = _apply_case(raw.strip(), spec["case"])
    return _fill(copy.deepcopy(macro["actions"]), vals)


def match(norm):
    """Best learned macro for a normalized phrase -> (macro_id, actions) or None."""
    best = None
    for macro in _load():
        acts = _instantiate(macro, norm)
        if acts is not None:
            score = len(re.sub(r"\{[nt]\d+\}", "", macro["template"]))
            if best is None or score > best[0]:
                best = (score, macro["id"], acts)
    if not best:
        return None
    items = _load()
    for it in items:
        if it["id"] == best[1]:
            it["hits"] = it.get("hits", 0) + 1
    _save(items)
    return best[1], best[2]


def learn(norm, actions):
    """Try to save a template for (norm -> actions). Returns the macro dict, or None if not safe."""
    if not actions or not norm:
        return None
    acts = copy.deepcopy(actions)
    template = norm
    slots, spans = {}, []  # spans: (start, end, slot id)
    used_numbers, n_i, t_i = [], 0, 0

    for a in acts:
        for k in list(a):
            v = a[k]
            if k in NUM_FIELDS and isinstance(v, (int, float)) and not isinstance(v, bool):
                hits = [m for m in _NUM.finditer(norm) if float(m.group(0)) == float(v)]
                if len(hits) != 1:
                    return None
                h = hits[0]
                if any(s <= h.start() < e for s, e, _ in spans):
                    return None  # two fields claim the same number
                sid = f"n{n_i}"
                n_i += 1
                slots[sid] = {"int": isinstance(v, int) or float(v) == int(float(v))}
                spans.append((h.start(), h.end(), sid))
                a[k] = "{" + sid + "}"
            elif k in TEXT_FIELDS and isinstance(v, str) and v.strip():
                low = v.strip().lower()
                hits = [m for m in re.finditer(r"(?<!\w)" + re.escape(low) + r"(?!\w)", norm)]
                if len(hits) != 1:
                    return None
                h = hits[0]
                mode = _case(v.strip(), norm[h.start():h.end()])
                if mode is None:
                    return None
                sid = f"t{t_i}"
                t_i += 1
                slots[sid] = {"case": mode}
                spans.append((h.start(), h.end(), sid))
                a[k] = "{" + sid + "}"
    # build template; slots order in the template must follow text order for the regex groups
    spans.sort()
    order = {sid: i for i, (_, _, sid) in enumerate(spans)}
    out, pos = [], 0
    for s, e, sid in spans:
        out.append(norm[pos:s])
        out.append("{" + sid + "}")
        pos = e
    out.append(norm[pos:])
    template = "".join(out)
    slots = {sid: slots[sid] for _, _, sid in spans}
    # adjacent slots / too little fixed text -> too loose
    if re.search(r"\{[nt]\d+\}\s*\{[nt]\d+\}", template):
        return None
    if len(re.findall(r"[a-z]{2,}", re.sub(r"\{[nt]\d+\}", " ", template))) < 3:
        return None
    macro = {"id": "", "template": template, "slots": slots, "actions": acts, "example": norm,
             "added": date.today().isoformat(), "hits": 0}
    # replay must reproduce Claude's actions exactly
    if _instantiate(macro, norm) != actions:
        return None
    items = _load()
    if any(it["template"] == template for it in items):
        return None
    macro["id"] = f"macro-{max([int(i['id'].split('-')[1]) for i in items] + [0]) + 1}"
    items.append(macro)
    _save(items)
    return macro


def forget(macro_id):
    items = _load()
    keep = [it for it in items if it["id"] != macro_id]
    if len(keep) != len(items):
        _save(keep)
        return True
    return False
