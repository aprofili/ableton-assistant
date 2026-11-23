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

# ---- icons: simple line glyphs drawn on the canvas (scalable, one consistent style) -------------
import math as _m


def _arrowhead(c, x, y, dx, dy, size, col):
    n = _m.hypot(dx, dy) or 1
    dx, dy = dx / n, dy / n
    px, py = -dy, dx
    c.create_polygon(x + dx * size, y + dy * size, x - dx * size * .2 + px * size * .75, y - dy * size * .2 + py * size * .75,
                     x - dx * size * .2 - px * size * .75, y - dy * size * .2 - py * size * .75, fill=col, outline=col)


def _arc_arrow(c, cx, cy, a, b, start, extent, col, lw, head=1):
    c.create_arc(cx - a, cy - b, cx + a, cy + b, start=start, extent=extent, style="arc", outline=col, width=lw)
    th = _m.radians(start + extent)
    d = 1 if extent > 0 else -1
    pt = lambda t: (cx + a * _m.cos(t), cy - b * _m.sin(t))
    x, y = pt(th)
    x2, y2 = pt(th + d * 0.05)
    _arrowhead(c, x, y, x2 - x, y2 - y, lw * 2.6, col)


def _icon(c, name, cx, cy, r, col, lw):
    L = lambda *pts, **kw: c.create_line(*pts, fill=col, width=lw, capstyle="round", joinstyle="round", **kw)
    poly = lambda *pts, fill=None: c.create_polygon(*pts, fill=fill or "", outline=col, width=lw, joinstyle="round")
    box = lambda x0, y0, x1, y1, fill=None: c.create_rectangle(cx + x0 * r, cy + y0 * r, cx + x1 * r, cy + y1 * r,
                                                              outline=col, fill=fill or "", width=lw)
    if name == "mic":
        c.create_oval(cx - .3 * r, cy - .85 * r, cx + .3 * r, cy + .15 * r, outline=col, width=lw)
        c.create_arc(cx - .6 * r, cy - .55 * r, cx + .6 * r, cy + .5 * r, start=180, extent=180, style="arc", outline=col, width=lw)
        L(cx, cy + .5 * r, cx, cy + .85 * r)
        L(cx - .3 * r, cy + .85 * r, cx + .3 * r, cy + .85 * r)
    elif name == "tap":
        c.create_oval(cx - .2 * r, cy - .2 * r, cx + .2 * r, cy + .2 * r, fill=col, outline=col)
        c.create_oval(cx - .55 * r, cy - .55 * r, cx + .55 * r, cy + .55 * r, outline=col, width=lw)
        c.create_oval(cx - .9 * r, cy - .9 * r, cx + .9 * r, cy + .9 * r, outline=col, width=lw)
    elif name in ("metronome", "h_tempo"):
        poly(cx - .55 * r, cy + .85 * r, cx + .55 * r, cy + .85 * r, cx + .25 * r, cy - .85 * r, cx - .25 * r, cy - .85 * r)
        L(cx, cy + .55 * r, cx + .3 * r, cy - .55 * r)
        c.create_oval(cx + .15 * r, cy - .3 * r, cx + .4 * r, cy - .05 * r, fill=col, outline=col)
    elif name == "mod":
        poly(cx, cy - .85 * r, cx + .75 * r, cy, cx + .32 * r, cy, cx + .32 * r, cy + .75 * r,
             cx - .32 * r, cy + .75 * r, cx - .32 * r, cy, cx - .75 * r, cy)
    elif name == "rec":
        c.create_oval(cx - .65 * r, cy - .65 * r, cx + .65 * r, cy + .65 * r, fill=RED, outline=RED)
    elif name == "stop":
        box(-.6, -.6, .6, .6, fill=col)
    elif name == "rec_session":
        c.create_oval(cx - .75 * r, cy - .75 * r, cx + .75 * r, cy + .75 * r, outline=RED, width=lw * 1.4)
        c.create_oval(cx - .3 * r, cy - .3 * r, cx + .3 * r, cy + .3 * r, fill=RED, outline=RED)
    elif name == "mute":
        poly(cx - .85 * r, cy - .28 * r, cx - .45 * r, cy - .28 * r, cx, cy - .7 * r, cx, cy + .7 * r, cx - .45 * r, cy + .28 * r, cx - .85 * r, cy + .28 * r)
        L(cx + .25 * r, cy - .35 * r, cx + .85 * r, cy + .35 * r)
        L(cx + .25 * r, cy + .35 * r, cx + .85 * r, cy - .35 * r)
    elif name == "solo":
        c.create_arc(cx - .72 * r, cy - .8 * r, cx + .72 * r, cy + .6 * r, start=0, extent=180, style="arc", outline=col, width=lw)
        box(-.85, -.05, -.45, .65, fill=col)
        box(.45, -.05, .85, .65, fill=col)
    elif name in ("loop",):
        _arc_arrow(c, cx, cy, .85 * r, .55 * r, 40, 290, col, lw)
    elif name == "punch":
        L(cx - .55 * r, cy - .7 * r, cx - .85 * r, cy - .7 * r, cx - .85 * r, cy + .7 * r, cx - .55 * r, cy + .7 * r)
        L(cx + .55 * r, cy - .7 * r, cx + .85 * r, cy - .7 * r, cx + .85 * r, cy + .7 * r, cx + .55 * r, cy + .7 * r)
        c.create_oval(cx - .3 * r, cy - .3 * r, cx + .3 * r, cy + .3 * r, fill=RED, outline=RED)
    elif name == "views":
        for i in range(2):
            for j in range(2):
                box(-.9 + i * .42, -.45 + j * .5, -.58 + i * .42, -.1 + j * .5)
        for j in range(3):
            L(cx + .2 * r, cy - .45 * r + j * .45 * r, cx + .9 * r, cy - .45 * r + j * .45 * r)
    elif name == "device":
        box(-.85, -.6, .85, .6)
        L(cx - .45 * r, cy - .6 * r, cx - .45 * r, cy + .6 * r)
        c.create_oval(cx + .1 * r, cy - .25 * r, cx + .6 * r, cy + .25 * r, outline=col, width=lw)
    elif name in ("prev", "next"):
        d = -1 if name == "prev" else 1
        L(cx - d * .85 * r, cy - .6 * r, cx - d * .85 * r, cy + .6 * r)
        for k in (0, 1):
            x = cx - d * .5 * r + d * k * .65 * r
            poly(x + d * .6 * r, cy, x, cy - .55 * r, x, cy + .55 * r, fill=col)
    elif name == "play":
        poly(cx - .5 * r, cy - .75 * r, cx + .75 * r, cy, cx - .5 * r, cy + .75 * r, fill=col)
    elif name == "continue":
        L(cx - .75 * r, cy - .7 * r, cx - .75 * r, cy + .7 * r)
        poly(cx - .35 * r, cy - .7 * r, cx + .8 * r, cy, cx - .35 * r, cy + .7 * r, fill=col)
    elif name == "undo":
        _arc_arrow(c, cx, cy + .1 * r, .7 * r, .6 * r, 110, 250, col, lw)
    elif name == "redo":
        _arc_arrow(c, cx, cy + .1 * r, .7 * r, .6 * r, 70, -250, col, lw)
    elif name == "wrong":
        c.create_oval(cx - .8 * r, cy - .8 * r, cx + .8 * r, cy + .8 * r, outline=col, width=lw)
        L(cx - .35 * r, cy - .35 * r, cx + .35 * r, cy + .35 * r)
        L(cx - .35 * r, cy + .35 * r, cx + .35 * r, cy - .35 * r)
    elif name == "spark":  # generic spark, drawn here (not any brand mark)
        for k in range(8):
            t = _m.radians(k * 45 + 10)
            ln = .85 if k % 2 == 0 else .6
            c.create_line(cx + .12 * r * _m.cos(t), cy - .12 * r * _m.sin(t), cx + ln * r * _m.cos(t), cy - ln * r * _m.sin(t),
                          fill=AMBER, width=lw * 1.6, capstyle="round")
    elif name in ("scroll_h", "scroll_v"):
        if name == "scroll_h":
            L(cx - .85 * r, cy, cx + .85 * r, cy)
            _arrowhead(c, cx + .9 * r, cy, 1, 0, lw * 2.6, col)
            _arrowhead(c, cx - .9 * r, cy, -1, 0, lw * 2.6, col)
        else:
            L(cx, cy - .85 * r, cx, cy + .85 * r)
            _arrowhead(c, cx, cy - .9 * r, 0, -1, lw * 2.6, col)
            _arrowhead(c, cx, cy + .9 * r, 0, 1, lw * 2.6, col)
    elif name == "h_playhead":
        L(cx, cy - .5 * r, cx, cy + .85 * r)
        poly(cx - .45 * r, cy - .85 * r, cx + .45 * r, cy - .85 * r, cx, cy - .35 * r, fill=col)
    elif name == "h_track":
        for j, y in enumerate((-.6, -.1, .4)):
            box(-.85, y, .85, y + .35, fill=col if j == 1 else None)
    elif name == "h_volume":
        L(cx, cy - .85 * r, cx, cy + .85 * r)
        box(-.45, -.15, .45, .35, fill=col)
    elif name == "h_pan":
        c.create_oval(cx - .6 * r, cy - .6 * r, cx + .6 * r, cy + .6 * r, outline=col, width=lw)
        L(cx, cy, cx + .3 * r, cy - .45 * r)
        L(cx - .85 * r, cy + .8 * r, cx - .85 * r, cy + .45 * r)
        L(cx + .85 * r, cy + .8 * r, cx + .85 * r, cy + .45 * r)
    elif name in ("h_loop_move", "h_loop_start", "h_loop_end"):
        lb = lambda x, d: L(cx + (x + d * .3) * r, cy - .65 * r, cx + x * r, cy - .65 * r, cx + x * r, cy + .1 * r, cx + (x + d * .3) * r, cy + .1 * r)
        if name != "h_loop_end":
            lb(-.85, 1)
        if name != "h_loop_start":
            lb(.85, -1)
        L(cx - .6 * r, cy + .6 * r, cx + .6 * r, cy + .6 * r)
        _arrowhead(c, cx + .65 * r, cy + .6 * r, 1, 0, lw * 2.6, col)
        _arrowhead(c, cx - .65 * r, cy + .6 * r, -1, 0, lw * 2.6, col)
    else:
        return False
    return True


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
        ir = min(rb * sx, rb * sy) * 0.8
        if not (dp.get("icon") and _icon(c, dp["icon"], X(cx), Y(cy), ir, FG, max(2, ir * 0.1))):
            self._ftext(X(cx), Y(cy), dp["label"], 2 * rb * sx * 0.85, 2 * rb * sy * 0.5, FG)
        ccw, cw = snap["dial_ccw"], snap["dial_cw"]
        lw_u = cx + r - x0 + 40
        mx = X(x0 + 8 + lw_u / 2)
        ir = min(lw_u * sx * 0.3, 36 * sy)
        dcol = KEYDN if (cw["pressed"] or ccw["pressed"]) else FG
        cap = cw.get("caption", "")
        iy = Y(cy + r + (30 if cap else 46))
        if not (cw.get("icon") and _icon(c, cw["icon"], mx, iy, ir, dcol, max(2, ir * 0.1))):
            self._ftext(mx, iy, "Scroll", lw_u * sx, 26 * sy, dcol)
        if cap:
            self._ftext(mx, Y(cy + r + 78), cap, lw_u * sx, 24 * sy, dcol)
        for pid, (a0, b0, a1, b1) in KEYS.items():
            k = snap[pid]
            fill = KEYDN if k["pressed"] else (KEYON if k["active"] else KEYC)
            self._rrect(X(a0), Y(b0), X(a1), Y(b1), s * 5, fill)
            kw, kh = (a1 - a0) * sx, (b1 - b0) * sy
            self.canvas.create_text(X(a0) + 6, Y(b0) + 4, text=pid.replace("b", "K"), fill=MUTED, anchor="nw",
                                    font=("Segoe UI", -self._fit("K10", kw * 0.3, kh * 0.18), "bold"))
            ir = min(kw, kh) * 0.34
            if not (k.get("icon") and _icon(c, k["icon"], X((a0 + a1) / 2), Y((b0 + b1) / 2) + kh * 0.05, ir, FG, max(2, ir * 0.11))):
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
