"""Live map of the pad: a resizable/maximizable window drawn in the shape of the XPPen ACK05,
each button labelled with what it does right now. Own Tk thread. Open from the tray: "Pad map"."""
import json
import logging
import os
import queue
import threading

from .overlay import BG, FG, MUTED, GREEN, RED, VIOLET, AMBER, monitors, set_dpi_aware

log = logging.getLogger("assistant")

BODY, KEYC, KEYON, KEYDN = "#1b2027", "#2a313a", "#14532d", "#3b82f6"

# device geometry in pixels of the XPPen driver image (500 x 282): x0, y0, x1, y1
KEYS = {
    "b1": (184, 74, 236, 126), "b2": (245, 74, 297, 126), "b3": (304, 74, 356, 126),
    "b7": (363, 74, 415, 188),
    "b4": (184, 135, 236, 187), "b5": (245, 135, 297, 187), "b6": (304, 135, 356, 187),
    "b8": (184, 196, 236, 248), "b9": (245, 196, 356, 248), "b10": (363, 196, 415, 248),
}
BODY_RECT = (42, 60, 430, 262)
DIAL = (78, 104, 52)  # cx, cy, outer radius (the dial overhangs the body's top-left corner)
W0, H0 = 500.0, 282.0


class PadMap:
    def __init__(self, pad, cfg):
        self.pad = pad
        self.cfg = cfg
        self.q = queue.Queue()
        self.started = False

    STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ui_state.json")

    def _save_open(self, is_open):
        try:
            os.makedirs(os.path.dirname(self.STATE), exist_ok=True)
            try:
                with open(self.STATE, encoding="utf-8") as f:
                    st = json.load(f)
            except Exception:
                st = {}
            st["padmap_open"] = bool(is_open)
            with open(self.STATE, "w", encoding="utf-8") as f:
                json.dump(st, f)
        except Exception:
            log.exception("Could not save pad map state")

    def restore(self):
        """Reopen the map if it was open when the assistant last ran."""
        try:
            with open(self.STATE, encoding="utf-8") as f:
                if json.load(f).get("padmap_open"):
                    self.show()
        except Exception:
            pass

    def hide(self):
        self._save_open(False)
        self.root.withdraw()

    def show(self):
        self._save_open(True)
        if not self.started:
            self.started = True
            threading.Thread(target=self._run, daemon=True, name="padmap").start()
        self.q.put("show")

    # ---- Tk thread
    def _run(self):
        try:
            import tkinter as tk
            set_dpi_aware()
            self.tk = tk
            self.root = tk.Tk()
            self.root.title("Ableton Assistant - Pad map")
            self.root.configure(bg=BG)
            self.root.geometry("900x640")
            self.root.minsize(480, 340)
            self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
            self.canvas.pack(fill="both", expand=True)
            self.full = False
            self.root.protocol("WM_DELETE_WINDOW", self.hide)
            self.root.bind("<F11>", self._toggle_full)
            self.root.bind("<Escape>", lambda e: self._set_full(False))
            self.canvas.bind("<Double-Button-1>", self._toggle_full)
            self.root.after(50, self._tick)
            self.root.mainloop()
        except Exception:
            log.exception("Pad map crashed")

    def _set_full(self, on):
        self.full = on
        self.root.attributes("-fullscreen", on)

    def _toggle_full(self, e=None):
        self._set_full(not self.full)

    def _place(self):
        """Open on the second monitor (config pad.map_monitor, default 1) and maximize."""
        mons = monitors()
        idx = self.cfg.get("pad", {}).get("map_monitor", 1)
        mx, my, mw, mh = mons[idx] if idx < len(mons) else mons[0]
        self.root.geometry(f"{min(1200, mw)}x{min(800, mh)}+{mx + 40}+{my + 40}")
        self.root.update_idletasks()
        try:
            self.root.state("zoomed")
        except Exception:
            pass

    def _tick(self):
        try:
            while True:
                self.q.get_nowait()
                first = not getattr(self, "placed", False)
                self.root.deiconify()
                if first:
                    self.placed = True
                    self._place()
                self.root.lift()
        except queue.Empty:
            pass
        except Exception:
            log.exception("Pad map show failed")
        try:
            if self.root.state() != "withdrawn":
                self._draw()
        except Exception:
            log.exception("Pad map draw failed")
        self.root.after(100, self._tick)

    # ---- drawing
    def _draw(self):
        c = self.canvas
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        s = min(w / (W0 + 30), (h - 40) / (H0 - 10)) * 0.92
        ox, oy = (w - W0 * s) / 2, (h - 20 - (H0 - 40) * s) / 2 - 30 * s
        X = lambda v: ox + v * s
        Y = lambda v: oy + v * s
        snap = self.pad.snapshot()
        c.delete("all")
        x0, y0, x1, y1 = BODY_RECT
        self._rrect(X(x0), Y(y0), X(x1), Y(y1), s * 14, BODY)
        # dial: outer ring with grooves, centre button (not programmable on the ACK05)
        cx, cy, r = DIAL
        ow = max(1, int(s * 1.2))
        c.create_oval(X(cx - r), Y(cy - r), X(cx + r), Y(cy + r), fill="#12161b", outline="#3a424d", width=ow)
        for k in range(1, 6):
            rr = r * (1 - 0.095 * k)
            c.create_oval(X(cx - rr), Y(cy - rr), X(cx + rr), Y(cy + rr), outline="#242b34", width=1)
        rb = r * 0.36
        c.create_oval(X(cx - rb), Y(cy - rb), X(cx + rb), Y(cy + rb), fill="#0d1014", outline="#3a424d", width=ow)
        ccw, cw = snap["dial_ccw"], snap["dial_cw"]
        # dial labels under the dial, on the body
        self._text(X(100), Y(cy + r + 22), "\u21ba " + ccw["label"], s * 8.5, KEYDN if ccw["pressed"] else FG)
        self._text(X(100), Y(cy + r + 42), "\u21bb " + cw["label"], s * 8.5, KEYDN if cw["pressed"] else FG)
        # keys
        for pid, (a0, b0, a1, b1) in KEYS.items():
            k = snap[pid]
            fill = KEYDN if k["pressed"] else (KEYON if k["active"] else KEYC)
            self._rrect(X(a0), Y(b0), X(a1), Y(b1), s * 5, fill)
            self._text(X(a0) + s * 4, Y(b0) + s * 3, pid.replace("b", "K"), s * 6, MUTED, anchor="nw")
            self._text(X((a0 + a1) / 2), Y((b0 + b1) / 2 + 3), k["label"], s * (8 if (a1 - a0) < 60 else 11), FG)
        if snap.get("_last"):
            c.create_text(w / 2, Y(y1) + 28 * s, text=snap["_last"], fill=MUTED, font=("Segoe UI", max(9, int(s * 7))))
        status = "Connected to Live" if snap["_connected"] else "Waiting for Ableton (is AbletonOSC enabled?)"
        c.create_text(w / 2, h - 12, text=status + "   |   F11 or double-click: fullscreen", fill=GREEN if snap["_connected"] else AMBER,
                      font=("Segoe UI", 10))

    def _text(self, x, y, text, size, color, anchor="center"):
        self.canvas.create_text(x, y, text=text, fill=color, anchor=anchor, justify="center",
                                font=("Segoe UI", max(7, int(size * 0.72)), "bold"))

    def _arrow(self, x, y, ch, pressed, s):
        self.canvas.create_text(x, y, text=ch, fill=KEYDN if pressed else FG, font=("Segoe UI", max(12, int(s * 14))))

    def _rrect(self, x0, y0, x1, y1, r, fill):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
               x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        self.canvas.create_polygon(pts, smooth=True, fill=fill, outline="#3a424d")
