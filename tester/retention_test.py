import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from core import log_archive, update_watchdog


class RetentionTest(unittest.TestCase):
    def test_only_expired_daily_logs_are_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = log_archive.archive_dir(tmp)
            folder.mkdir()
            for name in ('2026-11-17.zip', '2026-11-18.zip', 'fel_atgardade.log', 'other.zip'):
                (folder / name).touch()
            log_archive.archive_day_logs(tmp, date(2026, 11, 24))
            self.assertEqual({p.name for p in folder.iterdir()},
                             {'2026-11-18.zip', 'fel_atgardade.log', 'other.zip'})

    def test_watchdog_deletes_only_confirmed_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp).resolve()
            backup = app / 'data' / 'backups' / 'app-update' / 'attempt'
            update_watchdog.write_manifest(backup, {})
            update_watchdog.write_pending(app, {'backup': str(backup)})
            unrelated = backup.parent / 'keep'
            unrelated.mkdir()

            def start(*args):
                update_watchdog.confirm_healthy(app)
                return object()

            with patch.object(update_watchdog, 'start_app', side_effect=start):
                self.assertEqual(update_watchdog.supervise(app, backup, 'python', app / 'main.pyw', delay_sec=0), 'healthy')
            self.assertFalse(backup.exists())
            self.assertTrue(unrelated.is_dir())
