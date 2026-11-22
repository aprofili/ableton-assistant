"""Global push-to-talk trigger: any key or key combo (keyboard, or a Bluetooth/USB button that sends keys)."""
import threading

from pynput import keyboard

_MOD = {"ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
        "shift_l": "shift", "shift_r": "shift", "cmd_l": "cmd", "cmd_r": "cmd"}


def key_name(key):
    if isinstance(key, keyboard.Key):
        return _MOD.get(key.name, key.name)
    ch = getattr(key, "char", None)
    if ch and ch.isprintable() and ord(ch) >= 32:
        return ch.lower()
    vk = getattr(key, "vk", None)
    return f"vk{vk}" if vk is not None else str(key)


def parse_combo(s):
    return frozenset(p.strip().lower() for p in s.split("+") if p.strip())


def learn_combo(timeout=30):
    """Wait for the user to press a key/button, return its combo string like 'ctrl+alt+space'."""
    pressed, seen, done = set(), set(), threading.Event()

    def on_press(k):
        n = key_name(k)
        pressed.add(n)
        seen.add(n)

    def on_release(k):
        pressed.discard(key_name(k))
        if not pressed and seen:
            done.set()
            return False

    with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
        done.wait(timeout)
        l.stop()
    order = {"ctrl": 0, "alt": 1, "shift": 2, "cmd": 3}
    return "+".join(sorted(seen, key=lambda n: (order.get(n, 9), n))) if seen else None


class Trigger:
    """mode 'hold': record while held. 'toggle': press to start, press to stop.
    'tap': press to start, silence ends it."""

    def __init__(self, combo, mode, on_start, on_stop):
        self.combos = [parse_combo(combo)]
        self.mode = mode
        self.on_start, self.on_stop = on_start, on_stop
        self.pressed = set()
        self.active = False
        self.latched = False  # combo currently fully held (debounce key repeat)

    @property
    def combo(self):
        return self.combos[0]

    @combo.setter
    def combo(self, value):
        self.combos[0] = value

    def add_combo(self, combo):
        """Extra key that also triggers voice (e.g. the pad's voice button)."""
        self.combos.append(parse_combo(combo))

    def _held(self):
        return any(c <= self.pressed for c in self.combos)

    def stop_from_outside(self):
        if self.active:
            self.active = False
            self.on_stop()

    def _press(self, k):
        self.pressed.add(key_name(k))
        if self._held() and not self.latched:
            self.latched = True
            if self.mode == "hold":
                if not self.active:
                    self.active = True
                    self.on_start()
            elif self.mode == "toggle":
                if not self.active:
                    self.active = True
                    self.on_start()
                else:
                    self.active = False
                    self.on_stop()
            elif self.mode == "tap" and not self.active:
                self.active = True
                self.on_start()

    def _release(self, k):
        self.pressed.discard(key_name(k))
        if not self._held():
            self.latched = False
            if self.mode == "hold" and self.active:
                self.active = False
                self.on_stop()

    def run(self):
        with keyboard.Listener(on_press=self._press, on_release=self._release) as l:
            l.join()
