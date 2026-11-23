"""Button pad / dial support (built for the XPPen ACK05, works with any device that sends keys).

Configure the device in its driver so each button sends the combo listed in PAD_KEYS
(Ctrl+Alt+Shift+F1..F12 and Insert: combos nothing else uses). Single keys (e.g. "f20") also work. Remap in config.json under "pad": {"keys": {"b2": "f5", ...}}.

Layout (reading order):          dial: rotate = scroll (vertical while MOD held)
  [b1][b2][b3=MOD][ b4 ]
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

from .trigger import key_name, parse_combo

log = logging.getLogger("assistant")

_CSA = "ctrl+alt+shift+"
PAD_KEYS = {
    "b1": _CSA + "f1", "b2": _CSA + "f2", "b3": _CSA + "f3", "b4": _CSA + "f4", "b5": _CSA + "f5",
    "b6": _CSA + "f6", "b7": _CSA + "f7", "b8": _CSA + "f8", "b9": _CSA + "f9", "b10": _CSA + "f10",
    "dial_cw": _CSA + "f11", "dial_ccw": _CSA + "f12", "dial_press": _CSA + "insert",
}
MODS = {"ctrl", "alt", "shift", "cmd"}

MOD = "b3"  # hold: modifier for every other input

# id -> actions. K1 is voice (mod: "that was wrong"), K3 is the modifier itself.
ACTIONS = {
    "b2": [{"type": "undo"}],
    "b4": [{"type": "record", "on": "toggle"}],
    "b5": [{"type": "metronome", "on": "toggle"}],
    "b6": [{"type": "loop", "on": "toggle"}],
    "b7": [{"type": "key", "keys": "tab"}],  # Live: toggle Session / Arrangement view
    "b8": [{"type": "prev_cue"}],
    "b9": [{"type": "playstop"}],
    "b10": [{"type": "next_cue"}],
}

# with MOD held
MOD_ACTIONS = {
    "b2": [{"type": "redo"}],
    "b4": [{"type": "session_record", "on": "toggle"}],
    "b5": [{"type": "count_in_toggle"}],
    "b6": [{"type": "punch_cycle"}],
    "b7": [{"type": "key", "keys": "shift+tab"}],  # Live: toggle Clip / Device detail view
    "b8": [{"type": "goto_start"}],
    "b9": [{"type": "playstop", "continue": True}],
    "b10": [{"type": "goto_end"}],
}
VMOD_ACTIONS = MOD_ACTIONS  # old name

NAMES = {"b1": "K1", "b2": "K2", "b3": "K3", "b4": "K4", "b5": "K5", "b6": "K6", "b7": "K7",
         "b8": "K8", "b9": "K9", "b10": "K10", "dial_cw": "Dial CW", "dial_ccw": "Dial CCW",
         "dial_press": "Dial press"}


def label_for(pid, st):
    """(label, active) for a pad input given state st: playing, metronome, loop, record, listening,
    vmod (MOD held), count_in, punch_in, punch_out, session_record."""
    mod = bool(st.get("vmod"))
    if pid == "b1":
        if mod:
            return "That was\nWRONG", False
        return ("Listening..." if st.get("listening") else "Voice\n(hold)"), bool(st.get("listening"))
    if pid == "b2":
        return ("Redo" if mod else "Undo"), False
    if pid == "b3":
        return "MOD\n(hold)", mod
    if pid == "b4":
        if mod:
            return ("Stop session\nrecord" if st.get("session_record") else "Session\nrecord"), bool(st.get("session_record"))
        return ("Stop\nrecording" if st.get("record") else "Record"), bool(st.get("record"))
    if pid == "b5":
        if mod:
            return ("Count-in\nON" if st.get("count_in") else "Count-in\nOFF"), bool(st.get("count_in"))
        return ("Metronome\nON" if st.get("metronome") else "Metronome\nOFF"), bool(st.get("metronome"))
    if pid == "b6":
        if mod:
            pi, po = bool(st.get("punch_in")), bool(st.get("punch_out"))
            return "Punch\nIN %s\nOUT %s" % ("on" if pi else "off", "on" if po else "off"), pi or po
        return ("Loop\nON" if st.get("loop") else "Loop\nOFF"), bool(st.get("loop"))
    if pid == "b7":
        return ("Clip / Device\nview" if mod else "Session /\nArrangement"), False
    if pid == "b8":
        return ("Go to\nstart" if mod else "Previous\nsection"), False
    if pid == "b9":
        if mod:
            return ("Stop" if st.get("playing") else "Continue\nfrom stop"), bool(st.get("playing"))
        return ("Stop" if st.get("playing") else "Play"), bool(st.get("playing"))
    if pid == "b10":
        return ("Go to\nend" if mod else "Next\nsection"), False
    if pid == "dial_press":
        return "", False
    if pid == "dial_cw":
        return ("Scroll down" if mod else "Scroll right"), False
    if pid == "dial_ccw":
        return ("Scroll up" if mod else "Scroll left"), False
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
        """direction: +1 = right / down, -1 = left / up. Returns immediately: the keyboard hook thread
        must never block (window enumeration + SendInput there made scrolling lag), so the work is
        queued to a worker that merges ticks that arrive together into one wheel event."""
        if sys.platform != "win32":
            return False
        delta = self.step * self._mult_for(direction)
        if self._q is None:
            self._q = queue.Queue()
            threading.Thread(target=self._worker, daemon=True, name="pad-scroll").start()
        self._q.put((direction * delta, vertical))
        return True

    _q = None
    _live = (0.0, None)

    def _worker(self):
        while True:
            amount, vertical = self._q.get()
            try:
                while True:  # merge everything already waiting (same axis)
                    try:
                        a2, v2 = self._q.get(timeout=0.004)
                    except queue.Empty:
                        break
                    if v2 != vertical:
                        self._emit(amount, vertical)
                        amount, vertical = a2, v2
                    else:
                        amount += a2
                self._emit(amount, vertical)
            except Exception:
                log.exception("scroll failed")

    def _emit(self, amount, vertical):
        if not self._over_live():
            return
        self._send(-amount if vertical else amount, vertical)

    def _live_hwnd(self):
        from .keys import find_ableton_hwnd
        t, h = self._live
        now = time.time()
        if h and now - t < 3.0 and ctypes.windll.user32.IsWindow(h):
            return h
        h = find_ableton_hwnd()
        self._live = (now, h)
        return h

    def _over_live(self):
        u = ctypes.windll.user32
        live = self._live_hwnd()
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
        from .keys import release_held_modifiers
        release_held_modifiers()
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
        self.by_combo = {parse_combo(k): pid for pid, k in self.keys.items()}
        self._mods = set()
        self._down = {}  # key name -> pid, so release works even if modifiers go up first
        self.scroller = Scroller(pc.get("auto_hover", True))
        self.pressed = set()
        self.live = {"playing": False, "metronome": False, "loop": False, "record": False,
                     "session_record": False, "count_in": False, "punch_in": False, "punch_out": False}
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
        st["vmod"] = MOD in self.pressed
        out = {}
        for pid in self.keys:
            label, active = label_for(pid, st)
            out[pid] = {"label": label, "active": active, "pressed": pid in self.pressed, "key": self.keys[pid]}
        out["_connected"] = self.live_ok
        last = getattr(self.assistant, "last", None)
        out["_last"] = f"Last: “{last['text']}”  ({last['source']})" if last else ""
        return out

    # ---- input
    def _press(self, k):
        n = key_name(k)
        if n in MODS:
            self._mods.add(n)
            return
        pid = self.by_combo.get(frozenset(self._mods | {n}))
        if not pid:
            return
        self._down[n] = pid
        repeat = pid in self.pressed
        self.pressed.add(pid)
        self.handle(pid, repeat)

    def _release(self, k):
        n = key_name(k)
        if n in MODS:
            self._mods.discard(n)
            return
        pid = self._down.pop(n, None)
        if pid:
            self.pressed.discard(pid)

    def handle(self, pid, repeat=False):
        if pid in ("dial_cw", "dial_ccw"):
            direction = 1 if pid == "dial_cw" else -1
            try:
                self.scroller.scroll(direction, vertical=MOD in self.pressed)
            except Exception:
                log.exception("scroll failed")
            return
        if repeat:
            return
        if pid == MOD:
            return
        mod = MOD in self.pressed
        if pid == "b1":  # voice is handled by the trigger; MOD+K1 = "that was wrong"
            if mod:
                self.assistant.mark_wrong()
            return
        acts = (MOD_ACTIONS.get(pid) if mod else None) or ACTIONS.get(pid)
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
        def q(addr, default=False):
            try:
                return bool(osc.query(addr, timeout=0.5)[0])
            except TimeoutError:
                if addr.endswith("is_playing"):
                    raise
                return default  # property unavailable (e.g. count-in patch missing)
        self.live = {"playing": q("/live/song/get/is_playing"), "metronome": q("/live/song/get/metronome"),
                     "loop": q("/live/song/get/loop"), "record": q("/live/song/get/record_mode"),
                     "session_record": q("/live/song/get/session_record"),
                     "count_in": q("/live/song/get/count_in_duration"),
                     "punch_in": q("/live/song/get/punch_in"), "punch_out": q("/live/song/get/punch_out")}
        self.live_ok = True

    def _poll(self):
        while True:
            try:
                self._refresh()
                time.sleep(0.5)
            except Exception:
                self.live_ok = False
                time.sleep(2.0)
