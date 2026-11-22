"""Offline tests: router + executor against a mock AbletonOSC server. Run: python -m unittest"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from assistant import router, shortcuts as shortcuts_mod
from assistant.ableton import AbletonOSC, Actions


class MockLive:
    """Stands in for AbletonOSC: records sets, answers gets."""

    def __init__(self, send_port, recv_port, numerator=4, denominator=4):
        self.received = []
        self.props = {"signature_numerator": numerator, "signature_denominator": denominator,
                      "metronome": 0, "loop": 0, "tempo": 120.0}
        self.reply = SimpleUDPClient("127.0.0.1", recv_port)
        d = Dispatcher()
        d.set_default_handler(self._on)
        self.server = ThreadingOSCUDPServer(("127.0.0.1", send_port), d)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _on(self, addr, *args):
        self.received.append((addr, *args))
        if addr == "/live/test":
            self.reply.send_message(addr, ["ok"])
        elif addr.startswith("/live/song/get/"):
            self.reply.send_message(addr, [self.props.get(addr.rsplit("/", 1)[1], 0)])
        elif addr.startswith("/live/song/set/"):
            self.props[addr.rsplit("/", 1)[1]] = args[0]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.sc = shortcuts_mod.Shortcuts()

    def r(self, text):
        return router.route(text, self.sc)[0]

    def test_first_test_command(self):
        got = self.r("Create a loop region from measures 5 to 9, turn on the metronome and press play.")
        self.assertEqual(got, [
            {"type": "set_loop", "start_bar": 5, "end_bar": 9},
            {"type": "metronome", "on": True},
            {"type": "play"},
        ])

    def test_number_words_and_and(self):
        got = self.r("loop bars five and nine")
        self.assertEqual(got, [{"type": "set_loop", "start_bar": 5, "end_bar": 9}])

    def test_metronome_variants(self):
        self.assertEqual(self.r("turn off the metronome"), [{"type": "metronome", "on": False}])
        self.assertEqual(self.r("metronome on"), [{"type": "metronome", "on": True}])
        self.assertEqual(self.r("metronome"), [{"type": "metronome", "on": "toggle"}])

    def test_transport(self):
        self.assertEqual(self.r("stop"), [{"type": "stop"}])
        self.assertEqual(self.r("hey claude, play"), [{"type": "play"}])
        self.assertEqual(self.r("play from bar 17"), [{"type": "goto_bar", "bar": 17}, {"type": "play"}])
        self.assertEqual(self.r("go to the start"), [{"type": "goto_bar", "bar": 1}])

    def test_count_in_and_sections(self):
        self.assertEqual(self.r("change the count in to two measures"), [{"type": "set_count_in", "bars": 2}])
        self.assertEqual(self.r("next section"), [{"type": "next_cue"}])
        self.assertEqual(self.r("previous section"), [{"type": "prev_cue"}])

    def test_shortcut_registry(self):
        self.assertEqual(self.r("new midi track"), [{"type": "key", "keys": "ctrl+shift+t"}])
        self.assertEqual(self.r("save"), [{"type": "key", "keys": "ctrl+s"}])

    def test_needs_claude(self):
        self.assertIsNone(self.r("loop the first half of the chorus and play"))
        self.assertIsNone(self.r("name this section bridge"))


class ExecutorTests(unittest.TestCase):
    def run_cmd(self, text, num=4, den=4, cfg=None):
        send_port, recv_port = 21000, 21001
        live = MockLive(send_port, recv_port, num, den)
        osc = AbletonOSC("127.0.0.1", send_port, recv_port)
        try:
            Actions(osc, cfg or {}).run(router.route(text, shortcuts_mod.Shortcuts())[0])
            time.sleep(0.2)
            return [m for m in live.received if "/get/" not in m[0] and m[0] != "/live/test"]
        finally:
            osc.close()
            live.close()

    def test_loop_5_to_9_metronome_play(self):
        sent = self.run_cmd("create a loop region from measures 5 to 9, turn on the metronome and press play")
        self.assertEqual(sent, [
            ("/live/song/set/loop_start", 16.0),
            ("/live/song/set/loop_length", 16.0),
            ("/live/song/set/loop", 1),
            ("/live/song/set/metronome", 1),
            ("/live/song/start_playing",),
        ])

    def test_three_four_time(self):
        sent = self.run_cmd("loop bars 3 to 5", num=3, den=4)
        self.assertEqual(sent[0], ("/live/song/set/loop_start", 6.0))
        self.assertEqual(sent[1], ("/live/song/set/loop_length", 6.0))

    def test_inclusive_option(self):
        sent = self.run_cmd("loop bars 5 to 9", cfg={"bar_range_inclusive": True})
        self.assertEqual(sent[1], ("/live/song/set/loop_length", 20.0))

    def test_metronome_toggle_reads_state(self):
        sent = self.run_cmd("metronome")
        self.assertEqual(sent, [("/live/song/set/metronome", 1)])


class LearnTests(unittest.TestCase):
    def test_learn_adds_and_matches(self):
        tmp = tempfile.mkdtemp()
        old = (shortcuts_mod.LEARNED, shortcuts_mod.DOC)
        shortcuts_mod.LEARNED = os.path.join(tmp, "learned.json")
        shortcuts_mod.DOC = os.path.join(tmp, "SHORTCUTS.md")
        try:
            sc = shortcuts_mod.Shortcuts()
            self.assertIsNone(sc.match("freeze track"))
            self.assertTrue(sc.learn("ctrl+alt+f", ["freeze track", "freeze this track"], "Freeze track"))
            self.assertEqual(sc.match("freeze track")["keys"], "ctrl+alt+f")
            self.assertFalse(sc.learn("ctrl+alt+f", ["freeze track"]))
            self.assertIn("freeze track", open(shortcuts_mod.DOC).read())
            self.assertEqual(router.route("freeze track", sc)[0], [{"type": "key", "keys": "ctrl+alt+f"}])
        finally:
            shortcuts_mod.LEARNED, shortcuts_mod.DOC = old
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
