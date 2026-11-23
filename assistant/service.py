"""The voice service: trigger -> mic -> Whisper -> router/Claude -> Ableton. No UI; the tray (or console) drives it."""
import logging
import subprocess
import sys
import threading
import time

from . import config as cfgmod
from .ableton import AbletonOSC, Actions
from .app import beep, handle_text
from .shortcuts import Shortcuts
from .overlay import Overlay
from .pad import PadController
from .padmap import PadMap
from .pad import MOD as MOD_KEY

log = logging.getLogger("assistant")
_mutex = None


def single_instance():
    """True if we're the only instance (Windows named mutex); always True elsewhere."""
    global _mutex
    if sys.platform != "win32":
        return True
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\AbletonVoiceAssistant")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


class Assistant:
    def __init__(self, cfg, on_state=None, notify=None):
        self.cfg = cfg
        self.on_state = on_state or (lambda s: None)
        self._notify = notify or (lambda msg: None)
        self.state = "loading"  # loading | idle | listening | working | error
        self.enabled = True
        self.ready = False
        self.busy = threading.Lock()
        self._recording = False
        self.osc = self.actions = self.rec = self.stt = self.trigger = None
        self.shortcuts = Shortcuts()
        ov = cfg.get("overlay", {})
        self.overlay = Overlay(ov.get("opacity", 0.85), ov.get("enabled", True))
        self.overlay.level_fn = lambda: self.rec.level if self.rec else 0.0
        self._api_active = False
        self.last = None
        self.update_status = ""
        self.pad = PadController(cfg, self)
        self.padmap = PadMap(self.pad, cfg)

    # ---- helpers -------------------------------------------------------
    def set_state(self, s):
        self.state = s
        self.on_state(s)

    def notify(self, msg, level="info"):
        mode = self.cfg.get("notifications", "errors")
        if mode == "off" or (level == "info" and mode != "all"):
            return
        self._notify(msg)

    def start(self):
        self.overlay.start()
        threading.Thread(target=self._boot, daemon=True).start()

    def _boot(self):
        try:
            from .audio import Recorder, resolve_device
            from .stt import Transcriber
            from .trigger import Trigger

            o = self.cfg["osc"]
            self.osc = AbletonOSC(o["host"], o["send_port"], o["recv_port"])
            try:
                from .keys import KeySender
                keys = KeySender()
            except Exception:
                keys = None
            self.actions = Actions(self.osc, self.cfg, keys)
            self.actions.report = lambda msg, ok=True: self.overlay.api_done(ok, msg)
            try:
                device = resolve_device(self.cfg["input_device"])
            except RuntimeError as e:
                log.info("%s - using the system default mic", e)
                self.notify("Saved microphone not found; using the system default.", "error")
                device = None
            self.rec = Recorder(device, self.cfg["silence_seconds"], self.cfg["max_record_seconds"])
            if not self.osc.ping():
                log.info("WARNING: no reply from Ableton. Enable AbletonOSC in Live's Preferences > Link, Tempo & MIDI.")
                self.notify("No reply from Ableton. Is AbletonOSC enabled in Live's preferences?", "error")
            log.info("Loading speech model (%s)...", self.cfg["whisper"]["model"])
            w = self.cfg["whisper"]
            self.stt = Transcriber(w["model"], w["device"], w["compute_type"])
            self.stt.warm_up()
            t = self.cfg["trigger"]
            self.trigger = Trigger(t["keys"], t["mode"], self._on_start, self._on_stop)
            if self.pad.enabled:
                self.trigger.add_combo(self.pad.voice_key, suppress=lambda: MOD_KEY in self.pad.pressed)
                self.pad.start()
                self.padmap.restore()
            self.ready = True
            from . import updater
            updater.confirm()
            threading.Thread(target=self._update_loop, daemon=True, name="updater").start()
            self.set_state("idle")
            log.info("Ready. Trigger: %s (%s). Mic: %s.", t["keys"], t["mode"], self.cfg["input_device"] or "system default")
            self.trigger.run()
        except Exception as e:
            log.exception("Service failed to start")
            self.set_state("error")
            self.notify(f"Failed to start: {e}", "error")

    # ---- recording flow ------------------------------------------------
    def _on_start(self):
        if not self.enabled or not self.ready:
            self._recording = False
            return
        self._recording = True
        beep(self.cfg, "start")
        self.set_state("listening")
        self.overlay.listening()
        mode = self.trigger.mode
        if mode == "tap":
            self.rec.on_auto_stop = self.trigger.stop_from_outside
        try:
            self.rec.start(endpoint=(mode == "tap"))
        except Exception as e:
            self._recording = False
            log.info("ERROR: can't open the microphone: %s", e)
            self.notify(f"Can't open the microphone: {e}", "error")
            beep(self.cfg, "fail")
            self.overlay.hide()
            self.set_state("idle")

    def _on_stop(self):
        if not self._recording:
            return
        self._recording = False
        audio = self.rec.stop()
        self.overlay.hide()
        self.set_state("working")
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _process(self, audio):
        text = ""
        with self.busy:
            try:
                t0 = time.time()
                text = self.stt.transcribe(audio)
                log.info("heard %r (%.2fs)", text, time.time() - t0)
                if not text:
                    return
                ok = handle_text(text, self.cfg, self.actions, self.shortcuts,
                                 notify=lambda m: self.notify(m), on_event=self._on_event)
                beep(self.cfg, "ok" if ok else "fail")
                if ok and getattr(ok, "source", None):
                    self.last = {"text": text, "source": ok.source, "actions": ok.actions,
                                 "before": ok.before, "ts": time.time()}
                if ok:
                    self.notify(f"“{text}”")
                else:
                    self.notify(f"Not understood: “{text}”", "error")
            except Exception as e:
                log.info("ERROR: %s", e)
                if self._api_active:
                    self._api_active = False
                    self.overlay.api_done(False, str(e))
                beep(self.cfg, "fail")
                self.notify(f"“{text}” failed: {e}", "error")
            finally:
                self.set_state("idle")

    def _on_event(self, kind, info):
        if kind == "api_start":
            self._api_active = True
            self.overlay.api_start(info)
        elif kind == "api_done":
            self._api_active = False
            self.overlay.api_done(True, info)

    # ---- updates -------------------------------------------------------
    def _update_loop(self):
        time.sleep(45)
        while True:
            if self.cfg.get("updates", {}).get("auto", True):
                self.check_updates(auto=True)
            time.sleep(max(1, self.cfg.get("updates", {}).get("check_hours", 6)) * 3600)

    def check_updates(self, auto=False):
        from . import updater
        try:
            found = updater.check()
        except Exception as e:
            log.info("Update check failed: %s", e)
            self.update_status = "Update check failed"
            if not auto:
                self._notify(f"Update check failed: {e}")
            return
        if not found:
            self.update_status = "Up to date"
            if not auto:
                self._notify("Already up to date.")
            return
        tag, url = found
        self.update_status = f"Updating to {tag}"
        # wait until no command is in flight and nothing is being recorded
        for _ in range(120):
            if not self._recording and not self.busy.locked():
                break
            time.sleep(1)
        try:
            with self.busy:
                updater.install(tag, url)
        except Exception as e:
            log.info("Update to %s failed: %s", tag, e)
            self.update_status = "Update failed"
            self._notify(f"Update to {tag} failed: {e}")
            return
        self._notify(f"Updated to {tag}. Restarting...")
        time.sleep(1.5)
        updater.restart()

    def mark_wrong(self):
        """Save feedback on the last voice command (what was heard, what ran, state, log, screenshot)."""
        def work():
            from . import feedback
            from .router import normalize
            last = self.last
            if not last:
                self._notify("No voice command to give feedback on yet.")
                return
            try:
                now = self.actions.state() if self.actions else None
            except Exception:
                now = None
            from . import __version__
            feedback.record(last, now, normalize(last["text"]), __version__,
                            self.cfg.get("pad", {}).get("feedback_screenshot", True))
            log.info("FEEDBACK: marked wrong: %r -> %s", last["text"], last["actions"])
            beep(self.cfg, "fail")
            self.overlay.api_done(False, f"Noted as wrong: “{last['text']}”")
            self._notify(f"Saved feedback on “{last['text']}”")
        threading.Thread(target=work, daemon=True).start()

    # ---- settings changed from the tray --------------------------------
    def set_input_device(self, spec):
        from .audio import resolve_device
        cfgmod.save_user(input_device=spec)
        self.cfg["input_device"] = spec
        if self.rec is not None and not self._recording:
            try:
                self.rec.device = resolve_device(spec)
            except RuntimeError as e:
                self.notify(str(e), "error")

    def set_trigger_mode(self, mode):
        cfgmod.save_user(trigger={"mode": mode})
        self.cfg["trigger"]["mode"] = mode
        if self.trigger:
            self.trigger.mode = mode

    def learn_trigger(self):
        """Capture the next key/button press and make it the trigger."""
        def work():
            from .trigger import learn_combo, parse_combo
            self.enabled = False
            try:
                self._notify("Press the key or button you want to use as the trigger (20 s).")
                combo = learn_combo(timeout=20)
                if not combo:
                    self._notify("No key detected; trigger unchanged.")
                    return
                cfgmod.save_user(trigger={"keys": combo})
                self.cfg["trigger"]["keys"] = combo
                if self.trigger:
                    self.trigger.combo = parse_combo(combo)
                self._notify(f"Trigger set to: {combo}")
            finally:
                self.enabled = True
        threading.Thread(target=work, daemon=True).start()

    def check_ableton(self):
        ok = bool(self.osc and self.osc.ping())
        self._notify("Connected to Ableton." if ok else
                     "No reply from Ableton. Enable AbletonOSC in Live's Preferences > Link, Tempo & MIDI.")
        return ok


def open_in_notepad(path):
    subprocess.Popen(["notepad.exe", path], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
