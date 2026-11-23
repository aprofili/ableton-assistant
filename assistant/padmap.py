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

    def _load_state(self):
        try:
            with open(self.STATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_geom(self):
        """Remember window position/size (and maximized state) so a restart reopens it the same way."""
        try:
            if self.root.state() == "withdrawn" or self.full:
                return
            cur = {"geom": self.root.geometry(), "zoomed": self.root.state() == "zoomed"}
            if cur != getattr(self, "_geom_saved", None):
                self._geom_saved = cur
                st = self._load_state()
                st["padmap_window"] = cur
                os.makedirs(os.path.dirname(self.STATE), exist_ok=True)
                with open(self.STATE, "w", encoding="utf-8") as f:
                    json.dump(st, f)
        except Exception:
            pass

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
            self.canvas.bind("<Button-1>", self._click)
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
        saved = self._load_state().get("padmap_window")
        if saved and self._apply_saved(saved):
            return
        mons = monitors()
        idx = self.cfg.get("pad", {}).get("map_monitor", 1)
        mx, my, mw, mh = mons[idx] if idx < len(mons) else mons[0]
        self.root.geometry(f"{min(1200, mw)}x{min(800, mh)}+{mx + 40}+{my + 40}")
        self.root.update_idletasks()
        try:
            self.root.state("zoomed")
        except Exception:
            pass

    def _apply_saved(self, saved):
        import re
        m = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", saved.get("geom", ""))
        if not m:
            return False
        w, h, x, y = int(m[1]), int(m[2]), int(m[3]), int(m[4])
        mons = monitors()
        # only reuse the position if it still lands on an attached monitor
        if not any(mx - w / 2 < x < mx + mw - 100 and my - 10 < y < my + mh - 100 for mx, my, mw, mh in mons):
            return False
        self.root.geometry(f"{w}x{h}{x:+d}{y:+d}")
        self.root.update_idletasks()
        if saved.get("zoomed"):
            try:
                self.root.state("zoomed")
            except Exception:
                pass
        return True

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
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 30 == 0:  # ~ once a second
            self._save_geom()
        try:
            if self.root.state() != "withdrawn":
                snap = self.pad.snapshot()
                key = (repr(sorted(snap.items())), self.canvas.winfo_width(), self.canvas.winfo_height())
                if key != getattr(self, "_last_key", None):  # redraw only on change
                    self._last_key = key
                    self._draw(snap)
        except Exception:
            log.exception("Pad map draw failed")
        self.root.after(30, self._tick)

    # ---- drawing: the layout is stretched to fill the whole window (shape accuracy matters less than size)
    GX0, GX1, GY0, GY1 = 22.0, 436.0, 46.0, 266.0   # content bounds in device units

    def _fit(self, text, maxw, maxh):
        """Largest bold font (px) that fits `text` in maxw x maxh; cached."""
        key = (text, int(maxw), int(maxh))
        hit = self._fit_cache.get(key)
        if hit:
            return hit
        import tkinter.font as tkf
        lines = text.split("\n")
        size = 8
        for sz in range(90, 7, -2):
            f = self._fonts.get(sz)
            if f is None:
                f = self._fonts[sz] = tkf.Font(family="Segoe UI", size=-sz, weight="bold")
            if max(f.measure(l) for l in lines) <= maxw and f.metrics("linespace") * len(lines) <= maxh:
                size = sz
                break
        if len(self._fit_cache) > 600:
            self._fit_cache.clear()
        self._fit_cache[key] = size
        return size

    def _ftext(self, cx, cy, text, w, h, color, anchor="center"):
        sz = self._fit(text, w, h)
        self.canvas.create_text(cx, cy, text=text, fill=color, anchor=anchor, justify="center",
                                font=("Segoe UI", -sz, "bold"))

    def _draw(self, snap=None):
        c = self.canvas
        if not hasattr(self, "_fonts"):
            self._fonts, self._fit_cache = {}, {}
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        pad_x, top, bottom = 10, 8, 40
        sx = (w - 2 * pad_x) / (self.GX1 - self.GX0)
        sy = (h - top - bottom) / (self.GY1 - self.GY0)
        ox, oy = pad_x - self.GX0 * sx, top - self.GY0 * sy
        X = lambda v: ox + v * sx
        Y = lambda v: oy + v * sy
        self._xf = (ox, oy, sx, sy)
        s = min(sx, sy)
        snap = snap or self.pad.snapshot()
        c.delete("all")
        x0, y0, x1, y1 = BODY_RECT
        self._rrect(X(x0), Y(y0), X(x1), Y(y1), s * 12, BODY)
        cx, cy, r = DIAL
        ow = max(1, int(s * 1.2))
        ell = lambda rr, **kw: c.create_oval(X(cx - rr), Y(cy - rr), X(cx + rr), Y(cy + rr), **kw)
        ell(r, fill="#12161b", outline="#3a424d", width=ow)
        for k in range(1, 6):
            ell(r * (1 - 0.095 * k), outline="#242b34", width=1)
        rb = r * 0.5
        dp = snap["dial_press"]
        ell(rb, fill=KEYON if dp["active"] else ("#2a3440" if dp["pressed"] else "#0d1014"), outline="#3a424d", width=ow)
        self._ftext(X(cx), Y(cy), dp["label"], 2 * rb * sx * 0.85, 2 * rb * sy * 0.5, FG)
        ccw, cw = snap["dial_ccw"], snap["dial_cw"]
        lw, lh = (cx + r - x0 + 40) * sx, 20 * sy
        self._ftext(X(x0 + 8 + (lw / sx) / 2), Y(cy + r + 14), "\u21ba " + ccw["label"], lw, lh, KEYDN if ccw["pressed"] else FG)
        self._ftext(X(x0 + 8 + (lw / sx) / 2), Y(cy + r + 38), "\u21bb " + cw["label"], lw, lh, KEYDN if cw["pressed"] else FG)
        for pid, (a0, b0, a1, b1) in KEYS.items():
            k = snap[pid]
            fill = KEYDN if k["pressed"] else (KEYON if k["active"] else KEYC)
            self._rrect(X(a0), Y(b0), X(a1), Y(b1), s * 5, fill)
            kw, kh = (a1 - a0) * sx, (b1 - b0) * sy
            self.canvas.create_text(X(a0) + 6, Y(b0) + 4, text=pid.replace("b", "K"), fill=MUTED, anchor="nw",
                                    font=("Segoe UI", -self._fit("K10", kw * 0.3, kh * 0.18), "bold"))
            self._ftext(X((a0 + a1) / 2), Y((b0 + b1) / 2) + kh * 0.06, k["label"], kw * 0.9, kh * 0.62, FG)
        if snap.get("_last"):
            self._ftext(w / 2 - 12, h - 22, snap["_last"], w - 70, 26, MUTED)
        ok = snap["_connected"]  # connection to Live: green check / red cross
        c.create_text(w - 18, h - 20, text="\u2713" if ok else "\u2717", fill=GREEN if ok else RED,
                      font=("Segoe UI", -28, "bold"))

    def _click(self, e):
        try:
            ox, oy, sx, sy = self._xf
            x, y = (e.x - ox) / sx, (e.y - oy) / sy
            for pid, (a0, b0, a1, b1) in KEYS.items():
                if a0 <= x <= a1 and b0 <= y <= b1:
                    self.pad.click(pid)
                    return
            cx, cy, r = DIAL
            if (x - cx) ** 2 + (y - cy) ** 2 <= (r * 0.5) ** 2:
                self.pad.click("dial_press")
                return
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r or (abs(x - 100) < 70 and cy + r < y < cy + r + 50):
                self.pad.click("dial_ccw" if (y > cy + r and y < cy + r + 26) or (y <= cy + r and x < cx) else "dial_cw")
        except Exception:
            log.exception("pad map click")

    def _text(self, x, y, text, size, color, anchor="center"):
        self.canvas.create_text(x, y, text=text, fill=color, anchor=anchor, justify="center",
                                font=("Segoe UI", max(7, int(size * 0.72)), "bold"))

    def _arrow(self, x, y, ch, pressed, s):
        self.canvas.create_text(x, y, text=ch, fill=KEYDN if pressed else FG, font=("Segoe UI", max(12, int(s * 14))))

    def _rrect(self, x0, y0, x1, y1, r, fill):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
               x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        self.canvas.create_polygon(pts, smooth=True, fill=fill, outline="#3a424d")
