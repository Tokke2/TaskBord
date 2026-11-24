"""Kör med python -m unittest tester.logging_test."""
import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import logger_setup as logs


class LoggingTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)
        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level
        active = logs._ACTIVE_LOG_PATH
        root.handlers = []

        def restore():
            for handler in root.handlers:
                handler.close()
            root.handlers = handlers
            root.setLevel(level)
            logs._ACTIVE_LOG_PATH = active

        self.addCleanup(restore)

    def setup_logging(self):
        logs.setup_full_logging(
            self.data, capture_stdout=False, capture_exceptions=False,
            capture_threads=False,
        )

    def test_archives_old_files_and_searches_only_today(self):
        active = self.data / logs.SINGLE_LOG_NAME
        active.write_text("yesterday-only\n", encoding="utf-8")
        old = time.time() - 2 * 86400
        os.utime(active, (old, old))
        from core import log_archive
        self.assertTrue(log_archive.prepare_active(self.data))
        self.assertEqual(log_archive.archive_dated_logs(self.data), 1)
        self.setup_logging()
        logging.info("today-only")
        self.assertEqual(len(list((self.data / "arkiv").glob("*.zip"))), 1)
        self.assertFalse(logs.search_logs("yesterday-only", self.data))
        self.assertTrue(logs.search_logs("today-only", self.data))
        handler = next(h for h in logging.getLogger().handlers
                       if isinstance(h, logs.WinSafeTimedRotatingFileHandler))
        handler.rolloverAt = 0
        logging.info("after rollover")
        self.assertFalse(logs.search_logs("today-only", self.data))
        self.assertTrue(logs.search_logs("after rollover", self.data))

    def test_errors_persist_and_only_matching_success_clears(self):
        self.setup_logging()
        unresolved = self.data / "felsokning.json"
        for attempt in range(2):
            with logs.safe_run("retry"):
                raise ValueError(f"failed {attempt}")
        logging.error("other error")
        self.setup_logging()
        result = json.loads(unresolved.read_text(encoding="utf-8"))
        self.assertEqual(result["safe_run:retry"]["count"], 2)
        self.assertIn("ValueError: failed 1", result["safe_run:retry"]["details"])
        with logs.safe_run("retry"):
            pass
        result = json.loads(unresolved.read_text(encoding="utf-8"))
        self.assertNotIn("safe_run:retry", result)
        self.assertEqual(len(result), 1)
        self.assertTrue(logs.search_logs("failed 1", self.data))

    def test_successful_inbox_retry_clears_its_failure(self):
        from core import error_log
        from core.mail_bridge import InboxWatcher
        from core.store import TaskStore

        self.setup_logging()
        error_log.install(self.data)
        watcher = InboxWatcher(TaskStore(data_dir_override=str(self.data)), self.data)
        path = self.data / "inbox" / "retry.json"
        path.write_text("not json", encoding="utf-8")
        self.assertFalse(watcher._process(path))
        issues = self.data / "felsokning.json"
        self.assertIn("inbox-import:retry.json", json.loads(issues.read_text(encoding="utf-8")))
        path.write_text('{"title": "Fixed"}', encoding="utf-8")
        with patch.object(watcher, "_service_create", return_value={"ok": True}):
            self.assertTrue(watcher._process(path))
        self.assertEqual(json.loads(issues.read_text(encoding="utf-8")), {})
        self.assertNotIn("inte giltig JSON", (self.data / "fel.log").read_text(encoding="utf-8"))
        archived = self.data / "arkiv" / error_log.RESOLVED_NAME
        self.assertIn("inte giltig JSON", archived.read_text(encoding="utf-8"))
