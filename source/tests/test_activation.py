import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src import desktop_updates as updates


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / "releases" / "new"
        self.release.mkdir(parents=True)
        self.exe = self.release / "LoadoutRoom.exe"
        self.exe.touch()
        self.legacy = self.release / "LoadoutRoom1.0.exe"
        self.legacy.touch()
        self.pointer = self.root / "active-release.txt"
        self.settings = patch.object(updates, "settings_path", return_value=self.root / "updates.json")
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_new_process_sees_new_pointer(self):
        self.pointer.write_text("old", encoding="utf-8")
        observed = []
        def launch(args, cwd):
            observed.append(self.pointer.read_text(encoding="utf-8"))
            self.assertEqual(args, [str(self.exe.resolve())])
            self.assertEqual(cwd, str(self.release.resolve()))
        updates.activate_release(self.exe, launch)
        self.assertEqual(observed, [str(self.legacy.resolve())])

    def test_failed_launch_restores_old_selection(self):
        self.pointer.write_text("old", encoding="utf-8")
        with self.assertRaises(OSError):
            updates.activate_release(self.exe, lambda *a, **kw: (_ for _ in ()).throw(OSError("failed")))
        self.assertEqual(self.pointer.read_text(encoding="utf-8"), "old")

    def test_failed_first_launch_leaves_no_pointer(self):
        with self.assertRaises(OSError):
            updates.activate_release(self.exe, lambda *a, **kw: (_ for _ in ()).throw(OSError("failed")))
        self.assertFalse(self.pointer.exists())

    def test_outside_launcher_is_rejected(self):
        outside = self.root / "LoadoutRoom.exe"
        outside.touch()
        with self.assertRaises(ValueError):
            updates.activate_release(outside, lambda *a, **kw: self.fail("must not launch"))


if __name__ == "__main__":
    unittest.main()
