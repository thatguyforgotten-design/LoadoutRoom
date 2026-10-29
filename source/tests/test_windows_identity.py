"""Read back the real Windows shell properties, including 64-bit COM values."""
import ctypes
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from ctypes import wintypes
from src import windows_identity as identity


class RelaunchTests(unittest.TestCase):
    def test_portable_launcher_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Loadout Room ") as folder:
            app = Path(folder) / "app"
            app.mkdir()
            launcher = Path(folder) / "LoadoutRoom.exe"
            launcher.touch()
            command, icon = identity.relaunch_details(app)
            self.assertEqual(command, '"' + str(launcher.resolve()) + '"')
            self.assertEqual(icon, str(app.resolve() / "assets" / "Logo.ico") + ",0")

    @unittest.skipUnless(os.name == "nt", "Windows shell integration")
    def test_shell_receives_name_icon_command_and_id(self):
        root = tk.Tk()
        root.withdraw()
        app = Path(__file__).resolve().parents[2] / "app"
        try:
            identity.set_process_identity()
            identity.set_window_identity(root, app)
            hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
            store = ctypes.c_void_p()
            iid = identity.GUID("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
            shell = ctypes.WinDLL("shell32")
            shell.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(identity.GUID), ctypes.POINTER(ctypes.c_void_p)]
            shell.SHGetPropertyStoreForWindow.restype = ctypes.c_long
            self.assertEqual(shell.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store)), 0)
            table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            get_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(identity.PROPERTYKEY), ctypes.POINTER(identity.PROPVARIANT))(table[5])
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])
            command, icon = identity.relaunch_details(app)
            try:
                for pid, expected in ((2, command), (3, icon), (4, "LoadoutRoom"), (5, identity.APP_ID)):
                    key = identity.PROPERTYKEY(identity.GUID("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid)
                    value = identity.PROPVARIANT()
                    self.assertGreaterEqual(get_value(store, ctypes.byref(key), ctypes.byref(value)), 0)
                    try:
                        self.assertEqual(value.vt, 31)  # VT_LPWSTR
                        self.assertEqual(ctypes.wstring_at(value.value.pointer), expected)
                    finally:
                        ctypes.windll.ole32.PropVariantClear(ctypes.byref(value))
            finally:
                release(store)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
