"""Button pad / dial support (built for the XPPen ACK05, works with any device that sends keys).

Configure the device in its driver so each button sends the key listed in PAD_KEYS (F13-F24 and
Pause: keys nothing else uses). Remap in config.json under "pad": {"keys": {"b2": "f5", ...}}.

Layout (reading order):          dial: rotate = scroll, press = go to start
  [b1][b2][b3][ b4 ]
  [b5][b6][b7][ tall]
  [b8][ b9 wide ][b10]

All actions here run locally through AbletonOSC (no Claude API).
"""
import ctypes
import logging
import queue
import sys
import threading
import time

from pynput import keyboard

from .trigger import key_name

log = logging.getLogger("assistant")

PAD_KEYS = {
    "b1": "f13", "b2": "f14", "b3": "f15", "b4": "f16", "b5": "f17", "b6": "f18",
    "b7": "f19", "b8": "f20", "b9": "f21", "b10": "f22",
    "dial_cw": "f23", "dial_ccw": "f24", "dial_press": "pause",
}

# id -> (action list or None, name). b1 is voice; b7 is the scroll modifier (hold).
ACTIONS = {
    "b2": [{"type": "undo"}],
    "b3": [{"type": "redo"}],
    "b4": [{"type": "record", "on": "toggle"}],
    "b5": [{"type": "metronome", "on": "toggle"}],
    "b6": [{"type": "loop", "on": "toggle"}],
    "b8": [{"type": "prev_cue"}],
    "b9": [{"type": "playpause"}],
    "b10": [{"type": "next_cue"}],
    "dial_press": [{"type": "osc", "address": "/live/song/set/current_song_time", "args": [0.0]}],
}

NAMES = {"b1": "K1", "b2": "K2", "b3": "K3", "b4": "K4", "b5": "K5", "b6": "K6", "b7": "K7",
         "b8": "K8", "b9": "K9", "b10": "K10", "dial_cw": "Dial CW", "dial_ccw": "Dial CCW",
         "dial_press": "Dial press"}


def label_for(pid, st):
    """(label, active) for a pad input given state st: playing, metronome, loop, record, listening, vmod."""
    if pid == "b1":
        return ("Listening..." if st.get("listening") else "Voice\n(hold)"), bool(st.get("listening"))
    if pid == "b2":
        return "Undo", False
    if pid == "b3":
        return "Redo", False
    if pid == "b4":
        return ("Stop\nrecording" if st.get("record") else "Record"), bool(st.get("record"))
    if pid == "b5":
        return ("Metronome\nON" if st.get("metronome") else "Metronome\nOFF"), bool(st.get("metronome"))
    if pid == "b6":
        return ("Loop\nON" if st.get("loop") else "Loop\nOFF"), bool(st.get("loop"))
    if pid == "b7":
        return "Hold:\nscroll up/down", bool(st.get("vmod"))
    if pid == "b8":
        return "Previous\nsection", False
    if pid == "b9":
        return ("Pause" if st.get("playing") else "Play"), bool(st.get("playing"))
    if pid == "b10":
        return "Next\nsection", False
    if pid == "dial_press":
        return "Go to\nstart", False
    if pid == "dial_cw":
        return ("Scroll down" if st.get("vmod") else "Scroll right"), False
    if pid == "dial_ccw":
        return ("Scroll up" if st.get("vmod") else "Scroll left"), False
    return "", False


# ---- mouse wheel -----------------------------------------------------------
class Scroller:
    """Sends wheel events to Live. Horizontal by default; vertical when the modifier is held.
    Fast turning accelerates so one flick can cross a whole project."""

    def __init__(self, auto_hover=True, step=120, max_mult=12):
        self.auto_hover = auto_hover
        self.step = step
        self.max_mult = max_mult
        self._last = 0.0
        self._dir = 0
        self._mult = 1

    def _mult_for(self, direction):
        now = time.time()
        if direction == self._dir and now - self._last < 0.12:
            self._mult = min(self._mult + 1, self.max_mult)
        else:
            self._mult = 1
        self._dir, self._last = direction, now
        return self._mult

    def scroll(self, direction, vertical):
        """direction: +1 = right / down, -1 = left / up."""
        if sys.platform != "win32":
            return False
        delta = self.step * self._mult_for(direction)
        if not self._over_live():
            return False
        self._send(-delta * direction if vertical else delta * direction, vertical)
        return True

    def _over_live(self):
        from .keys import find_ableton_hwnd
        u = ctypes.windll.user32
        live = find_ableton_hwnd()
        if not live:
            return False

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

        pt = POINT()
        u.GetCursorPos(ctypes.byref(pt))
        under = u.WindowFromPoint(pt)
        if under and u.GetAncestor(under, 2) == live:
            return True
        if not self.auto_hover:
            return False
        r = RECT()
        u.GetWindowRect(live, ctypes.byref(r))
        u.SetCursorPos(int(r.l + (r.r - r.l) * 0.6), int(r.t + (r.b - r.t) * 0.45))
        return True

    @staticmethod
    def _send(amount, vertical):
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT)]
            _anonymous_ = ("u",)
            _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

        flags = 0x0800 if vertical else 0x1000  # MOUSEEVENTF_WHEEL / MOUSEEVENTF_HWHEEL
        inp = INPUT(type=0, mi=MOUSEINPUT(0, 0, ctypes.c_ulong(int(amount) & 0xFFFFFFFF).value, flags, 0, None))
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


# ---- controller --------------------------------------------------------------
class PadController:
    def __init__(self, cfg, assistant):
        pc = cfg.get("pad", {})
        self.enabled = pc.get("enabled", True)
        self.keys = dict(PAD_KEYS)
        self.keys.update(pc.get("keys", {}))
        self.assistant = assistant
        self.by_key = {}
        for pid, k in self.keys.items():
            self.by_key[k.strip().lower()] = pid
        self.scroller = Scroller(pc.get("auto_hover", True))
        self.pressed = set()
        self.live = {"playing": False, "metronome": False, "loop": False, "record": False}
        self.live_ok = False
        self._q = queue.Queue()
        self._listener = None

    @property
    def voice_key(self):
        return self.keys["b1"]

    def start(self):
        if not self.enabled:
            return
        threading.Thread(target=self._worker, daemon=True, name="pad-actions").start()
        threading.Thread(target=self._poll, daemon=True, name="pad-poll").start()
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.daemon = True
        self._listener.start()
        log.info("Pad ready (voice key %s).", self.voice_key)

    # ---- state for the map window
    def snapshot(self):
        st = dict(self.live)
        st["listening"] = self.assistant.state == "listening"
        st["vmod"] = "b7" in self.pressed
        out = {}
        for pid in self.keys:
            label, active = label_for(pid, st)
            out[pid] = {"label": label, "active": active, "pressed": pid in self.pressed, "key": self.keys[pid]}
        out["_connected"] = self.live_ok
        return out

    # ---- input
    def _press(self, k):
        pid = self.by_key.get(key_name(k))
        if not pid:
            return
        repeat = pid in self.pressed
        self.pressed.add(pid)
        self.handle(pid, repeat)

    def _release(self, k):
        pid = self.by_key.get(key_name(k))
        if pid:
            self.pressed.discard(pid)

    def handle(self, pid, repeat=False):
        if pid in ("dial_cw", "dial_ccw"):
            direction = 1 if pid == "dial_cw" else -1
            try:
                self.scroller.scroll(direction, vertical="b7" in self.pressed)
            except Exception:
                log.exception("scroll failed")
            return
        if repeat:
            return
        acts = ACTIONS.get(pid)
        if acts:
            self._q.put(acts)

    def _worker(self):
        while True:
            acts = self._q.get()
            a = self.assistant.actions
            if a is None:
                continue
            try:
                a.run(acts)
                self._refresh()
            except Exception as e:
                log.info("Pad action failed: %s", e)

    # ---- live state polling
    def _refresh(self):
        osc = self.assistant.osc
        if osc is None:
            return
        q = lambda addr: bool(osc.query(addr, timeout=0.5)[0])
        self.live = {"playing": q("/live/song/get/is_playing"), "metronome": q("/live/song/get/metronome"),
                     "loop": q("/live/song/get/loop"), "record": q("/live/song/get/record_mode")}
        self.live_ok = True

    def _poll(self):
        while True:
            try:
                self._refresh()
                time.sleep(0.5)
            except Exception:
                self.live_ok = False
                time.sleep(2.0)
