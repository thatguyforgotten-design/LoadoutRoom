import queue
import unittest
from unittest.mock import patch
from src.desktop_backend import Collector, NotReady


class RosterLoadingTests(unittest.TestCase):
    def test_roster_arrives_before_optional_content_and_survives_failure(self):
        events = queue.Queue()
        collector = Collector(events)
        self.addCleanup(collector.client.close)
        collector.client.puuid = "self"
        observed = []
        def get(kind, endpoint, allow_missing=False):
            if "/players/self" in endpoint and kind == "glz":
                return {"MatchID": "match"}
            if endpoint.endswith("/matches/match"):
                return {"Players": [
                    {"Subject": "self", "TeamID": "Blue"},
                    {"Subject": "hidden", "TeamID": "Red", "PlayerIdentity": {"Incognito": True, "HideAccountLevel": True, "AccountLevel": 99}},
                ]}
            if kind == "content":
                snapshots = [e[1] for e in list(events.queue) if e[0] == "snapshot"]
                self.assertEqual(len(snapshots[-1]["players"]), 2)
                self.assertIsNone(snapshots[-1]["players"][1]["level"])
                observed.append("roster before content")
                raise NotReady("content unavailable")
            return {}
        collector.client.get = get
        collector.client.names = lambda players: {}
        with patch("src.desktop_backend.public_catalog", return_value=[]):
            collector.collect()
        snapshots = [e[1] for e in list(events.queue) if e[0] == "snapshot"]
        self.assertEqual(observed, ["roster before content"])
        self.assertTrue(all(len(s["players"]) == 2 for s in snapshots))
        self.assertFalse(snapshots[-1]["partial"])
        self.assertIsNone(snapshots[-1]["players"][1]["level"])


if __name__ == "__main__":
    unittest.main()
