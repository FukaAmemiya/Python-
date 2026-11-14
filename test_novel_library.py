"""Offline bookshelf tests: old checkpoints, filtering data and export discovery."""

import tempfile
import unittest
from pathlib import Path

from novel_library import scan_books
from novel_storage import DownloadStore


class BookshelfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.state = self.output / ".novel_state"
        self.state.mkdir()

    def create_book(self, name, file="book.sqlite3"):
        store = DownloadStore(self.state / file)
        self.addCleanup(store.close)
        store.initialize(
            "https://www.ihuaben.com/book/1.html", name, "话本小说",
            "https://www.ihuaben.com/book/1/1.html", "小说.txt",
        )
        store.save_chapter(
            "https://www.ihuaben.com/book/1/1.html", "第一章", "正文", None,
        )

    def test_scan_old_record_without_changing_content(self):
        self.create_book("测试书")
        records = scan_books(self.output)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "测试书")
        self.assertEqual(records[0].chapters, 1)
        self.assertEqual(records[0].status, "end_reached")
        self.assertEqual(records[0].url, "https://www.ihuaben.com/book/1.html")

    def test_detect_existing_txt_and_epub(self):
        self.create_book("测试书")
        (self.output / "小说.txt").write_text("文本", encoding="utf-8")
        (self.output / "小说.epub").write_bytes(b"epub")
        record = scan_books(self.output)[0]
        self.assertEqual(record.export_path(".txt"), self.output / "小说.txt")
        self.assertEqual(record.export_path(".epub"), self.output / "小说.epub")
        self.assertIsNone(record.export_path(".pdf"))

    def test_skip_corrupt_checkpoint_without_breaking_bookshelf(self):
        (self.state / "bad.sqlite3").write_bytes(b"not a sqlite file")
        self.create_book("有效书", "good.sqlite3")
        self.assertEqual([b.title for b in scan_books(self.output)], ["有效书"])

    def test_missing_directory_returns_empty_list(self):
        self.assertEqual(scan_books(self.output / "not-created"), [])


if __name__ == "__main__":
    unittest.main()
