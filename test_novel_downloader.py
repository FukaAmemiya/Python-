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
        # 旧的离线用例没有模拟网站目录，保持导航测试独立。
        catalog_patch = patch.object(core.SfacgAdapter, "catalog", return_value=None)
        catalog_patch.start()
        self.addCleanup(catalog_patch.stop)

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


    def test_huaben_catalog_preserves_page_order(self):
        index = "https://www.ihuaben.com/list/1.html"
        soup = BeautifulSoup("""
            <h1>测试书</h1>
            <a href="/book/1/900.html">第一章</a>
            <a href="/book/1/100.html">第二章</a>
            <a href="/book/2/99.html">另一部书</a>
        """, "html.parser")
        adapter = core.HuabenAdapter(self.downloader({index: soup}))
        name, chapters = adapter.catalog("https://www.ihuaben.com/book/1.html")
        self.assertEqual(name, "测试书")
        self.assertEqual(chapters, [
            "https://www.ihuaben.com/book/1/900.html",
            "https://www.ihuaben.com/book/1/100.html",
        ])

    def test_huaben_next_with_chapter_title(self):
        adapter = core.HuabenAdapter(self.downloader({}))
        soup = BeautifulSoup("""
            <a href="/book/1/100.html">下一章 《第二章继续》</a>
        """, "html.parser")
        result = adapter.find_next(soup, "https://www.ihuaben.com/book/1/900.html")
        self.assertEqual(result, "https://www.ihuaben.com/book/1/100.html")

    def test_epub_export_contains_chapters(self):
        from zipfile import ZipFile
        from novel_epub import export_epub
        store = DownloadStore(self.directory / "epub.sqlite3")
        self.addCleanup(store.close)
        store.initialize(U1, "测试书", "SF", U1, "book.txt")
        store.save_chapter(U1, "第一章", "段落一\n\n段落二", None)
        output = export_epub(store, self.directory / "book.epub")
        with ZipFile(output) as archive:
            self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
            self.assertIn("第一章", archive.read("EPUB/chapter-00001.xhtml").decode())
            self.assertIn("nav.xhtml", archive.read("EPUB/package.opf").decode())


    def test_backfill_middle_chapter_preserves_txt_epub_order(self):
        from zipfile import ZipFile
        first = "https://www.ihuaben.com/book/1/100.html"
        middle = "https://www.ihuaben.com/book/1/200.html"
        last = "https://www.ihuaben.com/book/1/300.html"
        entry = "https://www.ihuaben.com/book/1.html"
        directory = "https://www.ihuaben.com/list/1.html"
        db = self.directory / ".novel_state" / f"{core.task_key(entry)}.sqlite3"
        db.parent.mkdir()
        store = DownloadStore(db)
        store.initialize(entry, "测试作品", "话本小说", first, "插章测试.txt")
        store.save_chapter(first, "第一章", "前段正文", last)
        store.save_chapter(last, "第三章", "后段正文", None)
        store.close()
        pages = {
            directory: BeautifulSoup(
                '<h1>测试作品</h1><a href="/book/1/100.html">一</a>'
                '<a href="/book/1/200.html">二</a>'
                '<a href="/book/1/300.html">三</a>', "html.parser"),
            middle: BeautifulSoup(
                '<h1>第二章</h1><div id="contentsource"><p>中段正文</p></div>',
                "html.parser"),
        }
        dl = self.downloader(pages)
        result = dl.run(entry, self.directory, output_format="both")
        self.assertEqual((result.status, result.saved_count), ("end_reached", 3))
        self.assertEqual(dl.fetched, [directory, middle])
        text = result.output_path.read_text(encoding="utf-8")
        self.assertLess(text.index("前段正文"), text.index("中段正文"))
        self.assertLess(text.index("中段正文"), text.index("后段正文"))
        with ZipFile(self.directory / "插章测试.epub") as book:
            self.assertIn("前段正文", book.read("EPUB/chapter-00001.xhtml").decode())
            self.assertIn("中段正文", book.read("EPUB/chapter-00002.xhtml").decode())
            self.assertIn("后段正文", book.read("EPUB/chapter-00003.xhtml").decode())
        repeated = self.downloader({directory: pages[directory]})
        repeat_result = repeated.run(entry, self.directory)
        self.assertEqual(repeat_result.saved_count, 3)
        self.assertEqual(repeated.fetched, [directory])

    def test_legacy_database_adds_catalog_without_losing_content(self):
        legacy = self.directory / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy)) as connection:
            connection.executescript("""
                CREATE TABLE task (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    start_url TEXT NOT NULL, book_name TEXT NOT NULL,
                    source TEXT NOT NULL, current_url TEXT,
                    output_name TEXT NOT NULL, status TEXT NOT NULL
                );
                CREATE TABLE chapters (
                    url TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE,
                    title TEXT NOT NULL, content TEXT NOT NULL
                );
                INSERT INTO task VALUES (1, 'url', '旧书', '话本', NULL, 'old.txt', 'end_reached');
                INSERT INTO chapters VALUES ('chapter1', 1, '第一章', '原文');
            """)
        store = DownloadStore(legacy)
        self.addCleanup(store.close)
        self.assertEqual(store.count(), 1)
        store.set_catalog(["chapter1"])
        self.assertEqual(store.iter_chapters().fetchone()["content"], "原文")

    def test_existing_book_can_export_while_catalog_offline(self):
        entry = "https://www.ihuaben.com/book/1.html"
        first = "https://www.ihuaben.com/book/1/100.html"
        database = self.directory / ".novel_state" / f"{core.task_key(entry)}.sqlite3"
        database.parent.mkdir()
        store = DownloadStore(database)
        store.initialize(entry, "旧书", "话本小说", first, "旧书.txt")
        store.save_chapter(first, "第一章", "原本保存的内容", None)
        store.close()
        dl = self.downloader({})
        result = dl.run(entry, self.directory)
        self.assertEqual(result.status, "end_reached")
        self.assertEqual(result.saved_count, 1)
        self.assertIn("无法确认网站是否新增章节", result.message)
        self.assertIn("原本保存的内容", result.output_path.read_text(encoding="utf-8"))

    def test_chapter_page_progress_uses_requested_range(self):
        entry = "https://www.ihuaben.com/book/1/300.html"
        index = "https://www.ihuaben.com/list/1.html"
        pages = {
            index: BeautifulSoup(
                '<a href="/book/1/100.html">一</a>'
                '<a href="/book/1/200.html">二</a>'
                '<a href="/book/1/300.html">三</a>', "html.parser"),
            entry: BeautifulSoup(
                '<title>作品</title><h1>第三章</h1>'
                '<div id="contentsource"><p>第三章正文</p></div>', "html.parser"),
        }
        progress = []
        downloader = self.downloader(pages, on_progress=progress.append)
        result = downloader.run(entry, self.directory)
        self.assertEqual((result.status, result.saved_count), ("end_reached", 1))
        self.assertEqual(progress[-1].total_count, 1)
        self.assertEqual(downloader.fetched, [index, entry])

    def test_epub_rejects_invalid_xml_characters(self):
        from xml.etree import ElementTree
        from zipfile import ZipFile
        from novel_epub import export_epub
        store = DownloadStore(self.directory / "xml.sqlite3")
        self.addCleanup(store.close)
        store.initialize(U1, "带控制符\x01的书", "SF", U1, "xml.txt")
        store.save_chapter(U1, "标题\x02", "可见内容\x03\n第二行", None)
        target = export_epub(store, self.directory / "xml.epub")
        with ZipFile(target) as archive:
            for name in ("EPUB/package.opf", "EPUB/nav.xhtml", "EPUB/chapter-00001.xhtml"):
                ElementTree.fromstring(archive.read(name))
            self.assertIn(b"style.css", archive.read("EPUB/package.opf"))
            self.assertIn(b"<br/>", archive.read("EPUB/chapter-00001.xhtml"))

    def test_sf_catalog_accepts_trailing_slash(self):
        adapter = core.SfacgAdapter(self.downloader({}))
        self.assertTrue(adapter.is_catalog("https://book.sfacg.com/Novel/123/MainIndex/"))
        self.assertTrue(adapter.is_catalog("https://book.sfacg.com/Novel/123/"))

    def test_catalog_download_and_repair_old_completed_task(self):
        first = "https://www.ihuaben.com/book/1/900.html"
        second = "https://www.ihuaben.com/book/1/100.html"
        directory = "https://www.ihuaben.com/list/1.html"
        entry = "https://www.ihuaben.com/book/1.html"
        pages = {
            directory: BeautifulSoup(
                '<h1>测试作品</h1><a href="/book/1/900.html">第一章</a>'
                '<a href="/book/1/100.html">第二章</a>', "html.parser"),
            first: BeautifulSoup(
                '<h1>第一章</h1><div id="contentsource"><p>第一段正文</p></div>',
                "html.parser"),
            second: BeautifulSoup(
                '<h1>第二章</h1><div id="contentsource"><p>第二段正文</p></div>',
                "html.parser"),
        }
        db = self.directory / ".novel_state" / f"{core.task_key(entry)}.sqlite3"
        db.parent.mkdir()
        store = DownloadStore(db)
        store.initialize(entry, "测试作品", "话本小说", first, "测试作品.txt")
        store.save_chapter(first, "第一章", "第一段正文", None)
        store.close()
        dl = self.downloader(pages)
        result = dl.run(entry, self.directory, output_format="both")
        self.assertEqual(result.status, "end_reached")
        self.assertEqual(result.saved_count, 2)
        self.assertEqual(len(result.exports), 2)
        self.assertEqual(dl.fetched, [directory, second])
        self.assertEqual(result.output_path.read_text(encoding="utf-8").count("第一段正文"), 1)
        self.assertTrue((self.directory / "测试作品.epub").is_file())

    def test_catalog_home_page_starts_at_first_chapter(self):
        entry = "https://www.ihuaben.com/book/1.html"
        directory = "https://www.ihuaben.com/list/1.html"
        first = "https://www.ihuaben.com/book/1/900.html"
        second = "https://www.ihuaben.com/book/1/100.html"
        pages = {
            directory: BeautifulSoup(
                '<h1>测试作品</h1><a href="/book/1/900.html">第一章</a>'
                '<a href="/book/1/100.html">第二章</a>', "html.parser"),
            first: BeautifulSoup(
                '<h1>第一章</h1><div id="contentsource"><p>正文1</p></div>',
                "html.parser"),
            second: BeautifulSoup(
                '<h1>第二章</h1><div id="contentsource"><p>正文2</p></div>',
                "html.parser"),
        }
        dl = self.downloader(pages)
        result = dl.run(entry, self.directory)
        self.assertEqual((result.status, result.saved_count), ("end_reached", 2))
        self.assertEqual(dl.fetched, [directory, first, second])

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
