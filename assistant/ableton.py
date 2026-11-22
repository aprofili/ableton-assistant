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
        self.osc.send("/live/song/set/loop", 1 if a.get("on", True) else 0)

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

    def a_goto_cue(self, a):
        self.osc.send("/live/song/cue_point/jump", a["name"])

    def a_next_cue(self, a):
        self.osc.send("/live/song/jump_to_next_cue")

    def a_prev_cue(self, a):
        self.osc.send("/live/song/jump_to_prev_cue")

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

    def a_osc(self, a):
        self.osc.send(a["address"], *a.get("args", []))

    def a_key(self, a):
        if self.keys is None:
            raise RuntimeError("Key sending is not available")
        self.keys.press(a["keys"])

    def a_wait(self, a):
        time.sleep(min(float(a.get("seconds", 0.2)), 5.0))
