"""AbletonOSC client plus the action executor.

AbletonOSC (https://github.com/ideoforms/AbletonOSC) listens on UDP 11000 and
replies on UDP 11001. Times are in beats (quarter notes), 0-indexed.
"""
import threading
import time

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


class AbletonOSC:
    def __init__(self, host="127.0.0.1", send_port=11000, recv_port=11001):
        self.client = SimpleUDPClient(host, send_port)
        self._replies = {}
        self._events = {}
        self._qlock = threading.RLock()
        disp = Dispatcher()
        disp.set_default_handler(self._on_reply)
        self.server = ThreadingOSCUDPServer((host, recv_port), disp)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _on_reply(self, addr, *args):
        self._replies[addr] = args
        ev = self._events.get(addr)
        if ev:
            ev.set()

    def send(self, addr, *args):
        self.client.send_message(addr, list(args))

    def query(self, addr, *args, timeout=1.5):
        with self._qlock:  # voice thread and pad poller share the reply table
            ev = threading.Event()
            self._events[addr] = ev
            self._replies.pop(addr, None)
            self.send(addr, *args)
            if not ev.wait(timeout):
                raise TimeoutError(
                    f"No reply from Ableton for {addr}. Is AbletonOSC enabled as a "
                    "Control Surface in Live's Preferences > Link, Tempo & MIDI?"
                )
            return self._replies[addr]

    def ping(self):
        try:
            self.query("/live/test")
            return True
        except TimeoutError:
            return False

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Actions:
    """Executes action dicts: {"type": "set_loop", "start_bar": 5, "end_bar": 9}."""

    def __init__(self, osc, config, keys=None):
        self.osc = osc
        self.cfg = config
        self.keys = keys  # KeySender or None
        self.report = lambda msg, ok=True: None  # set by the service: shows a popup

    # ---- helpers -------------------------------------------------------
    def beats_per_bar(self):
        num = self.osc.query("/live/song/get/signature_numerator")[0]
        den = self.osc.query("/live/song/get/signature_denominator")[0]
        return float(num) * 4.0 / float(den)

    def bar_to_beats(self, bar, bpb=None):
        bpb = bpb or self.beats_per_bar()
        return (float(bar) - 1.0) * bpb

    def state(self):
        """Snapshot for the Claude fallback."""
        q = self.osc.query
        bpb = self.beats_per_bar()
        cues = q("/live/song/get/cue_points")
        sections = [
            {"name": cues[i], "bar": round(cues[i + 1] / bpb + 1, 3)}
            for i in range(0, len(cues) - 1, 2)
        ]
        loop_start = q("/live/song/get/loop_start")[0]
        loop_len = q("/live/song/get/loop_length")[0]
        return {
            "tempo": q("/live/song/get/tempo")[0],
            "beats_per_bar": bpb,
            "is_playing": bool(q("/live/song/get/is_playing")[0]),
            "metronome": bool(q("/live/song/get/metronome")[0]),
            "loop_on": bool(q("/live/song/get/loop")[0]),
            "loop_start_bar": loop_start / bpb + 1,
            "loop_end_bar": (loop_start + loop_len) / bpb + 1,
            "position_bar": q("/live/song/get/current_song_time")[0] / bpb + 1,
            "sections": sections,
        }

    def _cues(self):
        flat = self.osc.query("/live/song/get/cue_points")
        return [(flat[i], float(flat[i + 1])) for i in range(0, len(flat) - 1, 2)]

    def _cue_index_at(self, beats):
        for i, (_, t) in enumerate(self._cues()):
            if abs(t - beats) < 1e-3:
                return i
        return None

    # ---- execution -----------------------------------------------------
    def run(self, actions):
        for a in actions:
            fn = getattr(self, "a_" + a["type"], None)
            if fn is None:
                raise ValueError(f"Unknown action type: {a['type']}")
            fn(a)

    def a_set_loop(self, a):
        bpb = self.beats_per_bar()
        start, end = float(a["start_bar"]), float(a["end_bar"])
        if self.cfg.get("bar_range_inclusive"):
            end += 1
        if end <= start:
            raise ValueError(f"Loop end bar {end} must be after start bar {start}")
        self.osc.send("/live/song/set/loop_start", self.bar_to_beats(start, bpb))
        self.osc.send("/live/song/set/loop_length", (end - start) * bpb)
        self.osc.send("/live/song/set/loop", 1)

    def a_loop(self, a):
        on = a.get("on", True)
        if on == "toggle":
            on = not bool(self.osc.query("/live/song/get/loop")[0])
        self.osc.send("/live/song/set/loop", 1 if on else 0)

    def a_playpause(self, a):
        """Playing -> stop (playhead stays). Stopped -> continue from where it stopped."""
        if bool(self.osc.query("/live/song/get/is_playing")[0]):
            self.osc.send("/live/song/stop_playing")
        else:
            self.osc.send("/live/song/continue_playing")

    def a_playstop(self, a):
        """Playing -> stop. Stopped -> play from the start marker, or (continue=True) from where it stopped."""
        if bool(self.osc.query("/live/song/get/is_playing")[0]):
            self.osc.send("/live/song/stop_playing")
        elif a.get("continue"):
            self.osc.send("/live/song/continue_playing")
        else:
            self.osc.send("/live/song/start_playing")

    def a_session_record(self, a):
        on = a.get("on", "toggle")
        if on == "toggle":
            on = not bool(self.osc.query("/live/song/get/session_record")[0])
        self.osc.send("/live/song/set/session_record", 1 if on else 0)

    def a_count_in_toggle(self, a):
        """Count-in off <-> 1 bar (other lengths are left alone when turning off)."""
        cur = int(self.osc.query("/live/song/get/count_in_duration")[0])
        self.osc.send("/live/song/set/count_in_duration", 0 if cur else 1)

    def a_punch_cycle(self, a):
        """Cycle (in, out): off/off -> in on -> in+out on -> in off (out on) -> off/off."""
        pin = bool(self.osc.query("/live/song/get/punch_in")[0])
        pout = bool(self.osc.query("/live/song/get/punch_out")[0])
        nxt = {(False, False): (True, False), (True, False): (True, True),
               (True, True): (False, True), (False, True): (False, False)}[(pin, pout)]
        self.osc.send("/live/song/set/punch_in", 1 if nxt[0] else 0)
        self.osc.send("/live/song/set/punch_out", 1 if nxt[1] else 0)

    def a_goto_start(self, a):
        self.osc.send("/live/song/set/current_song_time", 0.0)

    def a_goto_end(self, a):
        self.osc.send("/live/song/set/current_song_time", float(self.osc.query("/live/song/get/song_length")[0]))

    def a_record(self, a):
        on = a.get("on", "toggle")
        if on == "toggle":
            on = not bool(self.osc.query("/live/song/get/record_mode")[0])
        self.osc.send("/live/song/set/record_mode", 1 if on else 0)

    def a_metronome(self, a):
        on = a.get("on", "toggle")
        if on == "toggle":
            on = not bool(self.osc.query("/live/song/get/metronome")[0])
        self.osc.send("/live/song/set/metronome", 1 if on else 0)

    def a_play(self, a):
        self.osc.send("/live/song/start_playing")

    def a_continue(self, a):
        self.osc.send("/live/song/continue_playing")

    def a_stop(self, a):
        self.osc.send("/live/song/stop_playing")

    def a_goto_bar(self, a):
        self.osc.send("/live/song/set/current_song_time", self.bar_to_beats(a["bar"]))

    def a_goto_loop_start(self, a):
        self.osc.send("/live/song/set/current_song_time", self.osc.query("/live/song/get/loop_start")[0])

    def a_goto_cue(self, a):
        self.osc.send("/live/song/cue_point/jump", a["name"])

    def a_next_cue(self, a):
        self.osc.send("/live/song/jump_to_next_cue")

    def a_prev_cue(self, a):
        self.osc.send("/live/song/jump_to_prev_cue")

    def a_add_section(self, a):
        """Create (or rename) a locator at the start of a bar. Playhead is restored afterwards."""
        bpb = self.beats_per_bar()
        t = self.bar_to_beats(a["bar"], bpb)
        idx = self._cue_index_at(t)
        if idx is None:
            prev = self.osc.query("/live/song/get/current_song_time")[0]
            self.osc.send("/live/song/set/current_song_time", t)
            time.sleep(0.15)
            self.osc.send("/live/song/cue_point/add_or_delete")  # toggles a locator at the playhead
            time.sleep(0.15)
            self.osc.send("/live/song/set/current_song_time", prev)
            idx = self._cue_index_at(t)
            if idx is None:
                raise RuntimeError(f"Couldn't create a locator at bar {a['bar']}")
        self.osc.send("/live/song/cue_point/set/name", idx, str(a["name"]))

    def a_name_section(self, a):
        bpb = self.beats_per_bar()
        pos = self.osc.query("/live/song/get/current_song_time")[0]
        prior = [i for i, (_, t) in enumerate(self._cues()) if t <= pos + 1e-3]
        if prior:
            self.osc.send("/live/song/cue_point/set/name", prior[-1], str(a["name"]))
        else:
            self.a_add_section({"bar": int(pos // bpb) + 1, "name": a["name"]})

    def a_set_count_in(self, a):
        # Live's Song.count_in_duration: 0 none, 1 = 1 bar, 2 = 2 bars, 3 = 4 bars.
        # Requires the count_in_duration patch applied by scripts/install.ps1.
        bars = int(a["bars"])
        value = {0: 0, 1: 1, 2: 2, 4: 3}.get(bars)
        if value is None:
            raise ValueError("Count-in must be 0, 1, 2 or 4 bars")
        self.osc.send("/live/song/set/count_in_duration", value)

    def a_set_tempo(self, a):
        self.osc.send("/live/song/set/tempo", float(a["bpm"]))

    def a_undo(self, a):
        self.osc.send("/live/song/undo")

    def a_redo(self, a):
        self.osc.send("/live/song/redo")

    # ---- tracks / levels (RØDECaster workflow) -------------------------
    def _track_names(self):
        return list(self.osc.query("/live/song/get/track_names"))

    def _track_index(self, ref):
        """ref: track name (loose match), 'selected'/None, or an int index."""
        if isinstance(ref, int):
            return ref
        if ref in (None, "", "selected", "this", "it", "this track", "current"):
            return int(self.osc.query("/live/view/get/selected_track")[0])
        names = self._track_names()
        want = str(ref).strip().lower()
        for i, n in enumerate(names):
            if n.lower() == want:
                return i
        for i, n in enumerate(names):
            if want in n.lower() or n.lower() in want:
                return i
        raise ValueError(f"No track matching '{ref}'")

    def a_track_volume(self, a):
        """Raise/lower a track's fader by db (near 0 dB, one dB is ~0.025 of the fader range)."""
        idx = self._track_index(a.get("track"))
        cur = float(self.osc.query("/live/track/get/volume", idx)[-1])
        new = max(0.0, min(1.0, cur + float(a.get("db", 2)) * 0.025))
        self.osc.send("/live/track/set/volume", idx, new)

    def a_check_levels(self, a):
        """Sample every track's output meter while playing; report anything at/over the clip threshold."""
        secs = min(float(a.get("seconds", 3)), 15.0)
        thr = float((self.cfg.get("rode") or {}).get("clip_threshold", 0.85))  # fader scale: 0.85 ~ 0 dBFS
        if not bool(self.osc.query("/live/song/get/is_playing")[0]):
            self.report("Levels: nothing is playing", False)
            return
        names = self._track_names()
        peaks = {n: 0.0 for n in names + ["Master"]}
        end = time.time() + secs
        while time.time() < end:
            for i, n in enumerate(names):
                peaks[n] = max(peaks[n], float(self.osc.query("/live/track/get/output_meter_level", i, timeout=0.5)[-1]))
            peaks["Master"] = max(peaks["Master"], float(self.osc.query("/live/master/get/output_meter_level", timeout=0.5)[-1]))
            time.sleep(0.05)
        hot = [n for n, p in peaks.items() if p >= thr]
        if hot:
            self.report("Clipping: " + ", ".join(hot), False)
        else:
            top = max(peaks, key=peaks.get)
            self.report(f"No clipping (loudest: {top})", True)

    def a_new_input_track(self, a):
        """Create an armed audio track, optionally named, with its input set to an external channel."""
        self.osc.send("/live/song/create_audio_track", -1)
        time.sleep(0.3)
        idx = int(self.osc.query("/live/song/get/num_tracks")[0]) - 1
        if a.get("name"):
            self.osc.send("/live/track/set/name", idx, str(a["name"]))
        self.osc.send("/live/track/set/arm", idx, 1)
        self.osc.send("/live/view/set/selected_track", idx)
        rc = self.cfg.get("rode") or {}
        types = [str(t) for t in self.osc.query("/live/track/get/available_input_routing_types", idx)[1:]]
        want = rc.get("input_type", "Ext. In")
        if want in types:
            self.osc.send("/live/track/set/input_routing_type", idx, want)
            time.sleep(0.15)
        ch = a.get("channel")
        if ch is None:
            return
        chans = [str(c) for c in self.osc.query("/live/track/get/available_input_routing_channels", idx)[1:]]
        mapped = (rc.get("channels") or {}).get(str(ch))
        pick = mapped if mapped in chans else None
        if pick is None:
            import re as _re
            pick = next((c for c in chans if c == str(ch)), None) or \
                next((c for c in chans if _re.search(r"(?<!\d)" + _re.escape(str(ch)) + r"(?!\d)", c)), None)
        if pick is None:
            raise ValueError(f"Input channel {ch} not found. Live offers: {chans}. "
                             "Map it in config.json: rode.channels {\"%s\": \"<name>\"}" % ch)
        self.osc.send("/live/track/set/input_routing_channel", idx, pick)

    def a_osc(self, a):
        self.osc.send(a["address"], *a.get("args", []))

    def a_key(self, a):
        if self.keys is None:
            raise RuntimeError("Key sending is not available")
        self.keys.press(a["keys"])

    def a_wait(self, a):
        time.sleep(min(float(a.get("seconds", 0.2)), 5.0))
