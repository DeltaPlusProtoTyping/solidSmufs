"""3Dconnexion SpaceMouse input, read straight from the device through Windows' HID functions.

No 3Dconnexion SDK or library is needed: the SpaceMouse is a HID "multi-axis controller" (usage page 1,
usage 8) and sends its six axes as plain input reports. Newer devices send one report (id 1) with
all six as little-endian int16s (tx, ty, tz, rx, ry, rz); older ones send translation (id 1) and
rotation (id 2) separately, and buttons as id 3. Values run about ±350.

Reader(on_motion).start() reads every SpaceMouse it finds in a thread of its own and calls
on_motion([tx, ty, tz, rx, ry, rz]) with the latest values (all zeros when the cap is let go).
"""

import ctypes
import logging
import struct
import threading
import time
from ctypes import wintypes

log = logging.getLogger("solidsmufs")

VENDORS = {0x256F, 0x046D}  # 3Dconnexion, and Logitech (the older 3Dconnexion devices)
GAP, SPIKE = 0.15, 150  # seconds between reports, and change in one report, worth noting in the log
_LOGITECH_SPACE = range(0xC600, 0xC700)  # Logitech's 3Dconnexion product ids (C6xx); its other devices are ignored


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


class _IfData(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("guid", _GUID), ("flags", wintypes.DWORD), ("reserved", ctypes.c_void_p)]


class _Attrs(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT), ("ProductID", wintypes.USHORT),
                ("VersionNumber", wintypes.USHORT)]


class _Caps(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT), ("InputReportByteLength", wintypes.USHORT),
                ("OutputReportByteLength", wintypes.USHORT), ("FeatureReportByteLength", wintypes.USHORT),
                ("Reserved", wintypes.USHORT * 17), ("rest", wintypes.USHORT * 10)]


def devices():
    """[(device path, input report length)] of the SpaceMice plugged in (their multi-axis collection)."""
    hid, setup, k32 = ctypes.windll.hid, ctypes.windll.setupapi, ctypes.windll.kernel32
    setup.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setup.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_GUID), wintypes.DWORD, ctypes.POINTER(_IfData)]
    setup.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IfData), ctypes.c_void_p, wintypes.DWORD,
                                                       ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    setup.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    k32.CreateFileW.restype = wintypes.HANDLE
    guid = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setup.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)  # DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    found = []
    try:
        i = 0
        while True:
            ifd = _IfData(cbSize=ctypes.sizeof(_IfData))
            if not setup.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid), i, ctypes.byref(ifd)):
                break
            i += 1
            need = wintypes.DWORD()
            setup.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6  # cbSize of the detail header
            if not setup.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(ifd), buf, need, None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            h = k32.CreateFileW(path, 0, 3, None, 3, 0, None)  # no access needed to read the attributes
            if not h or h == wintypes.HANDLE(-1).value:
                continue
            try:
                a = _Attrs(Size=ctypes.sizeof(_Attrs))
                if not hid.HidD_GetAttributes(h, ctypes.byref(a)) or a.VendorID not in VENDORS:
                    continue
                if a.VendorID == 0x046D and a.ProductID not in _LOGITECH_SPACE:
                    continue
                pp = ctypes.c_void_p()
                if not hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
                    continue
                caps = _Caps()
                hid.HidP_GetCaps(pp, ctypes.byref(caps))
                hid.HidD_FreePreparsedData(pp)
                if caps.UsagePage == 1 and caps.Usage == 8:  # generic desktop / multi-axis controller
                    found.append((path, int(caps.InputReportByteLength)))
            finally:
                k32.CloseHandle(h)
    finally:
        setup.SetupDiDestroyDeviceInfoList(info)
    return found


def parse(report, state):
    """Update state ([tx, ty, tz, rx, ry, rz]) from one input report; True when it held axis values."""
    if len(report) < 7:
        return False
    rid = report[0]
    if rid == 1 and len(report) >= 13:
        state[:] = struct.unpack_from("<6h", report, 1)
        return True
    if rid == 1:
        state[0:3] = struct.unpack_from("<3h", report, 1)
        return True
    if rid == 2:
        state[3:6] = struct.unpack_from("<3h", report, 1)
        return True
    return False  # buttons (id 3) and anything else


class Reader:
    """Reads the SpaceMice in background threads; on_motion([tx, ty, tz, rx, ry, rz]) on each change."""

    def __init__(self, on_motion):
        self.on_motion = on_motion
        self.stopped = False
        self.handles = []

    def start(self):
        try:
            found = devices()
        except Exception:  # not Windows, or no HID functions: no SpaceMouse
            log.exception("SpaceMouse: couldn't list HID devices")
            return 0
        for path, length in found:
            threading.Thread(target=self._read, args=(path, max(length, 13)), daemon=True).start()
        log.info("SpaceMouse: %d found", len(found))
        return len(found)

    def stop(self):
        self.stopped = True
        k32 = ctypes.windll.kernel32
        for h in self.handles:
            k32.CancelIoEx(h, None)
            k32.CloseHandle(h)

    def _read(self, path, length):
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wintypes.HANDLE
        h = k32.CreateFileW(path, 0x80000000, 3, None, 3, 0, None)  # GENERIC_READ, shared with 3DxWare
        if not h or h == wintypes.HANDLE(-1).value:
            log.info("SpaceMouse: couldn't open %s (error %d)", path, k32.GetLastError())
            return
        self.handles.append(h)
        buf, got, state = ctypes.create_string_buffer(length), wintypes.DWORD(), [0] * 6
        last, before, run = time.monotonic(), [0] * 6, None
        while not self.stopped:
            if not k32.ReadFile(h, buf, length, ctypes.byref(got), None):
                if not self.stopped:
                    log.info("SpaceMouse: reading stopped (error %d)", k32.GetLastError())
                return
            if parse(buf.raw[:got.value], state):
                now = time.monotonic()
                held, step = any(abs(x) > 20 for x in before), max(abs(a - b) for a, b in zip(state, before))
                if held and (now - last > GAP or step > SPIKE):  # for telling device hiccups from view ones
                    log.info("SpaceMouse: %.0f ms since the last report, biggest change %d: %s -> %s",
                             1000 * (now - last), step, before, state)
                flipped = [i for i in range(6) if state[i] * before[i] < 0 and min(abs(state[i]), abs(before[i])) > 10]
                if flipped:  # the cap's value reversing outright between two reports
                    log.info("SpaceMouse: axis %s reversed: %s -> %s", flipped, before, state)
                moving = any(state)
                if moving and not run:
                    run = [now, 0]
                if run:
                    run[1] += 1
                if run and not moving:
                    log.info("SpaceMouse: a move of %.1f s, %d reports", now - run[0], run[1])
                    run = None
                last, before = now, list(state)
                try:
                    self.on_motion(list(state))
                except Exception:
                    log.exception("SpaceMouse: motion handler failed")


if __name__ == "__main__":  # move the cap and watch the values: python -m solidsmufs.spacemouse
    print(devices())
    r = Reader(lambda s: print(s))
    if r.start():
        time.sleep(15)
