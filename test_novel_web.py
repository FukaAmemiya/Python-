"""Offline tests for the local browser dashboard."""

import tempfile
import unittest
from pathlib import Path

from novel_core import DownloadError
from novel_web import DownloadDashboard, local_host_allowed, local_origin_allowed


class WebDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dashboard = DownloadDashboard(self.root)

    def test_library_contains_only_exported_books(self):
        (self.root / "novel.txt").write_text("章节", encoding="utf-8")
        (self.root / "novel.epub").write_bytes(b"epub")
        (self.root / "secret.sqlite3").write_text("state")
        (self.root / ".novel_state").mkdir()
        self.assertEqual(
            sorted(path.name for path in self.dashboard.files()),
            ["novel.epub", "novel.txt"],
        )

    def test_invalid_domains_and_formats_are_rejected(self):
        with self.assertRaises(DownloadError):
            self.dashboard.start("https://example.com/1.html", "both")
        with self.assertRaises(ValueError):
            self.dashboard.start("https://www.ihuaben.com/book/1.html", "pdf")

    def test_host_and_origin_are_restricted_to_loopback(self):
        self.assertTrue(local_host_allowed("127.0.0.1:18423", 18423))
        self.assertTrue(local_host_allowed("localhost:18423", 18423))
        self.assertFalse(local_host_allowed("evil.example:18423", 18423))
        self.assertFalse(local_host_allowed("127.0.0.1:9999", 18423))
        self.assertTrue(local_origin_allowed("http://localhost:18423", 18423))
        self.assertFalse(local_origin_allowed("https://evil.example", 18423))

    def test_symlinked_text_file_is_not_in_library(self):
        outside = self.root / "secret.dat"
        outside.write_text("not a public download", encoding="utf-8")
        link = self.root / "shortcut.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("系统不允许创建符号链接")
        self.assertNotIn(link, self.dashboard.files())

    def test_log_has_bounded_history(self):
        for index in range(350):
            self.dashboard.log(index)
        status, detail, logs = self.dashboard.snapshot()
        self.assertEqual((status, detail), ("准备就绪", "尚未开始下载"))
        self.assertEqual(len(logs), 80)
        self.assertEqual(logs[-1], "349")


if __name__ == "__main__":
    unittest.main()
