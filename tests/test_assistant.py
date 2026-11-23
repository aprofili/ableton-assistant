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
        self.tracks = ["Vocals", "Guitar"]
        self.selected = 1
        self.volume = 0.5
        self.meter = 0.4
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
        elif addr == "/live/song/get/track_names":
            self.reply.send_message(addr, list(self.tracks))
        elif addr == "/live/song/get/num_tracks":
            self.reply.send_message(addr, [len(self.tracks)])
        elif addr == "/live/song/create_audio_track":
            self.tracks.append("1 Audio")
        elif addr == "/live/view/get/selected_track":
            self.reply.send_message(addr, [self.selected])
        elif addr == "/live/track/get/volume":
            self.reply.send_message(addr, [args[0], self.volume])
        elif addr in ("/live/track/get/output_meter_level", "/live/master/get/output_meter_level"):
            self.reply.send_message(addr, ([args[0], self.meter] if args else [self.meter]))
        elif addr == "/live/track/get/available_input_routing_types":
            self.reply.send_message(addr, [args[0], "Ext. In", "No Input"])
        elif addr == "/live/track/get/available_input_routing_channels":
            self.reply.send_message(addr, [args[0], "1/2", "3/4", "5"])
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


class PadTests(unittest.TestCase):
    def _pad_mod(self):
        import sys
        import types
        try:
            import pynput  # noqa: F401
        except ImportError:
            kb = types.ModuleType("pynput.keyboard")
            kb.Key = type("Key", (), {})
            kb.Listener = object
            pk = types.ModuleType("pynput")
            pk.keyboard = kb
            sys.modules.update({"pynput": pk, "pynput.keyboard": kb})
        from assistant import pad
        return pad

    def test_labels_follow_state(self):
        pad = self._pad_mod()
        self.assertEqual(pad.label_for("b9", {"playing": True})[0], "Stop")
        self.assertEqual(pad.label_for("b9", {"playing": False})[0], "Play")
        self.assertEqual(pad.label_for("b9", {"vmod": True})[0], "Continue\nfrom stop")
        self.assertTrue(pad.label_for("b2", {"vmod": True, "metronome": True})[1])
        self.assertEqual(pad.label_for("b5", {})[0], "Mute\ntrack")
        self.assertEqual(pad.label_for("b5", {"vmod": True})[0], "Solo\ntrack")
        self.assertEqual(pad.label_for("b1", {"vmod": True})[0], "That was\nWRONG")
        self.assertEqual(pad.label_for("dial_cw", {"vmod": True})[0], "Scroll down")
        self.assertEqual(pad.label_for("dial_cw", {})[0], "Scroll right")

    def test_buttons_run_osc(self):
        pad = self._pad_mod()
        live = MockLive(21010, 21011)
        osc = AbletonOSC("127.0.0.1", 21010, 21011)
        try:
            act = Actions(osc, {})
            for pid in ("b9", "b6", "b4"):
                act.run(pad.ACTIONS[pid])
            act.run(pad.ACTIONS["b2"])         # K2 = tap tempo
            act.run(pad.MOD_ACTIONS["b8"])     # MOD+K8 = undo
            act.run(pad.MOD_ACTIONS["b9"])     # stopped + MOD -> continue
            live.props["is_playing"] = 1
            act.run(pad.ACTIONS["b9"])         # playing -> stop
            act.run(pad.MOD_ACTIONS["b4"])     # session record on
            for _ in range(4):                 # punch cycle
                act.run(pad.MOD_ACTIONS["b6"])
            act.run(pad.MOD_ACTIONS["b10"])    # MOD+K10 = redo
            time.sleep(0.3)
            sent = [m for m in live.received if "/get/" not in m[0] and m[0] != "/live/test"]
            self.assertEqual(sent, [
                ("/live/song/start_playing",), ("/live/song/set/loop", 1), ("/live/song/set/record_mode", 1),
                ("/live/song/tap_tempo",), ("/live/song/undo",), ("/live/song/continue_playing",), ("/live/song/stop_playing",),
                ("/live/song/set/session_record", 1),
                ("/live/song/set/punch_in", 1), ("/live/song/set/punch_out", 0),
                ("/live/song/set/punch_in", 1), ("/live/song/set/punch_out", 1),
                ("/live/song/set/punch_in", 0), ("/live/song/set/punch_out", 1),
                ("/live/song/set/punch_in", 0), ("/live/song/set/punch_out", 0),
                ("/live/song/redo",)])
        finally:
            osc.close()
            live.close()

    def test_updater_applies_zip_and_protects_user_files(self):
        import io
        import zipfile
        from assistant import updater
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "assistant"))
            for rel, txt in (("assistant/a.py", "old"), ("config.json", "mine"), ("requirements.txt", "x"),
                             ("data/learned_shortcuts.json", "learned")):
                os.makedirs(os.path.join(root, os.path.dirname(rel)), exist_ok=True)
                open(os.path.join(root, rel), "w").write(txt)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("aprofili-ableton-assistant-abc/assistant/a.py", "new")
                z.writestr("aprofili-ableton-assistant-abc/config.json", "OVERWRITE")
                z.writestr("aprofili-ableton-assistant-abc/data/learned_shortcuts.json", "OVERWRITE")
                z.writestr("aprofili-ableton-assistant-abc/requirements.txt", "y")
                z.writestr("aprofili-ableton-assistant-abc/new.txt", "n")
            bk = os.path.join(root, ".update_backup")
            changed = updater.apply_zip(buf.getvalue(), root, bk)
            self.assertTrue(changed)
            self.assertEqual(open(os.path.join(root, "assistant/a.py")).read(), "new")
            self.assertEqual(open(os.path.join(root, "config.json")).read(), "mine")
            self.assertEqual(open(os.path.join(root, "data/learned_shortcuts.json")).read(), "learned")
            self.assertEqual(open(os.path.join(root, "new.txt")).read(), "n")
            self.assertEqual(open(os.path.join(bk, "assistant/a.py")).read(), "old")
            self.assertTrue(updater._vt("v1.10.0") > updater._vt("1.9.9"))
        finally:
            shutil.rmtree(root)

    def _with_live(self, port, fn):
        live = MockLive(port, port + 1)
        osc = AbletonOSC("127.0.0.1", port, port + 1)
        try:
            return fn(live, osc)
        finally:
            osc.close()
            live.close()

    def test_track_volume_by_name_and_selected(self):
        def go(live, osc):
            act = Actions(osc, {})
            act.run(router.route("turn up the vocals by 4 db", shortcuts_mod.Shortcuts())[0])
            act.run(router.route("turn it down", shortcuts_mod.Shortcuts())[0])
            time.sleep(0.2)
            return [m for m in live.received if m[0] == "/live/track/set/volume"]
        sent = self._with_live(21020, go)
        self.assertEqual(sent[0][1], 0)
        self.assertAlmostEqual(sent[0][2], 0.6)
        self.assertEqual(sent[1][1], 1)
        self.assertAlmostEqual(sent[1][2], 0.45)

    def test_check_levels_reports_clipping(self):
        def go(live, osc):
            reports = []
            act = Actions(osc, {})
            act.report = lambda m, ok=True: reports.append((m, ok))
            live.props["is_playing"] = 1
            live.meter = 0.95
            act.run([{"type": "check_levels", "seconds": 0.3}])
            live.meter = 0.4
            act.run([{"type": "check_levels", "seconds": 0.3}])
            return reports
        r = self._with_live(21030, go)
        self.assertTrue(r[0][0].startswith("Clipping") and not r[0][1])
        self.assertTrue(r[1][0].startswith("No clipping") and r[1][1])

    def test_new_input_track(self):
        def go(live, osc):
            Actions(osc, {}).run(router.route("create a new audio track called vocals from mic 3", shortcuts_mod.Shortcuts())[0])
            time.sleep(0.2)
            return [m for m in live.received if "/set/" in m[0] or "create" in m[0]]
        sent = self._with_live(21040, go)
        self.assertIn(("/live/track/set/name", 2, "Vocals"), sent)
        self.assertIn(("/live/track/set/arm", 2, 1), sent)
        self.assertIn(("/live/track/set/input_routing_type", 2, "Ext. In"), sent)
        self.assertIn(("/live/track/set/input_routing_channel", 2, "3/4"), sent)

    def test_play_from_loop_start(self):
        sc = shortcuts_mod.Shortcuts()
        self.assertEqual(router.route("play from the start of my loop", sc)[0], [{"type": "goto_loop_start"}, {"type": "play"}])
        self.assertEqual(router.route("play from the start", sc)[0], [{"type": "goto_bar", "bar": 1}, {"type": "play"}])
        self.assertEqual(router.route("go to the start", sc)[0], [{"type": "goto_bar", "bar": 1}])

    def test_feedback_marks_phrase_bad(self):
        import tempfile
        from assistant import feedback
        old = feedback.DIR
        feedback.DIR = tempfile.mkdtemp()
        try:
            last = {"text": "play from the start of my loop", "source": "local", "actions": [{"type": "play"}], "before": {}}
            e = feedback.record(last, {"tempo": 120}, "play from the start of my loop", "x", screenshot=False)
            self.assertEqual(e["verdict"], "wrong")
            self.assertEqual(feedback.bad_for("play from the start of my loop"), [[{"type": "play"}]])
            self.assertEqual(feedback.bad_for("other"), [])
        finally:
            shutil.rmtree(feedback.DIR)
            feedback.DIR = old

    def test_modifier_and_scroll_dispatch(self):
        pad = self._pad_mod()
        calls = []

        class Asst:
            state = "idle"
            actions = osc = None

        pc = pad.PadController({"pad": {"keys": {"b2": "f5"}}}, Asst())
        pc.scroller.scroll = lambda d, vertical: calls.append((d, vertical))
        self.assertEqual(pc.by_combo[frozenset({"f5"})], "b2")
        pc.handle("dial_cw")
        pc.pressed.add("b3")
        pc.handle("dial_ccw")
        self.assertEqual(calls, [(1, False), (-1, True)])
        self.assertEqual(pc.voice_key, "ctrl+alt+shift+f1")
        pad.key_name = lambda k: k
        C, A, S = "ctrl", "alt", "shift"
        pc2 = pad.PadController({}, Asst())
        pc2.handle = lambda pid, repeat=False: calls.append(pid)
        for k in (C, A, S, "f3"):
            pc2._press(k)
        for k in (C, A, S):  # modifiers up before the key
            pc2._release(k)
        self.assertIn("b3", pc2.pressed)
        pc2._release("f3")
        self.assertNotIn("b3", pc2.pressed)
        self.assertEqual(calls[-1], "b3")
        pc2._press("f3")  # bare F3 must not trigger
        self.assertEqual(calls[-1], "b3")
        self.assertEqual(len(calls), 3)


    def test_hid_reports(self):
        pad = self._pad_mod()

        class Asst:
            state = "idle"
            actions = osc = trigger = None

        pc = pad.PadController({}, Asst())
        calls = []
        pc.handle = lambda pid, repeat=False: calls.append(pid)
        rep = lambda lo=0, hi=0, dial=0: bytes([2, 0xF0, lo, hi, 0, 0, 0, dial, 0, 0, 0, 0])
        pc.hid_report(rep(lo=0x02))      # K2
        pc.hid_report(rep())
        pc.hid_report(rep(hi=0x01))      # K9
        pc.hid_report(rep())
        pc.hid_report(rep(hi=0x04))      # dial press: no action
        pc.hid_report(rep(dial=1))
        pc.hid_report(rep(dial=2))
        self.assertEqual(calls, ["b2", "b9", "dial_cw", "dial_ccw"])
        self.assertTrue(pc.hid_active())


    def test_hold_labels_and_adjust(self):
        pad = self._pad_mod()
        self.assertEqual(pad.label_for("dial_cw", {})[0], "Scroll right")
        self.assertEqual(pad.label_for("dial_cw", {"hold": "b9"})[0], "Forward 1 bar")
        self.assertEqual(pad.label_for("dial_ccw", {"hold": "b9", "vmod": True})[0], "Back 1 beat")
        self.assertEqual(pad.label_for("b9", {"hold": "b9"}), ("Playhead\n(turn dial)", True))
        self.assertEqual(pad.label_for("b4", {"hold": "b9"})[0], "Record")

        class Osc:
            def __init__(self):
                self.v = {"signature_numerator": 4, "signature_denominator": 4, "current_song_time": 6.0,
                          "loop_start": 8.0, "loop_length": 16.0}
                self.sent = []

            def query(self, addr, *a, timeout=0):
                return (self.v[addr.rsplit("/", 1)[1]],)

            def send(self, addr, *a):
                self.sent.append((addr,) + a)
        o = Osc()
        act = Actions(o, {})
        self.assertEqual(act.hold_adjust("playhead", 1)[0], "Bar 3.1")      # 6 -> next bar line (8)
        self.assertEqual(act.hold_adjust("playhead", -1)[0], "Bar 2.1")     # 6 -> bar line 4
        self.assertEqual(act.hold_adjust("playhead", 1, True)[0], "Bar 2.4")  # next beat: 7
        act.hold_adjust("loop_end", 1)
        self.assertEqual(o.sent[-1], ("/live/song/set/loop_length", 20.0))
        act.hold_adjust("loop_start", 1)
        self.assertEqual(o.sent[-2:], [("/live/song/set/loop_start", 12.0), ("/live/song/set/loop_length", 12.0)])
        act.hold_adjust("loop_move", -1)
        self.assertEqual(o.sent[-2], ("/live/song/set/loop_start", 4.0))

    def test_hold_k2_dial_changes_tempo_tap_toggles(self):
        pad = self._pad_mod()

        class Asst:
            state = "idle"
            actions = osc = trigger = None

        pc = pad.PadController({}, Asst())
        calls, nudges = [], []
        pc.handle = lambda pid, repeat=False: calls.append(pid)
        pc._nudge = lambda d, kind="tempo", coarse=False, src="": nudges.append(d)
        rep = lambda lo=0, hi=0, dial=0: bytes([2, 0xF0, lo, hi, 0, 0, 0, dial, 0, 0, 0, 0])
        pc.hid_report(rep(lo=0x02))         # K2 down: nothing yet
        self.assertEqual(calls, [])
        pc.hid_report(rep())                # tap -> taps tempo on release
        self.assertEqual(calls, ["b2"])
        pc.hid_report(rep(lo=0x02))
        pc.handle = pad.PadController.handle.__get__(pc)  # real handle for the dial branch
        pc.hid_report(rep(lo=0x02, dial=1))
        pc.hid_report(rep(lo=0x02, dial=2))
        pc.hid_report(rep())                # release after scrolling: no toggle
        self.assertEqual(nudges, [1, -1])
        self.assertEqual(calls, ["b2"])


class MacroTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from assistant import macros
        self.m = macros
        self.old = macros.STORE
        macros.STORE = os.path.join(tempfile.mkdtemp(), "m.json")

    def tearDown(self):
        self.m.STORE = self.old

    def test_learn_generalizes_numbers_and_names(self):
        from assistant import router
        norm = router.normalize("Please set a flag at bar 13 and title it drum loop.")
        got = self.m.learn(norm, [{"type": "add_section", "bar": 13, "name": "drum loop"}])
        self.assertIsNotNone(got)
        hit = self.m.match(router.normalize("set a flag at bar twenty one and title it verse"))
        self.assertEqual(hit[1], [{"type": "add_section", "bar": 21, "name": "verse"}])
        self.assertIsNone(self.m.match(router.normalize("set a flag at bar 5")))

    def test_ambiguous_or_loose_not_learned(self):
        self.assertIsNone(self.m.learn("go to bar 4 bar 4", [{"type": "goto_bar", "bar": 4}]))  # number twice
        self.assertIsNone(self.m.learn("do it 4", [{"type": "goto_bar", "bar": 4}]))  # too little fixed text
        self.assertIsNone(self.m.learn("make a marker at bar 3 called chorus",
                                       [{"type": "add_section", "bar": 3, "name": "Course"}]))  # name not heard

    def test_forget_and_dedupe(self):
        norm = "set the loop from 5 to 9"
        acts = [{"type": "set_loop", "start_bar": 5, "end_bar": 9}]
        mac = self.m.learn(norm, acts)
        self.assertIsNone(self.m.learn(norm, acts))
        self.assertEqual(self.m.match("set the loop from 2 to 3")[1][0]["end_bar"], 3)
        self.assertTrue(self.m.forget(mac["id"]))
        self.assertIsNone(self.m.match("set the loop from 2 to 3"))

    def test_section_with_and_call_it_is_local(self):
        from assistant import router
        acts, src = router.route("Create a section marker at bar 13 and call it drum loop.")
        self.assertEqual(src, "local")
        self.assertEqual(acts, [{"type": "add_section", "bar": 13, "name": "Drum Loop"}])


if __name__ == "__main__":
    unittest.main()
