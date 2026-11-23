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
    "b2": [{"type": "tap_tempo"}],
    "b4": [{"type": "record", "on": "toggle"}],
    "b5": [{"type": "track_toggle", "prop": "mute"}],
    "b6": [{"type": "loop", "on": "toggle"}],
    "b7": [{"type": "key", "keys": "tab"}],  # Live: toggle Session / Arrangement view
    "b8": [{"type": "prev_cue"}],
    "b9": [{"type": "playstop"}],
    "b10": [{"type": "next_cue"}],
}

# with MOD held
MOD_ACTIONS = {
    "b2": [{"type": "metronome", "on": "toggle"}],
    "b4": [{"type": "session_record", "on": "toggle"}],
    "b5": [{"type": "track_toggle", "prop": "solo"}],
    "b6": [{"type": "punch_cycle"}],
    "b7": [{"type": "key", "keys": "shift+tab"}],  # Live: toggle Clip / Device detail view
    "b8": [{"type": "undo"}],
    "b9": [{"type": "playstop", "continue": True}],
    "b10": [{"type": "redo"}],
}
VMOD_ACTIONS = MOD_ACTIONS  # old name
# Buttons that, when held (without MOD) while turning the dial, change something instead of scrolling.
# A plain tap still runs the button's normal action (on release).
HOLD_SCROLL = {"b2": "tempo", "b9": "playhead", "b4": "track", "b5": "volume", "b7": "pan",
               "b6": "loop_move", "b8": "loop_start", "b10": "loop_end"}

NAMES = {"b1": "K1", "b2": "K2", "b3": "K3", "b4": "K4", "b5": "K5", "b6": "K6", "b7": "K7",
         "b8": "K8", "b9": "K9", "b10": "K10", "dial_cw": "Dial CW", "dial_ccw": "Dial CCW",
         "dial_press": "Dial press"}


# hold+dial wording, shown only while the button is held: kind -> (button title, cw, ccw, cw mod, ccw mod)
HOLD_LABELS = {
    "tempo": ("Tempo", "Tempo +1", "Tempo -1", "Tempo +5", "Tempo -5"),
    "playhead": ("Playhead", "Forward 1 bar", "Back 1 bar", "Forward 1 beat", "Back 1 beat"),
    "track": ("Select track", "Next track", "Previous track", "Next track", "Previous track"),
    "volume": ("Volume", "Louder", "Quieter", "Louder (big)", "Quieter (big)"),
    "pan": ("Pan", "Pan right", "Pan left", "Pan right (big)", "Pan left (big)"),
    "loop_move": ("Move loop", "Loop later 1 bar", "Loop earlier 1 bar", "Loop later 1 beat", "Loop earlier 1 beat"),
    "loop_start": ("Loop start", "Start later 1 bar", "Start earlier 1 bar", "Start later 1 beat", "Start earlier 1 beat"),
    "loop_end": ("Loop end", "End later 1 bar", "End earlier 1 bar", "End later 1 beat", "End earlier 1 beat"),
}


# short caption under the dial icon while a button is held: kind -> (normal, with MOD)
HOLD_CAPTION = {"tempo": ("\u00b11 BPM", "\u00b15 BPM"), "playhead": ("bar", "beat"), "track": ("track", "track"),
                "volume": ("2%", "10%"), "pan": ("5%", "25%"),
                "loop_move": ("bar", "beat"), "loop_start": ("bar", "beat"), "loop_end": ("bar", "beat")}


def icon_for(pid, st):
    """(icon name, caption) for a pad input; padmap draws the icon (text label is the fallback)."""
    mod = bool(st.get("vmod"))
    hold = HOLD_SCROLL.get(st.get("hold"))
    if hold:
        if pid == st["hold"]:
            return "h_" + hold, ""
        if pid in ("dial_cw", "dial_ccw"):
            return "scroll_h", HOLD_CAPTION[hold][1 if mod else 0]
    if pid == "b1":
        return ("wrong" if mod else "mic"), ""
    if pid == "b2":
        return ("metronome" if mod else "tap"), ""
    if pid == "b3":
        return "mod", ""
    if pid == "b4":
        if mod:
            return "rec_session", ""
        return ("stop" if st.get("record") else "rec"), ""
    if pid == "b5":
        return ("solo" if mod else "mute"), ""
    if pid == "b6":
        return ("punch" if mod else "loop"), ""
    if pid == "b7":
        return ("device" if mod else "views"), ""
    if pid == "b8":
        return ("undo" if mod else "prev"), ""
    if pid == "b9":
        if st.get("playing"):
            return "stop", ""
        return ("continue" if mod else "play"), ""
    if pid == "b10":
        return ("redo" if mod else "next"), ""
    if pid == "dial_press":
        return "spark", ""
    if pid in ("dial_cw", "dial_ccw"):
        return ("scroll_v" if mod else "scroll_h"), ""
    return "", ""


def label_for(pid, st):
    """(label, active) for a pad input given state st: playing, metronome, loop, record, listening,
    vmod (MOD held), count_in, punch_in, punch_out, session_record."""
    mod = bool(st.get("vmod"))
    hold = HOLD_SCROLL.get(st.get("hold"))
    if hold:
        lab = HOLD_LABELS[hold]
        if pid == st["hold"]:
            return lab[0], True
        if pid in ("dial_cw", "dial_ccw"):
            return lab[(1 if pid == "dial_cw" else 2) + (2 if mod else 0)], False
    if pid == "b1":
        if mod:
            return "That was\nWRONG", False
        return ("Listening" if st.get("listening") else "Voice"), bool(st.get("listening"))
    if pid == "b2":
        if mod:
            return ("Metronome\nON" if st.get("metronome") else "Metronome\nOFF"), bool(st.get("metronome"))
        return "Tap\ntempo", False
    if pid == "b3":
        return "MOD", mod
    if pid == "b4":
        if mod:
            return ("Stop session\nrecord" if st.get("session_record") else "Session\nrecord"), bool(st.get("session_record"))
        return ("Stop\nrecording" if st.get("record") else "Record"), bool(st.get("record"))
    if pid == "b5":
        return ("Solo\ntrack" if mod else "Mute\ntrack"), False
    if pid == "b6":
        if mod:
            pi, po = bool(st.get("punch_in")), bool(st.get("punch_out"))
            return "Punch\nIN %s\nOUT %s" % ("on" if pi else "off", "on" if po else "off"), pi or po
        return ("Loop\nON" if st.get("loop") else "Loop\nOFF"), bool(st.get("loop"))
    if pid == "b7":
        return ("Clip / Device\nview" if mod else "Session /\nArrangement"), False
    if pid == "b8":
        return ("Undo" if mod else "Previous\nsection"), False
    if pid == "b9":
        if mod:
            return ("Stop" if st.get("playing") else "Continue\nfrom stop"), bool(st.get("playing"))
        return ("Stop" if st.get("playing") else "Play"), bool(st.get("playing"))
    if pid == "b10":
        return ("Redo" if mod else "Next\nsection"), False
    if pid == "dial_press":
        return "Claude", bool(st.get("listening_claude"))
    if pid == "dial_cw":
        return ("Scroll down" if mod else "Scroll right"), False
    if pid == "dial_ccw":
        return ("Scroll up" if mod else "Scroll left"), False
    return "", False


# ---- mouse wheel -----------------------------------------------------------
class Scroller:
    """Sends wheel events to Live like a real wheel: one tick in, one notch out, no coasting.
    Ticks that sit in the queue longer than `stale` are dropped, so the scroll stops when the dial does.
    At the start of each burst, Live is focused and the cursor is parked on the arrangement/clip area,
    since Live scrolls whatever is under the cursor."""

    def __init__(self, auto_hover=True, step=120, max_mult=3, point=(0.5, 0.3), stale=0.15, idle=0.6):
        self.auto_hover = auto_hover
        self.step = step
        self.max_mult = max_mult
        self.point = point
        self.stale = stale
        self.idle = idle
        self._last = 0.0
        self._dir = 0
        self._mult = 1
        self._burst_end = 0.0

    def _mult_for(self, direction):
        """Mild speed-up for a fast spin; resets as soon as the dial slows or reverses."""
        now = time.time()
        if direction == self._dir and now - self._last < 0.04:
            self._mult = min(self._mult + 1, self.max_mult)
        else:
            self._mult = 1
        self._dir, self._last = direction, now
        return self._mult

    def scroll(self, direction, vertical):
        """direction: +1 = right / down, -1 = left / up. Returns immediately (hook thread must not block)."""
        if sys.platform != "win32":
            return False
        delta = self.step * self._mult_for(direction)
        if self._q is None:
            self._q = queue.Queue()
            threading.Thread(target=self._worker, daemon=True, name="pad-scroll").start()
        self._q.put((direction * delta, vertical, time.time()))
        return True

    _q = None
    _live = (0.0, None)

    def _worker(self):
        while True:
            amount, vertical, t0 = self._q.get()
            try:
                if time.time() - t0 > self.stale:
                    continue  # backlog from a stopped dial: drop it
                while True:  # merge ticks already waiting (same axis)
                    try:
                        a2, v2, t2 = self._q.get(timeout=0.004)
                    except queue.Empty:
                        break
                    if time.time() - t2 > self.stale:
                        continue
                    if v2 != vertical:
                        self._emit(amount, vertical)
                        amount, vertical = a2, v2
                    else:
                        amount += a2
                self._emit(amount, vertical)
            except Exception:
                log.exception("scroll failed")

    def _emit(self, amount, vertical):
        now = time.time()
        if now - self._burst_end > self.idle:
            ok = self._start_burst()
            log.info("scroll burst start (live window found: %s)", ok)
            if not ok:
                return
        self._burst_end = now
        self._send(-amount if vertical else amount, vertical)
        log.debug("scroll %s %s (%.0f ms)", amount, vertical, (time.time() - now) * 1000)

    def _start_burst(self):
        """Focus Live if needed and park the cursor on the arrangement area."""
        from .keys import ableton_in_front, focus_ableton
        if not self._live_hwnd():
            return False
        if not ableton_in_front():
            focus_ableton()
        if self.auto_hover:
            self._park()
        return True

    def _park(self):
        u = ctypes.windll.user32
        live = self._live_hwnd()

        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

        r = RECT()
        u.GetWindowRect(live, ctypes.byref(r))
        u.SetCursorPos(int(r.l + (r.r - r.l) * self.point[0]), int(r.t + (r.b - r.t) * self.point[1]))

    def _live_hwnd(self):
        from .keys import find_ableton_hwnd
        t, h = self._live
        now = time.time()
        if h and now - t < 3.0 and ctypes.windll.user32.IsWindow(h):
            return h
        h = find_ableton_hwnd()
        self._live = (now, h)
        return h

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
        self.scroller = Scroller(pc.get("auto_hover", True), pc.get("scroll_step", 120), pc.get("scroll_max_mult", 3),
                                 tuple(pc.get("scroll_point", (0.5, 0.3))))
        # "focus_and_act": a button press brings Live forward if needed, then runs.
        # "focus_only": the press that brings Live forward does nothing else.
        self.focus_mode = pc.get("focus_mode", "focus_and_act")
        self.pressed = set()
        self._stamp = {}
        self._hold = {}
        self._hold_btn = None   # button held for hold+dial (e.g. K5 = tempo)
        self._hold_used = False
        self._nq = None
        self._hid_seen = 0.0
        self._hid_state = 0
        self.mouse_mod = False  # MOD toggled by clicking the pad map (the physical pad holds MOD instead)
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
        st["vmod"] = self._mod()
        st["hold"] = self._hold_btn
        st["listening_claude"] = bool(getattr(self.assistant, "_to_claude", False))
        out = {}
        for pid in self.keys:
            label, active = label_for(pid, st)
            pr = pid in self.pressed or (pid == MOD and self.mouse_mod)
            icon, cap = icon_for(pid, st)
            out[pid] = {"label": label, "active": active, "pressed": pr, "key": self.keys[pid], "icon": icon, "caption": cap}
        out["_connected"] = self.live_ok
        last = getattr(self.assistant, "last", None)
        out["_last"] = f"Last: “{last['text']}”  ({last['source']})" if last else ""
        return out

    HID_BUTTONS = [f"b{i}" for i in range(1, 11)] + ["dial_press"]  # bit order in report bytes 2-3

    def hid_active(self):
        """True while the raw HID tap is delivering pad reports (then the driver's key combos are ignored)."""
        return time.time() - self._hid_seen < 30

    def hid_report(self, rep):
        """Raw pad report: [0x02, 0xf0, buttons lo, buttons hi, ..., dial at byte 7]."""
        if len(rep) < 8 or rep[0] != 2 or rep[1] != 0xF0:
            if len(rep) >= 2 and rep[0] == 2:
                self._hid_seen = time.time()  # heartbeat report
            return
        self._hid_seen = time.time()
        state = rep[2] | (rep[3] << 8)
        changed = state ^ self._hid_state
        self._hid_state = state
        for i, pid in enumerate(self.HID_BUTTONS):
            if not changed >> i & 1:
                continue
            down = bool(state >> i & 1)
            if down:
                self.pressed.add(pid)
            else:
                self.pressed.discard(pid)
            if pid == "b1":
                tr = getattr(self.assistant, "trigger", None)
                if tr:
                    tr.feed("hid_b1", down)
                if down and self._mod():
                    self.assistant.mark_wrong()
                if down:
                    self._q.put(None)
            elif pid == "dial_press":
                if down:
                    self._claude_toggle()
            elif pid in HOLD_SCROLL:
                if down:
                    if self._mod():
                        self.handle(pid)           # MOD+K5 etc. act immediately
                    else:
                        self._hold_btn, self._hold_used = pid, False
                elif self._hold_btn == pid:
                    if not self._hold_used:        # a tap, not a hold+dial: run the normal action
                        self.handle(pid)
                    self._hold_btn = None
            elif down:
                self.handle(pid)
        if rep[7] in (1, 2):
            pid = "dial_cw" if rep[7] == 1 else "dial_ccw"
            self.pressed.add(pid)
            threading.Timer(0.12, lambda: self.pressed.discard(pid)).start()
            self.handle(pid)

    def _mod(self):
        return MOD in self.pressed or self.mouse_mod

    def _claude_toggle(self):
        fn = getattr(self.assistant, "claude_dictate_toggle", None)
        if fn:
            threading.Thread(target=fn, daemon=True, name="claude-dictate").start()

    def click(self, pid):
        """Mouse click on the pad map: same action as the physical button. MOD toggles."""
        if pid == MOD:
            self.mouse_mod = not self.mouse_mod
            self._q.put(None)
            return
        if pid == "dial_press":
            self._claude_toggle()
            return
        if pid == "b1":
            a = self.assistant
            if self.mouse_mod:
                a.mark_wrong()
            elif a.state == "listening":
                a._on_stop()
            else:
                a._on_start()
            return
        self.handle(pid)

    # ---- input
    def _press(self, k):
        n = key_name(k)
        if n in MODS:
            self._mods.add(n)
            return
        pid = self.by_combo.get(frozenset(self._mods | {n}))
        if not pid or self.hid_active():
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

    def _nudge(self, delta, kind="tempo", coarse=False, src=""):
        """Hold+dial tempo steps: a worker merges ticks and applies them as whole BPM."""
        if self._nq is None:
            self._nq = queue.Queue()
            threading.Thread(target=self._nudge_worker, daemon=True, name="pad-nudge").start()
        self._nq.put((kind, delta, coarse, src))

    def _nudge_worker(self):
        while True:
            items = [self._nq.get()]
            try:
                while True:
                    try:
                        items.append(self._nq.get(timeout=0.005))
                    except queue.Empty:
                        break
                a = self.assistant.actions
                merged = {}
                for kind, d, coarse, src in items:
                    k = (kind, coarse, src)
                    merged[k] = merged.get(k, 0) + d
                for (kind, coarse, src), d in merged.items():
                    if a is None or not d:
                        continue
                    title, sub = a.hold_adjust(kind, d, coarse)
                    ov = getattr(self.assistant, "overlay", None)
                    if ov:
                        ov.result(True, title, sub or ("hold %s + turn dial" % src))
            except Exception as e:
                log.info("Hold+dial adjust failed: %s", e)

    def handle(self, pid, repeat=False):
        if pid in ("dial_cw", "dial_ccw"):
            direction = 1 if pid == "dial_cw" else -1
            if self._hold_btn:
                self._hold_used = True
                self._nudge(direction, HOLD_SCROLL[self._hold_btn], self._mod(), NAMES.get(self._hold_btn, ""))
                return
            try:
                self.scroller.scroll(direction, vertical=self._mod())
            except Exception:
                log.exception("scroll failed")
            return
        if repeat:
            return
        if pid == MOD:
            self._q.put(None)  # just bring Live forward
            return
        mod = self._mod()
        if pid == "b1":  # voice is handled by the trigger; MOD+K1 = "that was wrong"
            self._q.put(None)
            if mod:
                self.assistant.mark_wrong()
            return
        acts = (MOD_ACTIONS.get(pid) if mod else None) or ACTIONS.get(pid)
        self._q.put(acts)

    def _worker(self):
        while True:
            acts = self._q.get()
            a = self.assistant.actions
            try:
                from .keys import ableton_in_front, focus_ableton
                if not ableton_in_front():
                    focus_ableton()
                    if self.focus_mode == "focus_only":
                        continue
                if a is None or not acts:
                    continue
                self._optimistic(acts)
                a.note = None
                a.run(acts)
                if a.note:
                    ov = getattr(self.assistant, "overlay", None)
                    if ov:
                        ov.result(True, a.note[0], "selected track")
                threading.Timer(0.75, self._safe_refresh).start()  # confirm against Live once the hold has expired
            except Exception as e:
                log.info("Pad action failed: %s", e)
                self._safe_refresh()

    # ---- live state: pushed by Live (start_listen) for instant updates, polled slowly as a safety net
    _LISTEN = {"is_playing": "playing", "metronome": "metronome", "loop": "loop", "record_mode": "record",
               "session_record": "session_record", "count_in_duration": "count_in",
               "punch_in": "punch_in", "punch_out": "punch_out"}

    def _push(self, addr, args):
        if addr.startswith("/live/song/get/") and args:
            key = self._LISTEN.get(addr.rsplit("/", 1)[1])
            if key and time.time() >= self._hold.get(key, 0):
                # (during the hold after our own optimistic flip, replies to the action's own "is it playing?"
                # query also arrive here with the OLD value; ignore them, the refresh below confirms)
                self.live[key] = bool(args[0])
                self._stamp[key] = time.time()
                self.live_ok = True

    def _optimistic(self, acts):
        """Flip the displayed state right away; the real value from Live follows within a few ms."""
        before = dict(self.live)
        try:
            self._optimistic_flip(acts)
        finally:
            now = time.time()
            for k, v in self.live.items():
                if v != before.get(k):
                    self._stamp[k] = now
                    self._hold[k] = now + 0.6  # ignore polled (possibly stale) reads for this key meanwhile

    def _optimistic_flip(self, acts):
        for a in acts:
            t = a.get("type")
            if t in ("playstop", "playpause"):
                self.live["playing"] = not self.live["playing"]
            elif t == "loop" and a.get("on") == "toggle":
                self.live["loop"] = not self.live["loop"]
            elif t == "metronome" and a.get("on") == "toggle":
                self.live["metronome"] = not self.live["metronome"]
            elif t == "record" and a.get("on") == "toggle":
                self.live["record"] = not self.live["record"]
            elif t == "session_record" and a.get("on") == "toggle":
                self.live["session_record"] = not self.live["session_record"]
            elif t == "count_in_toggle":
                self.live["count_in"] = not self.live["count_in"]
            elif t == "punch_cycle":
                nxt = {(0, 0): (1, 0), (1, 0): (1, 1), (1, 1): (0, 1), (0, 1): (0, 0)}[
                    (int(self.live["punch_in"]), int(self.live["punch_out"]))]
                self.live["punch_in"], self.live["punch_out"] = bool(nxt[0]), bool(nxt[1])

    _unavailable = None

    def _safe_refresh(self):
        try:
            self._refresh()
        except Exception:
            pass

    def _refresh(self):
        osc = self.assistant.osc
        if osc is None:
            return
        if self._unavailable is None:
            self._unavailable = set()

        def q(prop, key):
            addr = "/live/song/get/" + prop
            if prop in self._unavailable:
                return self.live[key]
            try:
                return bool(osc.query(addr, timeout=0.4)[0])
            except TimeoutError:
                if prop == "is_playing":
                    raise
                self._unavailable.add(prop)  # e.g. count-in patch missing: don't wait on it again
                return False
        for prop, key in self._LISTEN.items():
            t0 = time.time()
            val = q(prop, key)
            # a push from Live or an optimistic flip since the query began wins over this (older) read
            if self._stamp.get(key, 0) < t0 and time.time() >= self._hold.get(key, 0):
                self.live[key] = val
        self.live_ok = True

    def _poll(self):
        subscribed, last_sub = None, 0.0
        while True:
            try:
                osc = self.assistant.osc
                if osc is not None:
                    if subscribed is not osc:
                        osc.listeners.append(self._push)
                        subscribed = osc
                    if time.time() - last_sub > 10:  # idempotent; survives Live reloading its scripts
                        osc.subscribe([p for p in self._LISTEN if p not in (self._unavailable or ())])
                        last_sub = time.time()
                self._refresh()
                time.sleep(1.5)
            except Exception:
                self.live_ok = False
                time.sleep(2.0)
