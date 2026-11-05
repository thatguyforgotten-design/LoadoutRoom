import copy
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop
from src.desktop_stats import competitive_stats, season_labels, peak_label


class PeakEpisodeTests(unittest.TestCase):
    def test_episode_follows_historical_peak_instead_of_current_act(self):
        labels = season_labels({"Seasons": [
            {"ID": "EP", "Type": "episode", "Name": "EPISODE 09"},
            {"ID": "OLD", "Type": "act", "Name": "ACT II", "ParentID": "ep"},
        ]})
        mmr = {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": {
            "now": {"CompetitiveTier": 12},
            "old": {"CompetitiveTier": 15, "WinsByTier": {"20": 1}},
        }}}}
        stats = competitive_stats(mmr, "now", season_names=labels)
        self.assertEqual(stats["peakRank"], "Diamond 3")
        self.assertEqual(stats["peakEpisode"], "EPISODE 09 / ACT II")
        self.assertEqual(stats["peakSeason"], "old")

    def test_historical_tier_mapping_keeps_the_same_episode(self):
        mmr = {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": {
            "old": {"CompetitiveTier": 24},
        }}}}
        stats = competitive_stats(mmr, "now", {"old": {24: "Radiant"}}, {"old": "EPISODE 02 / ACT I"})
        self.assertEqual(peak_label(stats), "Radiant · EPISODE 02 / ACT I")

    def test_missing_parent_and_missing_history_are_not_guessed(self):
        self.assertEqual(season_labels({"Seasons": [
            {"ID": "old", "Type": "act", "Name": "ACT I", "ParentID": "missing"},
            None,
        ]}), {})
        self.assertEqual(peak_label({"peakRank": "Gold 1"}), "Gold 1 · Episode unavailable")
        self.assertEqual(peak_label(competitive_stats({}, "now")), "Unavailable")

    def test_episode_refresh_does_not_rebuild_equipment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                desktop.appearance, "settings_path", return_value=Path(directory) / "updates.json"):
            root = tk.Tk()
            app = desktop.TrackerWindow(root, start_collector=False)
            try:
                app.toggle_sample()
                # Sample subject IDs are selected through the actual snapshot.
                player = app.snapshot["players"][0]
                app.choose_player(player["id"])
                root.update_idletasks()
                app.render_loadout()
                cards = app.cards.winfo_children()
                snapshot = copy.deepcopy(app.snapshot)
                snapshot["players"][0]["peakEpisode"] = "EPISODE 07 / ACT III"
                app.apply_snapshot(snapshot)
                self.assertIn("EPISODE 07 / ACT III", app.peak_label.cget("text"))
                self.assertEqual(cards, app.cards.winfo_children())
            finally:
                for callback in root.tk.call("after", "info"):
                    root.after_cancel(callback)
                app.close()
