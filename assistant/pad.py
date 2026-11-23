"""Button pad / dial support (built for the XPPen ACK05, works with any device that sends keys).

Configure the device in its driver so each button sends the combo listed in PAD_KEYS
(Ctrl+Alt+Shift+F1..F12 and Insert: combos nothing else uses). Single keys (e.g. "f20") also work. Remap in config.json under "pad": {"keys": {"b2": "f5", ...}}.

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

from .trigger import key_name, parse_combo

log = logging.getLogger("assistant")

_CSA = "ctrl+alt+shift+"
PAD_KEYS = {
    "b1": _CSA + "f1", "b2": _CSA + "f2", "b3": _CSA + "f3", "b4": _CSA + "f4", "b5": _CSA + "f5",
    "b6": _CSA + "f6", "b7": _CSA + "f7", "b8": _CSA + "f8", "b9": _CSA + "f9", "b10": _CSA + "f10",
    "dial_cw": _CSA + "f11", "dial_ccw": _CSA + "f12", "dial_press": _CSA + "insert",
}
MODS = {"ctrl", "alt", "shift", "cmd"}

# id -> (action list or None, name). b1 is voice; b7 is the scroll modifier (hold).
ACTIONS = {
    "b2": [{"type": "undo"}],  # with K7 held: redo (see VMOD_ACTIONS)
    "b4": [{"type": "record", "on": "toggle"}],
    "b5": [{"type": "metronome", "on": "toggle"}],
    "b6": [{"type": "loop", "on": "toggle"}],
    "b8": [{"type": "prev_cue"}],
    "b9": [{"type": "playpause"}],
    "b10": [{"type": "next_cue"}],
    "dial_press": [{"type": "osc", "address": "/live/song/set/current_song_time", "args": [0.0]}],
}

VMOD_ACTIONS = {"b2": [{"type": "redo"}]}

NAMES = {"b1": "K1", "b2": "K2", "b3": "K3", "b4": "K4", "b5": "K5", "b6": "K6", "b7": "K7",
         "b8": "K8", "b9": "K9", "b10": "K10", "dial_cw": "Dial CW", "dial_ccw": "Dial CCW",
         "dial_press": "Dial press"}


def label_for(pid, st):
    """(label, active) for a pad input given state st: playing, metronome, loop, record, listening, vmod."""
    if pid == "b1":
        return ("Listening..." if st.get("listening") else "Voice\n(hold)"), bool(st.get("listening"))
    if pid == "b2":
        return ("Redo" if st.get("vmod") else "Undo"), False
    if pid == "b3":
        return "That was\nWRONG", False
    if pid == "b4":
        return ("Stop\nrecording" if st.get("record") else "Record"), bool(st.get("record"))
    if pid == "b5":
        return ("Metronome\nON" if st.get("metronome") else "Metronome\nOFF"), bool(st.get("metronome"))
    if pid == "b6":
        return ("Loop\nON" if st.get("loop") else "Loop\nOFF"), bool(st.get("loop"))
    if pid == "b7":
        return "Hold:\nscroll\nup/down", bool(st.get("vmod"))
    if pid == "b8":
        return "Previous\nsection", False
    if pid == "b9":
        return ("Pause" if st.get("playing") else "Play"), bool(st.get("playing"))
    if pid == "b10":
        return "Next\nsection", False
    if pid == "dial_press":
        return "", False
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
    def _release_modifiers():
        """The pad's keys arrive as Ctrl+Alt+Shift+Fn; Live reads Alt+wheel as track height and
        Ctrl+wheel as zoom. Lift those modifiers so the wheel event is a plain scroll."""
        u = ctypes.windll.user32
        for vk in (0x11, 0x12, 0x10, 0xA2, 0xA3, 0xA4, 0xA5, 0xA0, 0xA1):  # ctrl, alt, shift (+L/R)
            if u.GetAsyncKeyState(vk) & 0x8000:
                u.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    @staticmethod
    def _send(amount, vertical):
        Scroller._release_modifiers()
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
                self.scroller.scroll(direction, vertical="b7" in self.pressed)
            except Exception:
                log.exception("scroll failed")
            return
        if repeat:
            return
        if pid == "b3":
            self.assistant.mark_wrong()
            return
        acts = (VMOD_ACTIONS.get(pid) if "b7" in self.pressed else None) or ACTIONS.get(pid)
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
