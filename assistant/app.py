import argparse
import json
import logging
import os
import sys
import threading
import time

from . import config as cfgmod
from . import router
from .ableton import AbletonOSC, Actions
from .shortcuts import Shortcuts

log = logging.getLogger("assistant")


def setup_logging():
    os.makedirs(os.path.join(cfgmod.ROOT, "logs"), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    log.setLevel(logging.INFO)
    from logging.handlers import RotatingFileHandler
    handlers = [RotatingFileHandler(os.path.join(cfgmod.ROOT, "logs", "assistant.log"),
                                    maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stdout is not None:  # pythonw.exe has no stdout
        handlers.insert(0, logging.StreamHandler(sys.stdout))
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.propagate = False


_TONES = {}


def _tone_wav(freq, ms, rate=44100):
    """In-memory mono 16-bit WAV of a sine tone with short fades (cached)."""
    key = (freq, ms)
    if key not in _TONES:
        import io
        import math
        import struct
        import wave
        n = int(rate * ms / 1000)
        fade = max(1, int(rate * 0.005))
        frames = bytearray()
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            frames += struct.pack("<h", int(9000 * env * math.sin(2 * math.pi * freq * i / rate)))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        _TONES[key] = buf.getvalue()
    return _TONES[key]


def beep(cfg, kind):
    if not cfg.get("beeps"):
        return
    tones = {"start": (880, 70), "ok": (1320, 60), "fail": (300, 220)}[kind]

    def _b():
        try:
            import winsound
            # PlaySound goes through the default Windows playback device;
            # winsound.Beep uses the legacy beep device instead.
            winsound.PlaySound(_tone_wav(*tones), winsound.SND_MEMORY)
        except Exception:
            pass

    threading.Thread(target=_b, daemon=True).start()


class Outcome:
    """Truthy result of a handled command: where it was routed and what ran."""
    def __init__(self, source, actions, text="", before=None, macro_id=None):
        self.source, self.actions, self.text, self.before = source, actions, text, before
        self.macro_id = macro_id  # learned macro that produced / was created from this command

    def __bool__(self):
        return True


def handle_text(text, cfg, actions, shortcuts, dry=False, notify=None, on_event=None):
    """Route and execute one transcribed command. Returns True on success."""
    t0 = time.time()
    acts, src = router.route(text, shortcuts)
    from . import feedback
    norm = router.normalize(text)
    prior_bad = feedback.bad_for(norm)
    macro_id = None
    if acts is None and not dry:
        from . import macros
        hit = macros.match(norm)
        if hit:
            macro_id, acts = hit
            src = "learned"
            log.info("Matched learned macro %s", macro_id)
    hint = None
    if prior_bad and cfg["claude"]["enabled"] and not dry:
        hint = ("The user marked this earlier interpretation of the same phrase as WRONG: "
                + json.dumps(prior_bad[-1]) + ". Do something different that better matches what they likely meant.")
        log.info("Phrase %r was marked wrong before; asking Claude instead of %s", norm, src or "the router")
        acts = None
    if acts is None:
        if not cfg["claude"]["enabled"]:
            log.info("Not understood locally and Claude fallback is off: %r", text)
            return False
        if dry:
            log.info("[dry] would call Claude API for: %r", text)
            return Outcome("claude", [])
        from . import claude_api
        if on_event:
            on_event("api_start", text)
        t_api = time.time()
        state = actions.state()
        t_state = time.time()
        acts = claude_api.ask(text, state, shortcuts.known_summary(), cfg["claude"]["model"], hint=hint)
        log.info("Claude call: state %.1fs, API %.1fs", t_state - t_api, time.time() - t_state)
        src = "claude"
        macro_id = None
        keyed = [a for a in acts if a["type"] == "key" and a.get("learn_phrases")]
        if len(acts) == 1 and keyed:
            if shortcuts.learn(keyed[0]["keys"], keyed[0]["learn_phrases"]):
                log.info("Learned single-key shortcut: %s -> %s (see docs/SHORTCUTS.md)",
                         keyed[0]["learn_phrases"], keyed[0]["keys"])
                if notify:
                    notify(f"Learned shortcut: \"{keyed[0]['learn_phrases'][0]}\" -> {keyed[0]['keys']}")
    log.info("[%s] %s", src, acts)
    before = None
    if not dry:
        try:
            before = actions.state()
        except Exception:
            pass
        actions.run(acts)
        if src == "claude":
            try:  # turn this solved example into a local template for next time
                from . import macros
                if prior_bad:  # the old interpretation was wrong: drop any macro that matches it
                    for old in [m for m in macros._load() if macros._instantiate(m, norm) is not None]:
                        macros.forget(old["id"])
                m = macros.learn(norm, acts)
                if m:
                    macro_id = m["id"]
                    log.info("Learned macro %s: %s", m["id"], m["template"])
                    if notify:
                        notify(f"Learned: \"{m['template']}\" (runs locally next time)")
            except Exception:
                log.exception("Macro learning failed")
    log.info("done in %.2fs", time.time() - t0)
    if on_event and not dry:
        from .describe import describe
        if src == "claude":
            on_event("api_done", describe(acts))
        else:
            on_event("local_done", (describe(acts), text))
    return Outcome(src, acts, text, before, macro_id)


def select_mic(cfg):
    from .audio import list_input_devices
    devs = list_input_devices()
    print("\nInput devices:")
    for n, d in enumerate(devs):
        print(f"  [{n}] {d['name']}  ({d['hostapi']}, {d['channels']} ch)")
    print("\nTip: for the command mic, pick a non-ASIO entry (WASAPI or MME) so it doesn't fight Ableton's ASIO driver.")
    choice = int(input("Pick a number: ").strip())
    d = devs[choice]
    cfgmod.save_user(input_device={"name": d["name"], "hostapi": d["hostapi"]})
    print(f"Saved: {d['name']} ({d['hostapi']})")


def main():
    ap = argparse.ArgumentParser(prog="assistant")
    ap.add_argument("--select-mic", action="store_true", help="choose the command microphone and save it")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--learn-trigger", action="store_true", help="press your button/key to set it as the trigger")
    ap.add_argument("--text", help="run one command from text (no mic); good for testing")
    ap.add_argument("--dry-run", action="store_true", help="with --text: show actions without sending to Ableton")
    ap.add_argument("--check", action="store_true", help="check the connection to Ableton and exit")
    ap.add_argument("--no-tray", action="store_true", help="run in this console instead of the system tray")
    args = ap.parse_args()

    setup_logging()
    cfg = cfgmod.load()

    if args.list_devices:
        from .audio import list_input_devices
        for d in list_input_devices():
            print(d)
        return
    if args.select_mic:
        select_mic(cfg)
        return
    if args.learn_trigger:
        from .trigger import learn_combo
        print("Press and release your button / key combo now...")
        combo = learn_combo()
        if not combo:
            print("Nothing detected.")
            return
        mode = input(f"Got '{combo}'. Mode - hold (record while held) / toggle / tap (silence ends it) [hold]: ").strip() or "hold"
        cfgmod.save_user(trigger={"keys": combo, "mode": mode})
        print(f"Saved trigger: {combo} ({mode})")
        return

    shortcuts = Shortcuts()
    if args.text and args.dry_run:
        handle_text(args.text, cfg, None, shortcuts, dry=True)
        return

    o = cfg["osc"]
    osc = AbletonOSC(o["host"], o["send_port"], o["recv_port"])
    from .keys import KeySender
    try:
        keys = KeySender()
    except Exception:
        keys = None
    actions = Actions(osc, cfg, keys)

    if args.check:
        ok = osc.ping()
        print("Ableton connection:", "OK" if ok else "NO REPLY (enable AbletonOSC in Live Preferences > Link, Tempo & MIDI)")
        sys.exit(0 if ok else 1)

    if args.text:
        ok = handle_text(args.text, cfg, actions, shortcuts)
        sys.exit(0 if ok else 1)

    # ---- live mode ----
    from .service import Assistant, single_instance

    if not single_instance():
        msg = "Ableton Assistant is already running (look for its icon in the system tray)."
        print(msg)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "Ableton Assistant", 0x40)
        except Exception:
            pass
        return
    osc.close()  # the service owns the OSC connection; free the port

    if args.no_tray:
        if cfg["input_device"] is None and sys.stdin and sys.stdin.isatty():
            select_mic(cfg)
            cfg = cfgmod.load()
        asst = Assistant(cfg)
        asst.start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    from .tray import run_tray
    run_tray(cfg)
