import argparse
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
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(cfgmod.ROOT, "logs", "assistant.log"), encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)


def beep(cfg, kind):
    if not cfg.get("beeps"):
        return
    tones = {"start": (880, 70), "ok": (1320, 60), "fail": (300, 220)}[kind]

    def _b():
        try:
            import winsound
            winsound.Beep(*tones)
        except Exception:
            pass

    threading.Thread(target=_b, daemon=True).start()


def handle_text(text, cfg, actions, shortcuts, dry=False):
    """Route and execute one transcribed command. Returns True on success."""
    t0 = time.time()
    acts, src = router.route(text, shortcuts)
    if acts is None:
        if not cfg["claude"]["enabled"]:
            log.info("Not understood locally and Claude fallback is off: %r", text)
            return False
        if dry:
            log.info("[dry] would call Claude API for: %r", text)
            return True
        from . import claude_api
        acts = claude_api.ask(text, actions.state(), shortcuts.known_summary(), cfg["claude"]["model"])
        src = "claude"
        keyed = [a for a in acts if a["type"] == "key" and a.get("learn_phrases")]
        if len(acts) == 1 and keyed:
            if shortcuts.learn(keyed[0]["keys"], keyed[0]["learn_phrases"]):
                log.info("Learned single-key shortcut: %s -> %s (see docs/SHORTCUTS.md)",
                         keyed[0]["learn_phrases"], keyed[0]["keys"])
    log.info("[%s] %s", src, acts)
    if not dry:
        actions.run(acts)
    log.info("done in %.2fs", time.time() - t0)
    return True


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
    from .audio import Recorder, resolve_device
    from .stt import Transcriber
    from .trigger import Trigger

    if cfg["input_device"] is None and sys.stdin.isatty():
        select_mic(cfg)
        cfg = cfgmod.load()
    device = resolve_device(cfg["input_device"])

    if not osc.ping():
        log.info("WARNING: no reply from Ableton. Enable AbletonOSC as a Control Surface in Live's Preferences.")
    log.info("Loading speech model (%s)...", cfg["whisper"]["model"])
    stt = Transcriber(cfg["whisper"]["model"], cfg["whisper"]["device"], cfg["whisper"]["compute_type"])
    stt.warm_up()

    rec = Recorder(device, cfg["silence_seconds"], cfg["max_record_seconds"])
    busy = threading.Lock()
    trig_cfg = cfg["trigger"]
    holder = {}

    def process(audio):
        with busy:
            try:
                t0 = time.time()
                text = stt.transcribe(audio)
                log.info("heard %r (%.2fs)", text, time.time() - t0)
                if not text:
                    return
                ok = handle_text(text, cfg, actions, shortcuts)
                beep(cfg, "ok" if ok else "fail")
            except Exception as e:
                log.info("ERROR: %s", e)
                beep(cfg, "fail")

    def on_start():
        beep(cfg, "start")
        if trig_cfg["mode"] == "tap":
            rec.on_auto_stop = lambda: holder["trigger"].stop_from_outside()
        rec.start(endpoint=trig_cfg["mode"] == "tap")

    def on_stop():
        audio = rec.stop()
        threading.Thread(target=process, args=(audio,), daemon=True).start()

    trigger = Trigger(trig_cfg["keys"], trig_cfg["mode"], on_start, on_stop)
    holder["trigger"] = trigger
    log.info("Ready. Trigger: %s (%s). Mic: %s. Ctrl+C to quit.", trig_cfg["keys"], trig_cfg["mode"],
             cfg["input_device"] or "system default")
    try:
        trigger.run()
    except KeyboardInterrupt:
        pass
