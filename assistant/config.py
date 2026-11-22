import copy
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "config.default.json")
USER_PATH = os.path.join(ROOT, "config.json")


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load():
    with open(DEFAULT_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.path.exists(USER_PATH):
        with open(USER_PATH, encoding="utf-8") as f:
            cfg = _merge(cfg, json.load(f))
    return cfg


def save_user(**updates):
    """Persist overrides (e.g. input_device, trigger) to config.json."""
    cur = {}
    if os.path.exists(USER_PATH):
        with open(USER_PATH, encoding="utf-8") as f:
            cur = json.load(f)
    _merge(cur, copy.deepcopy(updates))
    with open(USER_PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
