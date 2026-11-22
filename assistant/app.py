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
    from logging.handlers import RotatingFileHandler
    handlers = [RotatingFileHandler(os.path.join(cfgmod.ROOT, "logs", "assistant.log"),
                                    maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stdout is not None:  # pythonw.exe has no stdout
        handlers.insert(0, logging.StreamHandler(sys.stdout))
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.propagate = False


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


class Outcome:
    """Truthy result of a handled command: where it was routed and what ran."""
    def __init__(self, source, actions):
        self.source, self.actions = source, actions

    def __bool__(self):
        return True


def handle_text(text, cfg, actions, shortcuts, dry=False, notify=None, on_event=None):
    """Route and execute one transcribed command. Returns True on success."""
    t0 = time.time()
    acts, src = router.route(text, shortcuts)
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
        acts = claude_api.ask(text, actions.state(), shortcuts.known_summary(), cfg["claude"]["model"])
        src = "claude"
        keyed = [a for a in acts if a["type"] == "key" and a.get("learn_phrases")]
        if len(acts) == 1 and keyed:
            if shortcuts.learn(keyed[0]["keys"], keyed[0]["learn_phrases"]):
                log.info("Learned single-key shortcut: %s -> %s (see docs/SHORTCUTS.md)",
                         keyed[0]["learn_phrases"], keyed[0]["keys"])
                if notify:
                    notify(f"Learned shortcut: \"{keyed[0]['learn_phrases'][0]}\" -> {keyed[0]['keys']}")
    log.info("[%s] %s", src, acts)
    if not dry:
        actions.run(acts)
    log.info("done in %.2fs", time.time() - t0)
    if src == "claude" and on_event:
        from .describe import describe
        on_event("api_done", describe(acts))
    return Outcome(src, acts)


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
