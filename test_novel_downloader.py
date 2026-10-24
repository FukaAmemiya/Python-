"""离线回归测试，不访问小说网站。运行：python -m unittest -v test_novel_downloader"""

import sqlite3
from contextlib import closing
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup

import novel_core as core
from novel_storage import DownloadStore

ROOT = Path(__file__).resolve().parent
U1 = "https://book.sfacg.com/Novel/1/1/1"
U2 = "https://book.sfacg.com/Novel/1/1/2"
U3 = "https://book.sfacg.com/Novel/1/1/3"


def page(title="第一章 起点", text="第一段正文", next_url=None, body=True):
    html = f"<title>测试作品 - 网站</title><h1>{title}</h1>"
    if body:
        html += f'<div id="ChapterBody"><p>{text}</p></div>'
    if next_url:
        html += f'<a href="{next_url}">下一章</a>'
    return BeautifulSoup(html, "html.parser")


class OfflineDownloader(core.NovelDownloader):
    def __init__(self, pages, **kwargs):
        super().__init__(on_log=lambda _: None, **kwargs)
        self.pages = pages
        self.fetched = []

    def _get_soup(self, url):
        self._check_stop()
        if url in self._cache:
            return self._cache.pop(url)
        self.fetched.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="novel-test-", dir=ROOT)
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.delay = patch.object(core, "REQUEST_DELAY", 0)
        self.delay.start()
        self.addCleanup(self.delay.stop)

    def downloader(self, pages, **kwargs):
        downloader = OfflineDownloader(pages, **kwargs)
        self.addCleanup(downloader.close)
        return downloader

    def database(self, url=U1):
        return self.directory / ".novel_state" / f"{core.task_key(url)}.sqlite3"

    def test_domain_validation_and_normalization(self):
        for url in (
            "https://example.org/?site=sfacg.com",
            "https://sfacg.com.example.org/Novel/1/1/1",
            "https://sfacg.com@example.org/Novel/1/1/1",
            "ftp://book.sfacg.com/Novel/1/1/1",
            "https://book.sfacg.com:9999/Novel/1/1/1",
        ):
            with self.subTest(url=url), self.assertRaises(core.DownloadError):
                core.normalize_url(url)
        self.assertEqual(core.normalize_url(U1 + "/?source=link#top"), U1)

    def test_missing_first_body_is_failure_without_txt(self):
        result = self.downloader({U1: page(body=False)}).run(U1, self.directory)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.saved_count, 0)
        self.assertEqual(list(self.directory.glob("*.txt")), [])

    def test_bad_second_chapter_keeps_first_and_resume_position(self):
        dl = self.downloader({U1: page(next_url=U2), U2: page(body=False)})
        result = dl.run(U1, self.directory)
        self.assertEqual((result.status, result.saved_count), ("failed", 1))
        self.assertIn("第一段正文", result.output_path.read_text(encoding="utf-8"))
        with closing(sqlite3.connect(self.database())) as connection:
            self.assertEqual(connection.execute("SELECT current_url FROM task").fetchone()[0], U2)
        recovery = self.downloader({U2: page("第二章 继续", "恢复正文")}).run(U1, self.directory)
        self.assertEqual((recovery.status, recovery.saved_count), ("end_reached", 2))

    def test_stop_and_resume_without_duplicates_and_prepare_refetch(self):
        event = threading.Event()
        dl = self.downloader(
            {U1: page(next_url=U2), U2: page("第二章 后续", "第二段正文")},
            stop_event=event,
            on_progress=lambda progress: event.set() if progress.saved_count == 1 else None,
        )
        stopped = dl.run(U1, self.directory)
        self.assertEqual((stopped.status, stopped.saved_count), ("stopped", 1))
        self.assertEqual(dl.fetched, [U1])
        recovery = self.downloader({U2: page("第二章 后续", "第二段正文")})
        result = recovery.run(U1, self.directory)
        self.assertEqual(recovery.fetched, [U2])
        self.assertEqual(result.saved_count, 2)
        self.assertEqual(result.output_path.read_text(encoding="utf-8").count("第一段正文"), 1)

    def test_transaction_rolls_back_chapter_if_progress_update_fails(self):
        store = DownloadStore(self.directory / "transaction.sqlite3")
        self.addCleanup(store.close)
        store.initialize(U1, "测试书", "测试站", U1, "测试.txt")
        store.connection.execute("""
            CREATE TRIGGER fail_progress BEFORE UPDATE ON task
            BEGIN SELECT RAISE(ABORT, 'simulated checkpoint failure'); END
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            store.save_chapter(U1, "第一章", "正文", U2)
        self.assertEqual(store.count(), 0)
        self.assertEqual(store.task()["current_url"], U1)
        store.connection.execute("DROP TRIGGER fail_progress")
        store.save_chapter(U1, "第一章", "正文", U2)
        self.assertEqual(store.count(), 1)
        self.assertEqual(store.task()["current_url"], U2)

    def test_crash_after_commit_can_recover_export_without_refetch(self):
        with patch.object(DownloadStore, "export", side_effect=OSError("disk unavailable")):
            result = self.downloader({U1: page()}).run(U1, self.directory)
        self.assertEqual((result.status, result.saved_count), ("failed", 1))
        recovery = self.downloader({})
        result = recovery.run(U1, self.directory)
        self.assertEqual(result.status, "end_reached")
        self.assertTrue(result.output_path.is_file())
        self.assertEqual(recovery.fetched, [])

    def test_deleted_export_is_rebuilt_from_database(self):
        first = self.downloader({U1: page()}).run(U1, self.directory)
        first.output_path.unlink()
        second = self.downloader({}).run(U1, self.directory)
        self.assertEqual(second.saved_count, 1)
        self.assertIn("第一段正文", second.output_path.read_text(encoding="utf-8"))

    def test_corrupt_database_does_not_touch_existing_files(self):
        self.database().parent.mkdir()
        self.database().write_bytes(b"NOT A SQLITE DATABASE")
        old = self.directory / "原有小说.txt"
        old.write_text("原文必须保留", encoding="utf-8")
        result = self.downloader({}).run(U1, self.directory)
        self.assertEqual(result.status, "failed")
        self.assertEqual(old.read_text(encoding="utf-8"), "原文必须保留")
        self.assertEqual(self.database().read_bytes(), b"NOT A SQLITE DATABASE")

    def test_old_txt_and_corrupt_legacy_progress_are_preserved(self):
        old = self.directory / "SF轻小说_测试作品.txt"
        progress = old.with_suffix(".progress")
        old.write_text("旧小说", encoding="utf-8")
        progress.write_text("损坏的旧进度", encoding="utf-8")
        result = self.downloader({U1: page()}).run(U1, self.directory)
        self.assertNotEqual(result.output_path, old)
        self.assertEqual(old.read_text(encoding="utf-8"), "旧小说")
        self.assertEqual(progress.read_text(encoding="utf-8"), "损坏的旧进度")

    def test_loop_is_reported_and_never_appended(self):
        result = self.downloader({U1: page(next_url=U2), U2: page(next_url=U1)}).run(U1, self.directory)
        self.assertEqual((result.status, result.saved_count), ("failed", 1))
        self.assertIn("回到已下载章节", result.message)

    def test_cross_book_or_external_link_is_rejected(self):
        for target in ("https://example.org/Novel/1/1/2", "https://book.sfacg.com/Novel/2/1/2"):
            with self.subTest(target=target):
                dl = self.downloader({U1: page(next_url=target)})
                result = dl.run(U1, self.directory)
                self.assertEqual(result.status, "failed")
                self.assertEqual(dl.fetched, [U1])

    def test_same_title_different_start_urls_do_not_collide(self):
        first = self.downloader({U1: page()}).run(U1, self.directory)
        second = self.downloader({U2: page()}).run(U2, self.directory)
        self.assertNotEqual(first.output_path, second.output_path)
        self.assertTrue(first.output_path.exists())

    def test_existing_export_name_is_not_overwritten_for_new_task(self):
        name = "SF轻小说_测试作品_" + core.task_key(U1)[:10] + ".txt"
        old = self.directory / name
        old.write_text("已有文件", encoding="utf-8")
        result = self.downloader({U1: page()}).run(U1, self.directory)
        self.assertNotEqual(old, result.output_path)
        self.assertEqual(old.read_text(encoding="utf-8"), "已有文件")

    def test_huaben_directory_uses_document_order(self):
        url = "https://www.ihuaben.com/book/1.html"
        soup = BeautifulSoup("""
            <h1 class="text-danger">测试书</h1>
            <span class="chapterTitle"><a href="/book/1/900.html">第一章</a></span>
            <span class="chapterTitle"><a href="/book/1/100.html">第二章</a></span>
        """, "html.parser")
        adapter = core.HuabenAdapter(self.downloader({url: soup}))
        self.assertEqual(adapter.prepare(url)[1], "https://www.ihuaben.com/book/1/900.html")

    def test_relative_navigation_uses_current_page(self):
        soup = page(next_url="../2/")
        soup._source_url = U1 + "/"
        adapter = core.SfacgAdapter(self.downloader({}))
        self.assertEqual(adapter.find_next(soup, U1), U2)

    def test_title_starting_with_year_is_preserved(self):
        adapter = core.SfacgAdapter(self.downloader({}))
        title, _ = adapter.parse_chapter(page("1984年的夏天"), U1)
        self.assertEqual(title, "1984年的夏天")

    def test_stopped_before_start_creates_no_records(self):
        event = threading.Event()
        event.set()
        result = self.downloader({}, stop_event=event).run(U1, self.directory)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(list(self.directory.iterdir()), [])


class NetworkTests(unittest.TestCase):
    @staticmethod
    def response(code, text="", headers=None):
        response = requests.Response()
        response.status_code = code
        response._content = text.encode("utf-8")
        response._content_consumed = True
        response.encoding = "utf-8"
        response.url = U1
        response.headers.update(headers or {})
        return response

    def make_downloader(self, responses):
        session = Mock()
        session.headers = {}
        session.get.side_effect = responses
        downloader = core.NovelDownloader(session=session, on_log=lambda _: None)
        self.addCleanup(downloader.close)
        return downloader, session

    def test_404_is_not_retried(self):
        dl, session = self.make_downloader([self.response(404)])
        with self.assertRaises(core.DownloadError):
            dl._get_soup(U1)
        self.assertEqual(session.get.call_count, 1)

    def test_transient_error_is_retried(self):
        dl, session = self.make_downloader([self.response(503), self.response(200, "<h1>正文</h1>")])
        with patch.object(dl, "_wait") as wait:
            soup = dl._get_soup(U1)
        self.assertEqual(soup.h1.get_text(), "正文")
        self.assertEqual(session.get.call_count, 2)
        wait.assert_called_once_with(core.RETRY_WAIT)

    def test_redirect_target_is_checked_before_request(self):
        dl, session = self.make_downloader([
            self.response(302, headers={"Location": "https://example.org/Novel/1/1/1"})
        ])
        with self.assertRaises(core.DownloadError):
            dl._get_soup(U1)
        self.assertEqual(session.get.call_count, 1)

    def test_trailing_slash_redirect_keeps_server_url(self):
        dl, session = self.make_downloader([
            self.response(301, headers={"Location": U1 + "/"}),
            self.response(200, "<h1>正文</h1>"),
        ])
        dl._get_soup(U1)
        self.assertEqual(session.get.call_args_list[1].args[0], U1 + "/")

    def test_stop_event_interrupts_retry_wait(self):
        dl, _ = self.make_downloader([])
        dl.stop_event.set()
        with self.assertRaises(core.DownloadStopped):
            dl._wait(120)


if __name__ == "__main__":
    unittest.main()
