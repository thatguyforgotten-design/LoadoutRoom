"""Windows taskbar identity for the Python-hosted LoadoutRoom window."""
import ctypes
import os
import subprocess
import sys
import uuid
from pathlib import Path
from ctypes import wintypes

APP_ID = "LoadoutRoom.Desktop"


def relaunch_details(app_dir):
    app_dir = Path(app_dir).resolve()
    launcher = app_dir.parent / "LoadoutRoom.exe"
    if launcher.is_file():
        command = subprocess.list2cmdline([str(launcher)])
    else:
        # Source checkouts still need the script when relaunched from the taskbar.
        command = subprocess.list2cmdline([sys.executable, str(app_dir / "desktop.py")])
    return command, str(app_dir / "assets" / "Logo.ico") + ",0"


def set_process_identity():
    if os.name == "nt":
        shell = ctypes.WinDLL("shell32")
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        _check(shell.SetCurrentProcessExplicitAppUserModelID(APP_ID))


def _check(result):
    if result < 0:
        raise OSError("Windows taskbar identity failed: 0x%08X" % (result & 0xffffffff))


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        ctypes.memmove(ctypes.addressof(self), uuid.UUID(value).bytes_le, 16)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class _Value(ctypes.Union):
    _fields_ = [("pointer", ctypes.c_void_p),
                ("storage", ctypes.c_ubyte * (16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 8))]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("reserved1", ctypes.c_ushort),
                ("reserved2", ctypes.c_ushort), ("reserved3", ctypes.c_ushort),
                ("value", _Value)]


def set_window_identity(root, app_dir):
    if os.name != "nt":
        return
    root.update_idletasks()
    user = ctypes.WinDLL("user32")
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    hwnd = user.GetAncestor(root.winfo_id(), 2)  # GA_ROOT: Tk's actual top-level wrapper.
    if not hwnd:
        raise OSError("LoadoutRoom has no top-level Windows window")
    shell = ctypes.WinDLL("shell32")
    shell.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(GUID),
                                                  ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    store = ctypes.c_void_p()
    iid = GUID("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")  # IPropertyStore
    _check(shell.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store)))
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                  ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(vtable[6])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    command, icon = relaunch_details(app_dir)
    try:
        # Windows requires a window-level ID and the command/name pair together.
        for pid, text in ((2, command), (4, "LoadoutRoom"), (3, icon), (5, APP_ID)):
            key = PROPERTYKEY(GUID("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid)
            value = PROPVARIANT()
            # SetValue copies its input. Keep this Python-owned buffer alive for
            # the call; it must not be passed to PropVariantClear/CoTaskMemFree.
            buffer = ctypes.create_unicode_buffer(text)
            value.vt = 31  # VT_LPWSTR
            value.value.pointer = ctypes.cast(buffer, ctypes.c_void_p).value
            _check(set_value(store, ctypes.byref(key), ctypes.byref(value)))
        _check(commit(store))
    finally:
        release(store)
