"""Draw with the laptop's discrete graphics chip, not the integrated one.

Laptops with two GPUs (Intel + NVIDIA / AMD) start apps on the integrated chip, and Qt's Chromium
then draws the 3D view there. Old integrated drivers flicker and stutter; the discrete chip is much
faster. Chromium's own switches for this (--force_high_performance_gpu, --use-adapter-luid) are
ignored inside Qt, but Chromium draws on whichever adapter Qt's Direct3D picks, and Qt takes that
from QT_D3D_ADAPTER_INDEX. So before Qt starts, pick the adapter with the most dedicated video memory.

Set QT_D3D_ADAPTER_INDEX yourself to choose another, or SOLIDSMURFS_GPU=integrated to leave it to Windows.
"""

import ctypes
import os
import sys
from ctypes import wintypes


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _DESC1(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", _LUID), ("Flags", ctypes.c_uint)]


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


_IID_IDXGIFactory1 = _GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
_SOFTWARE = 0x2  # DXGI_ADAPTER_FLAG_SOFTWARE (Microsoft Basic Render Driver)


def _vcall(obj, index, *args):
    """Call COM method `index` of obj's vtable; every argument here is a pointer or a UINT."""
    vt = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    types = [ctypes.c_uint if isinstance(a, int) else ctypes.c_void_p for a in args]
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(vt[index])
    return fn(obj, *[a if isinstance(a, int) else ctypes.cast(a, ctypes.c_void_p) for a in args])


def adapters():
    """[(index, name, dedicated video memory in bytes, is software)] in Direct3D's own order."""
    factory = ctypes.c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(_IID_IDXGIFactory1), ctypes.byref(factory)) != 0:
        return []
    out = []
    try:
        i = 0
        while True:
            ad = ctypes.c_void_p()
            if _vcall(factory, 12, i, ctypes.pointer(ad)) != 0:  # IDXGIFactory1::EnumAdapters1
                break
            d = _DESC1()
            _vcall(ad, 10, ctypes.pointer(d))  # IDXGIAdapter1::GetDesc1
            out.append((i, d.Description, int(d.DedicatedVideoMemory), bool(d.Flags & _SOFTWARE)))
            _vcall(ad, 2)  # Release
            i += 1
    finally:
        _vcall(factory, 2)
    return out


def prefer_discrete():
    """Point Qt (and so the 3D view) at the GPU with the most video memory. Returns its name, or None
    when nothing was changed."""
    if sys.platform != "win32" or "QT_D3D_ADAPTER_INDEX" in os.environ or os.environ.get("SOLIDSMURFS_GPU") == "integrated":
        return None
    try:
        hw = [a for a in adapters() if not a[3]]
    except Exception:  # no DXGI (very old Windows, remote session): leave it to Windows
        return None
    if len(hw) < 2:
        return None
    best = max(hw, key=lambda a: a[2])
    if best[0] == 0:
        return None
    os.environ["QT_D3D_ADAPTER_INDEX"] = str(best[0])
    return best[1]
