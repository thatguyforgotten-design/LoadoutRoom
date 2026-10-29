import io
import unittest
from pathlib import Path
from unittest.mock import patch
from src.desktop_backend import read_connection_info, NotReady


class ConnectionLogTests(unittest.TestCase):
    def read(self, data):
        with patch.object(Path, "open", return_value=io.BytesIO(data)):
            return read_connection_info("ShooterGame.log")

    def test_startup_version_is_retained_after_log_exceeds_tail_limit(self):
        startup = b"CI server version: release-test-shipping-1\nhttps://glz-eu-1.eu.a.pvp.net\n"
        recent = b"\nhttps://pd.na.a.pvp.net\nhttps://glz-na-1.na.a.pvp.net\n"
        data = startup + b"x" * 10_000_000 + recent
        self.assertNotIn(b"CI server version", data[-8_000_000:])
        self.assertEqual(self.read(data), ("na", "na-1", "na", "release-test-shipping-1"))

    def test_short_log_and_region_fallback(self):
        self.assertEqual(self.read(b"CI server version: current\nhttps://glz-eu-1.eu.a.pvp.net\n"),
                         ("eu", "eu-1", "eu", "current"))

    def test_rotated_log_does_not_reuse_previous_version(self):
        self.read(b"CI server version: old\nhttps://glz-na-1.na.a.pvp.net\n")
        with self.assertRaises(NotReady):
            self.read(b"https://glz-na-1.na.a.pvp.net\n")

    def test_pbe_mapping_is_preserved(self):
        self.assertEqual(self.read(b"CI server version: pbe\nhttps://pd.pbe.a.pvp.net\nhttps://glz-pbe-1.pbe.a.pvp.net\n"),
                         ("na", "na-1", "na", "pbe"))

    def test_latest_version_and_region_win_in_short_log(self):
        self.assertEqual(self.read(b"CI server version: old\nhttps://glz-eu-1.eu.a.pvp.net\nCI server version: new\nhttps://glz-na-1.na.a.pvp.net\n"),
                         ("na", "na-1", "na", "new"))


if __name__ == "__main__":
    unittest.main()
