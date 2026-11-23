"""System tray UI: status icon + right-click menu."""
import logging
import os
import threading
import sys

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from . import config as cfgmod
from .service import Assistant, open_in_notepad

log = logging.getLogger("assistant")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AbletonVoiceAssistant"

COLORS = {"loading": (120, 120, 120), "idle": (0, 150, 136), "listening": (215, 45, 45),
          "working": (235, 165, 20), "error": (130, 40, 40), "disabled": (90, 90, 90)}
STATUS = {"loading": "Loading speech model...", "listening": "Listening...", "working": "Working...",
          "error": "Error - see log"}


def make_icon(state):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=COLORS[state])
    w = (250, 250, 250)
    d.rounded_rectangle((24, 9, 40, 35), radius=8, fill=w)       # capsule
    d.arc((15, 18, 49, 47), 0, 180, fill=w, width=4)              # cradle
    d.line((32, 47, 32, 54), fill=w, width=4)                     # stem
    d.line((22, 54, 42, 54), fill=w, width=4)                     # base
    if state == "disabled":
        d.line((10, 54, 54, 10), fill=(255, 255, 255), width=5)
    return img


def _autostart_cmd():
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw}" "{os.path.join(cfgmod.ROOT, "start_tray.pyw")}"'


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_NAME)[0] == _autostart_cmd()
    except Exception:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _autostart_cmd())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


class TrayApp:
    def __init__(self, cfg):
        self.cfg = cfg
        self.asst = Assistant(cfg, on_state=self.on_state, notify=self.notify)
        self.icon = pystray.Icon("ableton-assistant", make_icon("loading"), "Ableton Assistant", menu=self.build_menu())

    # ---- state / notifications ----------------------------------------
    def notify(self, msg):
        try:
            self.icon.notify(msg, "Ableton Assistant")
        except Exception:
            pass

    def on_state(self, state):
        shown = "disabled" if (not self.asst.enabled and state == "idle") else state
        try:
            self.icon.icon = make_icon(shown)
            self.icon.title = "Ableton Assistant - " + self.status_text(state)
            self.icon.update_menu()
        except Exception:
            pass

    def status_text(self, state=None):
        state = state or self.asst.state
        if state == "idle":
            t = self.cfg["trigger"]
            if not self.asst.enabled:
                return "Paused"
            return f"Ready - {t['mode']} {t['keys']}"
        return STATUS.get(state, state)

    # ---- menu ----------------------------------------------------------
    def mic_items(self):
        from .audio import list_input_devices
        cur = self.cfg.get("input_device")
        idle = not getattr(self.asst, "_recording", False)  # rescan hardware on every menu open (safe only when idle)

        def picker(spec):
            def pick(icon, item):
                self.asst.set_input_device(spec)
                self.icon.update_menu()
            return pick

        def is_checked(spec):
            return lambda item: self.cfg.get("input_device") == spec

        yield MenuItem("System default", picker(None), checked=is_checked(None), radio=True)
        seen = set()
        for d in list_input_devices(refresh=idle):
            if d["hostapi"] != "MME" or d["name"] == "Microsoft Sound Mapper - Input" or d["name"] in seen:
                continue
            seen.add(d["name"])
            spec = {"name": d["name"], "hostapi": d["hostapi"]}
            yield MenuItem(d["name"], picker(spec), checked=is_checked(spec), radio=True)

    def build_menu(self):
        a = self.asst

        def toggle_enabled(icon, item):
            a.enabled = not a.enabled
            self.on_state(a.state)

        def mode_item(mode, label):
            return MenuItem(label, lambda icon, item: (a.set_trigger_mode(mode), icon.update_menu()),
                            checked=lambda item: self.cfg["trigger"]["mode"] == mode, radio=True)

        def notif_item(mode, label):
            def pick(icon, item):
                cfgmod.save_user(notifications=mode)
                self.cfg["notifications"] = mode
            return MenuItem(label, pick, checked=lambda item: self.cfg.get("notifications", "errors") == mode, radio=True)

        def toggle_claude(icon, item):
            v = not self.cfg["claude"]["enabled"]
            cfgmod.save_user(claude={"enabled": v})
            self.cfg["claude"]["enabled"] = v

        def toggle_overlay(icon, item):
            v = not self.cfg.get("overlay", {}).get("enabled", True)
            cfgmod.save_user(overlay={"enabled": v})
            self.cfg.setdefault("overlay", {})["enabled"] = v
            a.overlay.enabled = v

        def toggle_updates(icon, item):
            on = not self.cfg.get("updates", {}).get("auto", True)
            self.cfg.setdefault("updates", {})["auto"] = on
            cfgmod.save_user(updates={"auto": on})

        def toggle_beeps(icon, item):
            v = not self.cfg.get("beeps", True)
            cfgmod.save_user(beeps=v)
            self.cfg["beeps"] = v

        def toggle_autostart(icon, item):
            try:
                set_autostart(not autostart_enabled())
            except Exception as e:
                self.notify(f"Couldn't change startup setting: {e}")

        def open_log(icon, item):
            open_in_notepad(os.path.join(cfgmod.ROOT, "logs", "assistant.log"))

        def open_env(icon, item):
            p = os.path.join(cfgmod.ROOT, ".env")
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    f.write("ANTHROPIC_API_KEY=\n")
            open_in_notepad(p)

        def open_config(icon, item):
            if not os.path.exists(cfgmod.USER_PATH):
                cfgmod.save_user()
            open_in_notepad(cfgmod.USER_PATH)

        def open_shortcuts(icon, item):
            open_in_notepad(os.path.join(cfgmod.ROOT, "docs", "SHORTCUTS.md"))

        def restart(icon, item):
            import subprocess
            subprocess.Popen(["wscript.exe", os.path.join(cfgmod.ROOT, "restart_hidden.vbs")],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def quit_(icon, item):
            icon.stop()
            os._exit(0)

        from . import __version__
        return Menu(
            MenuItem(lambda item: self.status_text(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Listening enabled", toggle_enabled, checked=lambda item: a.enabled),
            MenuItem("Pad map", lambda icon, item: a.padmap.show()),
            MenuItem("Last command was wrong", lambda icon, item: a.mark_wrong()),
            MenuItem("Microphone", Menu(self.mic_items)),
            MenuItem("Settings", Menu(
                MenuItem("Trigger", Menu(
                    MenuItem(lambda item: f"Key: {self.cfg['trigger']['keys']}  (click to change)",
                             lambda icon, item: a.learn_trigger()),
                    Menu.SEPARATOR,
                    mode_item("hold", "Hold to talk"),
                    mode_item("toggle", "Press to start / press to stop"),
                    mode_item("tap", "Tap, ends on silence"),
                )),
                MenuItem("Use Claude for complex commands", toggle_claude,
                         checked=lambda item: self.cfg["claude"]["enabled"]),
                MenuItem("On-screen indicator", toggle_overlay,
                         checked=lambda item: self.cfg.get("overlay", {}).get("enabled", True)),
                MenuItem("Beeps", toggle_beeps, checked=lambda item: self.cfg.get("beeps", True)),
                MenuItem("Notifications", Menu(
                    notif_item("errors", "Errors only"),
                    notif_item("all", "Every command"),
                    notif_item("off", "Off"),
                )),
                MenuItem("Start with Windows", toggle_autostart, checked=lambda item: autostart_enabled()),
            )),
            MenuItem("Updates", Menu(
                MenuItem(f"Version {__version__}", None, enabled=False),
                MenuItem("Auto-update", toggle_updates,
                         checked=lambda item: self.cfg.get("updates", {}).get("auto", True)),
                MenuItem(lambda item: "Check now" + (f" ({a.update_status})" if a.update_status else ""),
                         lambda icon, item: threading.Thread(target=a.check_updates, daemon=True).start()),
            )),
            MenuItem("Tools", Menu(
                MenuItem("Check Ableton connection", lambda icon, item: a.check_ableton()),
                MenuItem("View log", open_log),
                MenuItem("Shortcuts list", open_shortcuts),
                MenuItem("Edit API key (.env)", open_env),
                MenuItem("Edit settings (config.json)", open_config),
            )),
            Menu.SEPARATOR,
            MenuItem("Restart", restart),
            MenuItem("Quit", quit_),
        )

    def run(self):
        self.icon.run(setup=lambda icon: (setattr(icon, "visible", True), self.asst.start()))


def run_tray(cfg):
    from .overlay import set_dpi_aware
    set_dpi_aware()
    try:
        TrayApp(cfg).run()
    except Exception:
        log.exception("Tray crashed")
        raise
