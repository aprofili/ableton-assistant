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
                      "metronome": 0, "loop": 0, "tempo": 120.0, "current_song_time": 0.0}
        self.cues = []  # [name, time]
        self.reply = SimpleUDPClient("127.0.0.1", recv_port)
        d = Dispatcher()
        d.set_default_handler(self._on)
        self.server = ThreadingOSCUDPServer(("127.0.0.1", send_port), d)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _on(self, addr, *args):
        self.received.append((addr, *args))
        if addr == "/live/test":
            self.reply.send_message(addr, ["ok"])
        elif addr == "/live/song/get/cue_points":
            self.reply.send_message(addr, [x for c in sorted(self.cues, key=lambda c: c[1]) for x in c])
        elif addr == "/live/song/cue_point/add_or_delete":
            t = self.props["current_song_time"]
            hit = [c for c in self.cues if abs(c[1] - t) < 1e-3]
            if hit:
                self.cues.remove(hit[0])
            else:
                self.cues.append(["marker", t])
        elif addr == "/live/song/cue_point/set/name":
            sorted(self.cues, key=lambda c: c[1])[args[0]][0] = args[1]
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
        self.assertIsNone(self.r("go to the section i called bridge and play it"))


class ExecutorTests(unittest.TestCase):
    def run_cmd(self, text, num=4, den=4, cfg=None, setup=None, keep_live=False):
        send_port, recv_port = 21000, 21001
        live = MockLive(send_port, recv_port, num, den)
        if setup:
            setup(live)
        osc = AbletonOSC("127.0.0.1", send_port, recv_port)
        try:
            Actions(osc, cfg or {}).run(router.route(text, shortcuts_mod.Shortcuts())[0])
            time.sleep(0.2)
            sent = [m for m in live.received if "/get/" not in m[0] and m[0] != "/live/test"]
            return (sent, live) if keep_live else sent
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


class SectionTests(unittest.TestCase):
    def test_router_markers(self):
        sc = shortcuts_mod.Shortcuts()
        self.assertEqual(router.route("Make a section marker saying verse at measure 10.", sc)[0],
                         [{"type": "add_section", "bar": 10, "name": "Verse"}])
        self.assertEqual(router.route("add a locator called pre chorus at bar 17", sc)[0],
                         [{"type": "add_section", "bar": 17, "name": "Pre Chorus"}])
        self.assertEqual(router.route("create a marker at bar 5 named bridge", sc)[0],
                         [{"type": "add_section", "bar": 5, "name": "Bridge"}])
        self.assertEqual(router.route("name this section chorus", sc)[0],
                         [{"type": "name_section", "name": "Chorus"}])

    def test_add_section_creates_names_and_restores_playhead(self):
        sent, live = ExecutorTests().run_cmd("make a section marker saying verse at measure 10", keep_live=True)
        self.assertEqual(live.cues, [["Verse", 36.0]])
        self.assertEqual(live.props["current_song_time"], 0.0)  # restored

    def test_add_section_renames_existing(self):
        def setup(live):
            live.cues.append(["old", 36.0])
        sent, live = ExecutorTests().run_cmd("make a section marker saying verse at measure 10", setup=setup, keep_live=True)
        self.assertEqual(live.cues, [["Verse", 36.0]])

    def test_name_section_uses_preceding_locator(self):
        def setup(live):
            live.cues.extend([["a", 0.0], ["b", 16.0], ["c", 32.0]])
            live.props["current_song_time"] = 20.0
        sent, live = ExecutorTests().run_cmd("name this section chorus", setup=setup, keep_live=True)
        self.assertEqual(sorted(live.cues, key=lambda c: c[1]), [["a", 0.0], ["Chorus", 16.0], ["c", 32.0]])

    def test_name_section_creates_when_none_precedes(self):
        def setup(live):
            live.props["current_song_time"] = 17.0  # bar 5
        sent, live = ExecutorTests().run_cmd("name this section chorus", setup=setup, keep_live=True)
        self.assertEqual(live.cues, [["Chorus", 16.0]])


class ClaudeApiTests(unittest.TestCase):
    def test_prompt_builds_with_literal_braces(self):
        from assistant import claude_api
        out = claude_api.build_system([{"phrases": ["save"], "keys": "ctrl+s"}], {"tempo": 120})
        self.assertIn("set_loop{start_bar,end_bar}", out)
        self.assertIn('"tempo": 120', out)
        self.assertNotIn("{known}", out)

    def test_ask_parses_tool_call(self):
        import sys
        import types
        from assistant import claude_api

        captured = {}

        class Block:
            type = "tool_use"
            input = {"actions": [{"type": "goto_bar", "bar": 3}]}

        class Messages:
            def create(self, **kw):
                captured.update(kw)
                return types.SimpleNamespace(content=[Block()])

        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda **kw: types.SimpleNamespace(messages=Messages())
        old = sys.modules.get("anthropic")
        sys.modules["anthropic"] = fake
        os.environ["ANTHROPIC_API_KEY"] = "test"
        try:
            self.assertEqual(claude_api.ask("go to three", {}, []), [{"type": "goto_bar", "bar": 3}])
            self.assertEqual(captured["tool_choice"]["name"], "perform_actions")
        finally:
            if old is None:
                del sys.modules["anthropic"]
            else:
                sys.modules["anthropic"] = old


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
