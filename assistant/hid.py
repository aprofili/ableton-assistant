"""Raw HID tap for the XPPen pad (Windows Raw Input). Reads the pad's own reports alongside the driver,
so button/dial signals can be handled here without driver key mappings.
Phase 1: discovery. Logs every report from XP-Pen devices to logs/pad_hid.log (deduplicated, capped)."""
import ctypes
import ctypes.wintypes as wt
import logging
import os
import sys
import threading
import time

log = logging.getLogger("assistant")
XPPEN_VID = 0x28BD
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP = os.path.join(HERE, "logs", "pad_hid.log")

RIM_TYPEHID = 2
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x100
RIDEV_DEVNOTIFY = 0x2000
WM_INPUT_DEVICE_CHANGE = 0x00FE
RIDEV_PAGEONLY = 0x20
FALLBACK_PAGES = [0x01, 0x0C, 0x0D, 0xFF00, 0xFF01, 0xFF02, 0xFF0A, 0xFF0B, 0xFF0C, 0xFF0D, 0xFF0E, 0xFF0F]
WM_INPUT = 0x00FF
HWND_MESSAGE = -3


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wt.HANDLE), ("dwType", wt.DWORD)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT), ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD), ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]


class HidTap:
    def __init__(self, on_report=None, on_key=None):
        self.on_report = on_report
        self.on_key = on_key  # on_report(device_name, bytes)
        self._names = {}
        self._seen = {}
        self._count = 0
        self._last_report = time.time()

    def start(self):
        if sys.platform != "win32":
            return
        threading.Thread(target=self._run, daemon=True, name="pad-hid").start()

    def _devname(self, h):
        if h in self._names:
            return self._names[h]
        u = ctypes.windll.user32
        n = wt.UINT(0)
        u.GetRawInputDeviceInfoW(h, RIDI_DEVICENAME, None, ctypes.byref(n))
        buf = ctypes.create_unicode_buffer(n.value + 1)
        u.GetRawInputDeviceInfoW(h, RIDI_DEVICENAME, buf, ctypes.byref(n))
        self._names[h] = buf.value
        return buf.value

    def _xppen_pages(self):
        """(usagePage, usage) of each XP-Pen HID interface, found by enumerating devices."""
        u = ctypes.windll.user32
        n = wt.UINT(0)
        u.GetRawInputDeviceList(None, ctypes.byref(n), ctypes.sizeof(RAWINPUTDEVICELIST))
        arr = (RAWINPUTDEVICELIST * n.value)()
        u.GetRawInputDeviceList(arr, ctypes.byref(n), ctypes.sizeof(RAWINPUTDEVICELIST))
        pages = set()
        for d in arr:
            self._dump(f"rawdev type={d.dwType} {self._devname(d.hDevice)[:110]}")
            if d.dwType != RIM_TYPEHID:
                continue
            name = self._devname(d.hDevice).upper()
            if "VID_28BD" not in name:
                continue
            # RID_DEVICE_INFO: cbSize, dwType, then hid {vid, pid, ver, usagePage, usage}
            buf = ctypes.create_string_buffer(64)
            sz = wt.UINT(64)
            ctypes.memset(buf, 0, 64)
            ctypes.c_ulong.from_buffer(buf).value = 32
            r = u.GetRawInputDeviceInfoW(ctypes.c_void_p(d.hDevice), RIDI_DEVICEINFO, buf, ctypes.byref(sz))
            if r in (0, -1, 0xFFFFFFFF):
                self._dump(f"deviceinfo failed r={r} err={ctypes.windll.kernel32.GetLastError()}")
            import struct
            page, usage = struct.unpack_from("<HH", buf.raw, 20)  # after cbSize, dwType, vid, pid, version
            pages.add((page, usage))
            self._dump(f"device {name} page=0x{page:04X} usage=0x{usage:04X}")
        return pages

    def enable_raw_mode(self):
        """Switch the pad to raw mode like the XPPen driver does. Runs in a short-lived child process with a
        timeout so a stuck HID call can never freeze the assistant."""
        import subprocess
        try:
            r = subprocess.run([sys.executable, "-I", "-m", "assistant.hidinit"], cwd=HERE, capture_output=True,
                               text=True, timeout=8, creationflags=0x08000000)
            for line in (r.stdout + r.stderr).splitlines():
                self._dump("rawmode " + line)
            log.info("Pad raw mode: %s", (r.stdout.strip().splitlines() or ["no output"])[-1])
        except subprocess.TimeoutExpired:
            self._dump("rawmode child timed out")
            log.info("Pad raw mode: timed out")

    def _xppen_paths(self):
        u = ctypes.windll.user32
        n = wt.UINT(0)
        u.GetRawInputDeviceList(None, ctypes.byref(n), ctypes.sizeof(RAWINPUTDEVICELIST))
        arr = (RAWINPUTDEVICELIST * n.value)()
        u.GetRawInputDeviceList(arr, ctypes.byref(n), ctypes.sizeof(RAWINPUTDEVICELIST))
        return [self._devname(d.hDevice) for d in arr
                if d.dwType == RIM_TYPEHID and "VID_28BD" in self._devname(d.hDevice).upper()]

    def _dump(self, line):
        try:
            os.makedirs(os.path.dirname(DUMP), exist_ok=True)
            with open(DUMP, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + line + "\n")
        except OSError:
            pass

    def _run(self):
        try:
            self._loop()
        except Exception:
            log.exception("HID tap failed")

    def _loop(self):
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        def proc(hwnd, msg, wp, lp):
            if msg == WM_INPUT:
                try:
                    self._on_input(lp)
                except Exception:
                    log.exception("hid input")
            elif msg == WM_INPUT_DEVICE_CHANGE and wp == 1:  # a device arrived (pad switched on / replugged)
                try:
                    if "VID_28BD" in self._devname(lp).upper():
                        self._schedule_init(1.5, "pad connected")
                except Exception:
                    log.exception("hid device change")
            return u.DefWindowProcW(hwnd, msg, wp, lp)

        self._proc = WNDPROC(proc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HANDLE),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR)]

        wc = WNDCLASS()
        wc.lpfnWndProc = self._proc
        wc.hInstance = k.GetModuleHandleW(None)
        wc.lpszClassName = "AbletonAssistantHid"
        u.RegisterClassW(ctypes.byref(wc))
        u.CreateWindowExW.restype = wt.HWND
        u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        hwnd = u.CreateWindowExW(0, wc.lpszClassName, "hid", 0, 0, 0, 0, 0, wt.HWND(HWND_MESSAGE), None,
                                 wc.hInstance, None)
        pages = {(p, u_) for p, u_ in self._xppen_pages() if p}
        reg = [RAWINPUTDEVICE(p, us, RIDEV_INPUTSINK | RIDEV_DEVNOTIFY, hwnd) for p, us in pages]
        # also register whole usage pages (only XP-Pen reports are kept in _on_input)
        reg += [RAWINPUTDEVICE(p, 0, RIDEV_INPUTSINK | RIDEV_PAGEONLY | RIDEV_DEVNOTIFY, hwnd) for p in FALLBACK_PAGES]
        ok = 0
        for r in reg:  # one by one: a single rejected entry must not drop the rest
            one = (RAWINPUTDEVICE * 1)(r)
            if u.RegisterRawInputDevices(one, 1, ctypes.sizeof(RAWINPUTDEVICE)):
                ok += 1
            else:
                self._dump(f"register failed page=0x{r.usUsagePage:04X} usage=0x{r.usUsage:04X} err={k.GetLastError()}")
        log.info("HID tap registered (%s/%s entries)", ok, len(reg))
        try:
            self.enable_raw_mode()
            threading.Thread(target=self._keep_raw, daemon=True, name="pad-rawmode").start()
        except Exception:
            log.exception("raw mode failed")
        msg = wt.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    _init_at = 0.0

    def _schedule_init(self, delay, why):
        """Re-send the raw-mode packet shortly (debounced). Used on reconnect or when the pad is seen in
        keyboard mode."""
        now = time.time()
        if now - self._init_at < 4.0:
            return
        self._init_at = now
        log.info("Pad raw mode re-init (%s)", why)

        def go():
            time.sleep(delay)
            try:
                self.enable_raw_mode()
            except Exception:
                log.exception("raw mode re-init")
        threading.Thread(target=go, daemon=True, name="pad-reinit").start()

    def _keep_raw(self):
        """The pad drops back to keyboard mode when it reconnects (wireless sleep/wake): re-send every 5 minutes as a safety net."""
        while True:
            time.sleep(300)
            try:
                self.enable_raw_mode()
            except Exception:
                log.exception("raw mode resend")

    def _on_input(self, lparam):
        u = ctypes.windll.user32
        sz = wt.UINT(0)
        hs = ctypes.sizeof(RAWINPUTHEADER)
        u.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(sz), hs)
        buf = ctypes.create_string_buffer(sz.value)
        u.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(sz), hs)
        hdr = RAWINPUTHEADER.from_buffer(buf)
        name = self._devname(hdr.hDevice)
        if "VID_28BD" not in name.upper():
            return
        self._last_report = time.time()
        if hdr.dwType == 1:  # keyboard: the pad is in keyboard mode -> switch it to raw mode
            self._schedule_init(0.3, "pad in keyboard mode")
            import struct
            make, flags, _r, vkey, msg = struct.unpack_from("<HHHHI", buf.raw, hs)
            self._dump(f"key {name[-40:-30]} vk=0x{vkey:02X} make=0x{make:02X} flags={flags} msg=0x{msg:X}")
            if self.on_key:
                self.on_key(name, vkey, not (flags & 1), make)
            return
        if hdr.dwType == 0:  # mouse (dial wheel in default mode)
            import struct
            _f, _p, bflags, bdata = struct.unpack_from("<HHHh", buf.raw, hs)
            self._dump(f"mouse {name[-40:-30]} buttons=0x{bflags:04X} data={bdata}")
            return
        if hdr.dwType != RIM_TYPEHID:
            return
        off = hs
        size_hid, count = ctypes.c_ulong.from_buffer(buf, off).value, ctypes.c_ulong.from_buffer(buf, off + 4).value
        data = bytes(buf.raw[off + 8: off + 8 + size_hid * count])
        for i in range(count):
            rep = data[i * size_hid:(i + 1) * size_hid]
            if len(rep) >= 4 and rep[0] == 2 and rep[1] == 0xF8 and rep[2] == 2 and rep[3] == 1:
                self._schedule_init(0.5, "reconnect report")
            if self.on_report:
                self.on_report(name, rep)
            if self._count < 3000:
                self._count += 1
                self._dump(f"report {name[-24:]} {rep.hex(' ')}")
