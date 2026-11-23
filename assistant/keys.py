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
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = find_ableton_hwnd()
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Alt tap lets SetForegroundWindow succeed when we aren't the foreground process
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
