"""Send keyboard shortcuts to Ableton (focusing its window first on Windows)."""
import sys
import time


def find_ableton_hwnd():
    """Visible top-level Live window handle, or None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith("Ableton Live") or " - Ableton Live" in buf.value:
                    found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def find_window_by_exe(exe_name):
    """Largest visible top-level window owned by a process whose image name is exe_name (case-insensitive)."""
    if sys.platform != "win32":
        return None
    import ctypes
    import os
    from ctypes import wintypes

    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    best = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd) and u.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                buf = ctypes.create_unicode_buffer(520)
                n = wintypes.DWORD(520)
                k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
                k.CloseHandle(h)
                if os.path.basename(buf.value).lower() == exe_name.lower():
                    r = wintypes.RECT()
                    u.GetWindowRect(hwnd, ctypes.byref(r))
                    best.append(((r.right - r.left) * (r.bottom - r.top), hwnd))
        return True

    u.EnumWindows(cb, 0)
    return max(best)[1] if best else None


def focus_window(hwnd):
    """Bring any window to the front."""
    if sys.platform != "win32" or not hwnd:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    fg = user32.GetForegroundWindow()
    if fg != hwnd:
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        their = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        if their and their != me:
            user32.AttachThreadInput(me, their, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if their and their != me:
            user32.AttachThreadInput(me, their, False)
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def release_held_modifiers():
    """Lift Ctrl/Alt/Shift that are physically/driver held (the pad sends Ctrl+Alt+Shift+Fn), so keys
    and wheel events we inject are not read as modified."""
    if sys.platform != "win32":
        return
    import ctypes
    u = ctypes.windll.user32
    for vk in (0x11, 0x12, 0x10, 0xA2, 0xA3, 0xA4, 0xA5, 0xA0, 0xA1):
        if u.GetAsyncKeyState(vk) & 0x8000:
            u.keybd_event(vk, 0, 0x0002, 0)


def ableton_in_front():
    """True if the foreground window belongs to the Live process (main window or a plugin window)."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    live = find_ableton_hwnd()
    if not live:
        return True  # nothing to focus
    fg = u.GetForegroundWindow()
    if not fg:
        return False
    pid_fg, pid_live = wintypes.DWORD(), wintypes.DWORD()
    u.GetWindowThreadProcessId(fg, ctypes.byref(pid_fg))
    u.GetWindowThreadProcessId(live, ctypes.byref(pid_live))
    return pid_fg.value == pid_live.value and not u.IsIconic(live)


def focus_ableton():
    """Bring Live's main window to the front (no-op if it already is). Avoids the Alt-tap trick unless
    needed: a lone Alt press/release activates Live's menu bar, which swallowed the next key (Tab)."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = find_ableton_hwnd()
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if user32.GetForegroundWindow() == hwnd:
        return True
    fg = user32.GetForegroundWindow()
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    their = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    if their and their != me:
        user32.AttachThreadInput(me, their, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if their and their != me:
        user32.AttachThreadInput(me, their, False)
    if user32.GetForegroundWindow() != hwnd:  # fallback: Alt tap, then close the menu it opens
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
    time.sleep(0.08)
    return True


class KeySender:
    def __init__(self):
        from pynput.keyboard import Controller, Key

        self.kb = Controller()
        self.Key = Key

    def _parse(self, part):
        part = part.strip().lower()
        aliases = {"ctrl": "ctrl", "control": "ctrl", "cmd": "cmd", "win": "cmd", "return": "enter",
                   "esc": "esc", "escape": "esc", "del": "delete", "pgup": "page_up", "pgdn": "page_down"}
        part = aliases.get(part, part)
        if len(part) == 1:
            return part
        return getattr(self.Key, part)

    def press(self, combo):
        release_held_modifiers()
        focus_ableton()
        parts = [self._parse(p) for p in combo.split("+")]
        mods, key = parts[:-1], parts[-1]
        for m in mods:
            self.kb.press(m)
        self.kb.press(key)
        self.kb.release(key)
        for m in reversed(mods):
            self.kb.release(m)
