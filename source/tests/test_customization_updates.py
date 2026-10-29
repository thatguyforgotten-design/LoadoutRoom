import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
import desktop
from src import desktop_appearance as appearance


class CustomizationAndUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = patch.object(appearance, "settings_path", return_value=Path(self.temp.name) / "updates.json")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.root = tk.Tk()
        self.app = desktop.TrackerWindow(self.root, start_collector=False)
        def close():
            self.root.update_idletasks()
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            self.app.close()
        self.addCleanup(close)
        self.release = {"version": "1.0.24", "notes": "Test"}

    def test_startup_badge_does_not_prompt_or_install(self):
        with patch.object(desktop.messagebox, "askyesno") as prompt, patch.object(desktop.updates, "install_release") as install:
            self.app.handle_update(("update_available", self.release, True))
            self.assertEqual(self.app.update_button.cget("text"), "Update available")
            prompt.assert_not_called()
            install.assert_not_called()

    def test_declining_keeps_badge_and_never_installs(self):
        with patch.object(desktop.messagebox, "askyesno", return_value=False), patch.object(desktop.updates, "install_release") as install:
            self.app.handle_update(("update_available", self.release, False))
            self.assertEqual(self.app.available_release, self.release)
            self.assertEqual(self.app.update_button.cget("text"), "Update available")
            install.assert_not_called()
        self.app.handle_update(("update_available", None, True))
        self.assertEqual(self.app.update_button.cget("text"), "Updates")

    def test_background_persists_and_panel_color_is_preserved(self):
        panel = self.app.player_title.master
        panel_color = panel.cget("background")
        appearance.save_background("#FFFFFF")
        self.assertEqual(appearance.load_background(desktop.BG), "#ffffff")
        self.app.apply_background("#ffffff")
        self.assertEqual(self.root.cget("background"), "#ffffff")
        self.assertEqual(self.app.version_label.cget("foreground"), "#475569")
        self.app.apply_background(desktop.PANEL)
        self.app.apply_background(desktop.BG)
        self.assertEqual(panel.cget("background"), panel_color)
        self.assertEqual(self.app.version_label.cget("foreground"), desktop.MUTED)
        appearance.save_background(desktop.BG)
        self.assertEqual(appearance.load_background(desktop.BG), desktop.BG)

    def test_corrupt_preference_falls_back(self):
        (Path(self.temp.name) / "appearance.json").write_text('{"background":"bad"}', encoding="utf-8")
        self.assertEqual(appearance.load_background(desktop.BG), desktop.BG)

    def test_update_badge_and_customization_fit_at_minimum_size(self):
        self.app.set_update_indicator(self.release)
        self.root.geometry("1080x700")
        self.root.update_idletasks()
        for widget in (self.app.update_button, self.app.customize_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreaterEqual(widget.winfo_rootx(), self.root.winfo_rootx())
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())


if __name__ == "__main__":
    unittest.main()
