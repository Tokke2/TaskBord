"""Kör med python -m unittest tester.update_safety_test."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import update_watchdog, updater


class UpdateSafetyTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = Path(temp.name).resolve()
        self.main = self.app / "main.pyw"
        self.main.write_bytes(b"old")
        self.info = updater.UpdateInfo(files={"main.pyw": b"new"}, changed=["main.pyw"])

    def test_no_watchdog_no_change(self):
        with patch.object(update_watchdog, "copy_self_to", return_value=False):
            with self.assertRaises(updater.UpdateError):
                updater.apply_update(self.app, self.info)
        self.assertEqual(self.main.read_bytes(), b"old")

    def test_manifest_failure_rolls_back(self):
        with patch.object(update_watchdog, "write_manifest", side_effect=OSError("disk full")):
            with self.assertRaises(updater.UpdateError):
                updater.apply_update(self.app, self.info)
        self.assertEqual(self.main.read_bytes(), b"old")

    def test_protected_destination_rejected_before_writing(self):
        self.info.changed.append("DATA/active.json")
        with self.assertRaises(updater.UpdateError):
            updater.apply_update(self.app, self.info)
        self.assertEqual(self.main.read_bytes(), b"old")
