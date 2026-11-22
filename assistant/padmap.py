"""Live map of the pad: a resizable/maximizable window drawn in the shape of the XPPen ACK05,
each button labelled with what it does right now. Own Tk thread. Open from the tray: "Pad map"."""
import logging
import queue
import threading

from .overlay import BG, FG, MUTED, GREEN, RED, VIOLET, AMBER, monitors, set_dpi_aware

log = logging.getLogger("assistant")

BODY, KEYC, KEYON, KEYDN = "#1b2027", "#2a313a", "#14532d", "#3b82f6"

# normalized device coordinates (device is 1.0 wide, 0.86 tall): x0, y0, x1, y1
KEYS = {
    "b1": (0.36, 0.10, 0.50, 0.25), "b2": (0.53, 0.10, 0.67, 0.25), "b3": (0.70, 0.10, 0.84, 0.25),
    "b4": (0.87, 0.10, 1.01, 0.43),
    "b5": (0.36, 0.28, 0.50, 0.43), "b6": (0.53, 0.28, 0.67, 0.43), "b7": (0.70, 0.28, 0.84, 0.43),
    "b8": (0.36, 0.46, 0.50, 0.61), "b9": (0.53, 0.46, 0.84, 0.61), "b10": (0.87, 0.46, 1.01, 0.61),
}
DIAL = (0.17, 0.36, 0.15)  # cx, cy, r


class PadMap:
    def __init__(self, pad, cfg):
        self.pad = pad
        self.cfg = cfg
        self.q = queue.Queue()
        self.started = False

    def show(self):
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
            self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)
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
        s = min(w / 1.10, h / 0.84)
        ox, oy = (w - s * 1.03) / 2 + s * 0.02, (h - s * 0.70) / 2
        X = lambda v: ox + v * s
        Y = lambda v: oy + v * s
        snap = self.pad.snapshot()
        c.delete("all")
        # body + dial well
        self._rrect(X(-0.02), Y(0.0), X(1.04), Y(0.70), s * 0.04, BODY)
        cx, cy, r = DIAL
        c.create_oval(X(cx - r), Y(cy - r), X(cx + r), Y(cy + r), fill="#232a33", outline="#3a424d", width=max(1, int(s * 0.004)))
        rr = r * 0.42
        d = snap["dial_press"]
        c.create_oval(X(cx - rr), Y(cy - rr), X(cx + rr), Y(cy + rr), fill=KEYDN if d["pressed"] else KEYC, outline="#3a424d")
        self._text(X(cx), Y(cy), d["label"], s * 0.026, FG)
        # dial rotate labels
        ccw, cw = snap["dial_ccw"], snap["dial_cw"]
        self._arrow(X(cx - r * 0.72), Y(cy - r * 0.62), "↺", ccw["pressed"], s)
        self._arrow(X(cx + r * 0.72), Y(cy - r * 0.62), "↻", cw["pressed"], s)
        self._text(X(cx - r * 0.62), Y(cy + r * 0.72), ccw["label"], s * 0.021, MUTED)
        self._text(X(cx + r * 0.62), Y(cy + r * 0.72), cw["label"], s * 0.021, MUTED)
        # keys
        for pid, (x0, y0, x1, y1) in KEYS.items():
            k = snap[pid]
            fill = KEYDN if k["pressed"] else (KEYON if k["active"] else KEYC)
            self._rrect(X(x0), Y(y0), X(x1), Y(y1), s * 0.015, fill)
            self._text(X(x0) + s * 0.012, Y(y0) + s * 0.012, pid.replace("b", "K"), s * 0.016, MUTED, anchor="nw")
            self._text(X((x0 + x1) / 2), Y((y0 + y1) / 2), k["label"], s * 0.021 if (x1 - x0) < 0.2 else s * 0.03, FG)
        # footer
        status = "Connected to Live" if snap["_connected"] else "Waiting for Ableton (is AbletonOSC enabled?)"
        c.create_text(w / 2, h - 12, text=status + "   |   F11 or double-click: fullscreen", fill=GREEN if snap["_connected"] else AMBER,
                      font=("Segoe UI", 10))

    def _text(self, x, y, text, size, color, anchor="center"):
        self.canvas.create_text(x, y, text=text, fill=color, anchor=anchor, justify="center",
                                font=("Segoe UI", max(7, int(size * 0.72)), "bold"))

    def _arrow(self, x, y, ch, pressed, s):
        self.canvas.create_text(x, y, text=ch, fill=KEYDN if pressed else FG, font=("Segoe UI", max(12, int(s * 0.05))))

    def _rrect(self, x0, y0, x1, y1, r, fill):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
               x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        self.canvas.create_polygon(pts, smooth=True, fill=fill, outline="#3a424d")
