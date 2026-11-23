"""Child process: send the XPPen raw-mode init packet (02 b0 04 00 00 ...) to the pad's vendor interface."""
import ctypes
import ctypes.wintypes as wt
import sys


def main():
    k = ctypes.windll.kernel32
    h = ctypes.windll.hid
    u = ctypes.windll.user32

    class DL(ctypes.Structure):
        _fields_ = [("hDevice", wt.HANDLE), ("dwType", wt.DWORD)]

    n = wt.UINT(0)
    u.GetRawInputDeviceList(None, ctypes.byref(n), ctypes.sizeof(DL))
    arr = (DL * n.value)()
    u.GetRawInputDeviceList(arr, ctypes.byref(n), ctypes.sizeof(DL))
    paths = []
    for d in arr:
        if d.dwType != 2:
            continue
        sz = wt.UINT(0)
        u.GetRawInputDeviceInfoW(d.hDevice, 0x20000007, None, ctypes.byref(sz))
        buf = ctypes.create_unicode_buffer(sz.value + 1)
        u.GetRawInputDeviceInfoW(d.hDevice, 0x20000007, buf, ctypes.byref(sz))
        if "VID_28BD" in buf.value.upper():
            paths.append(buf.value)
    k.CreateFileW.restype = ctypes.c_void_p
    k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    h.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    h.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    sent = 0
    for name in paths:
        hd = k.CreateFileW(name, 0xC0000000, 3, None, 3, 0, None)
        if hd in (None, ctypes.c_void_p(-1).value):
            print(f"open failed err={k.GetLastError()} {name[-40:]}")
            continue
        pre = ctypes.c_void_p()
        outlen = 0
        if h.HidD_GetPreparsedData(hd, ctypes.byref(pre)):
            caps = (ctypes.c_ushort * 8)()
            h.HidP_GetCaps(pre, caps)
            outlen = caps[3]
        if outlen:
            buf = bytearray(outlen)
            buf[0:5] = bytes([0x02, 0xB0, 0x04, 0x00, 0x00])
            wrote = wt.DWORD(0)
            ok = k.WriteFile(hd, bytes(buf), outlen, ctypes.byref(wrote), None)
            print(f"{name[-40:]} outlen={outlen} write ok={bool(ok)} wrote={wrote.value}")
            sent += bool(ok)
        k.CloseHandle(ctypes.c_void_p(hd))
    print(f"sent to {sent} interface(s)")


if __name__ == "__main__":
    if sys.platform == "win32":
        main()
