"""Translucent, click-through on-screen popups on every monitor (tkinter, own thread).

listening()                 pulsing red "Listening" pill with a live level bar
api_start(heard)            "Asking Claude..." while an API call is in flight
api_done(ok, detail)        result of the API command, then fades out
hide()                      fade out whatever is showing
The windows never take focus and ignore the mouse, so Ableton keeps keyboard focus.
"""
import ctypes
import logging
import math
import queue
import sys
import threading
import time
from ctypes import wintypes

log = logging.getLogger("assistant")

KEY = "#ff00fe"  # transparent colour key (rounded corners)
BG = "#12161b"
FG = "#f4f6f8"
MUTED = "#9aa4af"
RED, AMBER, GREEN, VIOLET = "#ef4444", "#f5a524", "#34d399", "#a78bfa"


def set_dpi_aware():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def monitors():
    """List of (x, y, w, h) in physical pixels for every attached monitor."""
    if sys.platform != "win32":
        return [(0, 0, 1280, 720)]
    out = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)

    def cb(hmon, hdc, rect, lparam):
        r = rect.contents
        out.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    return out or [(0, 0, 1920, 1080)]


class Overlay:
    def __init__(self, opacity=0.85, enabled=True):
        self.opacity = opacity
        self.enabled = enabled
        self.level_fn = None
        self.q = queue.Queue()
        self.ok = False

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="overlay").start()

    # ---- public (thread-safe) -------------------------------------------
    def listening(self):
        self._put(("listening",))

    def api_start(self, heard=""):
        self._put(("api_start", heard))

    def api_done(self, ok, detail=""):
        self._put(("api_done", ok, detail))

    def hide(self):
        self._put(("hide",))

    def _put(self, msg):
        if self.enabled:
            self.q.put(msg)

    # ---- Tk thread -------------------------------------------------------
    def _run(self):
        try:
            import tkinter as tk
        except Exception as e:
            log.info("On-screen indicator disabled (tkinter unavailable): %s", e)
            return
        try:
            self.tk = tk
            self.root = tk.Tk()
            self.root.withdraw()
            self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
            self.wins = []
            self.mode = "hidden"
            self.t0 = 0.0
            self.level = 0.0
            self.heard = ""
            self.detail = ""
            self.result_ok = True
            self.hide_at = None
            self.fade_t0 = None
            self.ok = True
            self.root.after(30, self._tick)
            self.root.mainloop()
        except Exception:
            log.exception("Overlay thread crashed")

    def _tick(self):
        try:
            while True:
                self._handle(self.q.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            log.exception("Overlay message failed")
        try:
            self._animate()
        except Exception:
            log.exception("Overlay animation failed")
        self.root.after(33, self._tick)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "listening":
            self._show("listening")
        elif kind == "api_start":
            self.heard = msg[1]
            self._show("api_working")
        elif kind == "api_done":
            self.result_ok, self.detail = msg[1], msg[2]
            self._show("api_done")
            self.hide_at = time.time() + (2.6 if msg[1] else 4.0)
        elif kind == "hide":
            if self.mode != "hidden":
                self.mode = "fading"
                self.fade_t0 = time.time()

    def _show(self, mode):
        was_hidden = self.mode in ("hidden", "fading")
        self.mode = mode
        self.t0 = time.time()
        self.hide_at = None
        self.fade_t0 = None
        if was_hidden or not self.wins:
            self._build()
        for w in self.wins:
            w["win"].attributes("-alpha", self.opacity)

    def _build(self):
        tk = self.tk
        for w in self.wins:
            try:
                w["win"].destroy()
            except Exception:
                pass
        self.wins = []
        s = self.scale
        W, H = int(400 * s), int(104 * s)
        for (mx, my, mw, mh) in monitors():
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.attributes("-alpha", self.opacity)
            win.configure(bg=KEY)
            try:
                win.attributes("-transparentcolor", KEY)
            except Exception:
                pass
            c = tk.Canvas(win, width=W, height=H, bg=KEY, highlightthickness=0)
            c.pack()
            x = mx + (mw - W) // 2
            y = my + int(48 * s)
            win.geometry(f"{W}x{H}+{x}+{y}")
            win.update_idletasks()
            self._click_through(win)
            self.wins.append({"win": win, "canvas": c, "W": W, "H": H})

    @staticmethod
    def _click_through(win):
        if sys.platform != "win32":
            return
        try:
            u = ctypes.windll.user32
            hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
            style = u.GetWindowLongW(hwnd, -20)
            # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW (no taskbar) | NOACTIVATE (no focus)
            u.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass

    def _animate(self):
        if self.mode == "hidden":
            return
        now = time.time()
        if self.mode == "fading":
            a = 1.0 - (now - self.fade_t0) / 0.25
            if a <= 0:
                for w in self.wins:
                    w["win"].withdraw()
                self.mode = "hidden"
                return
            for w in self.wins:
                w["win"].attributes("-alpha", self.opacity * a)
            return
        if self.mode == "api_done" and self.hide_at and now >= self.hide_at:
            self.mode = "fading"
            self.fade_t0 = now
            return
        if self.mode == "listening" and self.level_fn:
            try:
                target = min(1.0, float(self.level_fn()) * 14)
            except Exception:
                target = 0.0
            self.level += (target - self.level) * 0.45
        for w in self.wins:
            w["win"].deiconify() if w["win"].state() == "withdrawn" else None
            self._draw(w, now - self.t0)

    # ---- drawing ---------------------------------------------------------
    @staticmethod
    def _rr(c, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
               x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return c.create_polygon(pts, smooth=True, **kw)

    def _draw(self, w, t):
        c, W, H, s = w["canvas"], w["W"], w["H"], self.scale
        c.delete("all")
        self._rr(c, 2, 2, W - 2, H - 2, 26 * s, fill=BG, outline="")
        cx, cy = 52 * s, H / 2
        title_font = ("Segoe UI Semibold", int(17 * s * 0.75))
        sub_font = ("Segoe UI", int(11 * s * 0.75))
        if self.mode == "listening":
            pulse = 0.5 + 0.5 * math.sin(t * 6.0)
            r = (13 + 4 * pulse) * s
            c.create_oval(cx - r - 7 * s, cy - r - 7 * s, cx + r + 7 * s, cy + r + 7 * s, fill="#3a1d20", outline="")
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=RED, outline="")
            c.create_text(88 * s, H * 0.36, text="Listening", anchor="w", fill=FG, font=title_font)
            c.create_text(88 * s, H * 0.62, text="say your command, then release", anchor="w", fill=MUTED, font=sub_font)
            bx1, bx2, by = 88 * s, W - 30 * s, H - 20 * s
            c.create_line(bx1, by, bx2, by, fill="#2a3138", width=int(5 * s), capstyle="round")
            fill_to = bx1 + (bx2 - bx1) * self.level
            if fill_to > bx1 + 1:
                c.create_line(bx1, by, fill_to, by, fill=RED, width=int(5 * s), capstyle="round")
        elif self.mode == "api_working":
            start = (t * 300) % 360
            r = 15 * s
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=-start, extent=270, style="arc",
                         outline=VIOLET, width=int(4 * s))
            c.create_text(88 * s, H * 0.38, text="Asking Claude…", anchor="w", fill=FG, font=title_font)
            c.create_text(88 * s, H * 0.64, text=self._clip(self.heard, 40), anchor="w", fill=MUTED, font=sub_font)
        elif self.mode == "api_done":
            col = GREEN if self.result_ok else RED
            r = 15 * s
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="")
            if self.result_ok:
                c.create_line(cx - 7 * s, cy, cx - 2 * s, cy + 6 * s, cx + 8 * s, cy - 6 * s, fill=BG,
                              width=int(3.5 * s), capstyle="round", joinstyle="round")
            else:
                c.create_line(cx - 6 * s, cy - 6 * s, cx + 6 * s, cy + 6 * s, fill=BG, width=int(3.5 * s), capstyle="round")
                c.create_line(cx - 6 * s, cy + 6 * s, cx + 6 * s, cy - 6 * s, fill=BG, width=int(3.5 * s), capstyle="round")
            title = "Claude • done" if self.result_ok else "Claude • failed"
            c.create_text(88 * s, H * 0.38, text=title, anchor="w", fill=FG, font=title_font)
            c.create_text(88 * s, H * 0.64, text=self._clip(self.detail, 44), anchor="w", fill=MUTED, font=sub_font)

    @staticmethod
    def _clip(text, n):
        text = (text or "").strip()
        return text if len(text) <= n else text[: n - 1] + "…"
