"""双站小说下载核心。Python 3.10+；界面入口见 novel_gui.py。"""

import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from novel_storage import DownloadStore, StorageError

HUABEN_BASE = "https://www.ihuaben.com"
SFACG_BASE = "https://book.sfacg.com"
REQUEST_TIMEOUT = (10, 15)  # 连接超时、读取超时
MAX_RETRIES = 3  # 总尝试次数
RETRY_WAIT = 3
REQUEST_DELAY = 0.8
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "downloads"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
_ROLE_URL_RE = re.compile(r"/juese/")


class DownloadError(Exception):
    """向用户展示的网络、链接或页面解析错误。"""


class DownloadStopped(Exception):
    pass


@dataclass(frozen=True)
class DownloadProgress:
    book_name: str
    chapter_title: str
    saved_count: int
    total_count: int | None = None


@dataclass(frozen=True)
class DownloadResult:
    status: str  # end_reached / stopped / failed
    book_name: str
    saved_count: int
    output_path: Path | None
    message: str
    exports: tuple[Path, ...] = ()


def normalize_url(url):
    """只支持按路径定位章节的两个站点，移除查询参数和片段以防重复。"""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if (
        parts.scheme not in ("http", "https")
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 80, 443)
    ):
        raise DownloadError("请输入完整的 http/https 小说网址。")
    if host in ("ihuaben.com", "www.ihuaben.com"):
        host = "www.ihuaben.com"
    elif host in ("sfacg.com", "www.sfacg.com", "book.sfacg.com"):
        host = "book.sfacg.com"
    else:
        raise DownloadError("目前只支持话本小说和 SF 轻小说的官方网址。")
    path = parts.path or "/"
    # 两站章节地址中的路径 ID 才是身份；统一协议、主机和尾斜杠。
    return urlunsplit(("https", host, path.rstrip("/") or "/", "", ""))


def task_key(url):
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:20]


def safe_filename(name):
    return re.sub(r'[\x00-\x1f\\/*?:"<>|]', "", name).strip(" .")[:70] or "小说"


class SiteAdapter:
    source_name = ""
    name_prefix = ""
    CHAPTER_RE = re.compile(r"(?!)")
    NEXT_TEXTS = ("下一章",)

    def __init__(self, downloader):
        self.dl = downloader

    def prepare(self, url):
        raise NotImplementedError

    def parse_chapter(self, soup, url):
        raise NotImplementedError

    def book_id(self, url):
        raise NotImplementedError

    def is_catalog(self, url):
        raise NotImplementedError

    def catalog(self, url, required=False):
        """返回 (书名, 按网页顺序排列的章节链接)，不可用时返回 None。"""
        return None

    def validate_related(self, current_url, target):
        if urlsplit(current_url).hostname != urlsplit(target).hostname:
            raise DownloadError("章节链接跳转到了其他网站，已停止。")
        current_id, target_id = self.book_id(current_url), self.book_id(target)
        if current_id and target_id and current_id != target_id:
            raise DownloadError("章节链接指向另一本书，已停止。")

    def find_next(self, soup, current_url):
        page_url = getattr(soup, "_source_url", None) or current_url
        for anchor in soup.find_all("a"):
            label = re.sub(r"\s+", "", anchor.get_text(" ", strip=True))
            hint = re.sub(r"\s+", "", anchor.get("title", "") or anchor.get("aria-label", ""))
            if not any(label.startswith(t) or hint.startswith(t) for t in self.NEXT_TEXTS):
                continue
            href = (anchor.get("href") or "").strip()
            # 某些站点末章保留禁用的按钮。
            disabled = (
                anchor.get("aria-disabled") == "true"
                or "disabled" in anchor.get("class", [])
            )
            if disabled and href in ("", "#", "javascript:void(0)", "javascript:void(0);"):
                continue
            if not href or href.startswith(("#", "javascript:")):
                raise DownloadError("下一章按钮地址无效，无法确认后续章节。")
            nxt = normalize_url(urljoin(page_url, href))
            self.validate_related(current_url, nxt)
            if self.CHAPTER_RE.search(urlsplit(nxt).path):
                return nxt
            if self.is_catalog(nxt):
                continue
            raise DownloadError("下一章链接不是可识别的章节页，已保留进度。")
        return None

    @staticmethod
    def clean_title(raw):
        return raw.replace("《", "").replace("》", "").strip()

    @staticmethod
    def require_content(title, content):
        if not title or not content.strip():
            raise DownloadError("章节标题或正文为空，未保存本章；请用浏览器确认页面。")
        return title, content.strip()


class HuabenAdapter(SiteAdapter):
    source_name = "话本小说"
    name_prefix = "话本_"
    CHAPTER_RE = re.compile(r"/\d+/\d+\.html$|^/\d+\.html$")
    NEXT_TEXTS = ("下一章", "下一篇")

    def book_id(self, url):
        path = urlsplit(url).path
        match = re.search(r"^/(?:book|list)/(\d+)(?:/|\.html|$)", path)
        return match.group(1) if match else None

    def is_catalog(self, url):
        path = urlsplit(url).path
        return (re.fullmatch(r"/book/\d+(?:\.html)?", path) is not None
                or re.fullmatch(r"/list/\d+\.html", path) is not None)

    def catalog(self, url, required=False):
        book_id = self.book_id(url)
        if not book_id:
            return None
        urls = (
            f"{HUABEN_BASE}/list/{book_id}.html",
            f"{HUABEN_BASE}/book/{book_id}.html",
        )
        for index_url in urls:
            try:
                soup = self.dl._get_soup(index_url)
            except (DownloadError, KeyError):
                continue
            chapters = self._catalog_links(soup, index_url, book_id)
            if not chapters:
                continue
            heading = soup.find("h1")
            name = self.clean_title(heading.get_text(" ", strip=True)) if heading else ""
            if not name:
                title = soup.find("title")
                name = self.clean_title(title.get_text().split("章节目录")[0]) if title else "话本小说作品"
            if index_url != urls[0]:
                self.dl.log("完整目录不可用，改从书籍主页读取章节链接。")
            return name, chapters
        if required:
            raise DownloadError("话本目录和书籍主页都没有可识别章节，请检查链接或网站结构。")
        self.dl.log("话本目录暂不可用，将尝试下一章导航。")
        return None

    def _catalog_links(self, soup, index_url, book_id):
        links, seen = [], set()
        for anchor in soup.select("a[href]"):
            try:
                target = normalize_url(urljoin(index_url, anchor["href"]))
            except (DownloadError, ValueError):
                continue
            if (self.book_id(target) != book_id
                    or not self.CHAPTER_RE.search(urlsplit(target).path)
                    or target in seen):
                continue
            seen.add(target)
            links.append(target)
        return links

    def prepare(self, url):
        soup = self.dl._get_soup(url)
        if soup.find("div", id="contentsource"):
            title = soup.find("title")
            raw = title.get_text(" ", strip=True) if title else ""
            match = re.search(r"-《(.+?)》第\d+章", raw)
            name = match.group(1) if match else self.clean_title(raw.split("-")[0])
            self.dl._cache[url] = soup
            self.dl.log("检测到章节页，从当前章节开始。")
            return name or "话本小说作品", url
        raise DownloadError("未识别到话本正文，请使用书籍主页、目录或章节页网址。")

    @staticmethod
    def _parse_paragraph(paragraph):
        roles = paragraph.find_all("a", href=_ROLE_URL_RE)
        text = paragraph.get_text()
        names = [role.get_text(strip=True) for role in roles]
        for name in names:
            text = text.replace(name, "", 1)
        prefix = "".join(name + "：" for name in names if name)
        return prefix + text.strip()

    def parse_chapter(self, soup, url):
        title_element = soup.find("h1")
        body = soup.find("div", id="contentsource")
        if title_element is None or body is None:
            raise DownloadError("未找到话本章节标题或正文；本章未写入，进度已保留。")
        lines = [self._parse_paragraph(p) for p in body.find_all("p")]
        content = "\n\n".join(line for line in lines if line.strip())
        return self.require_content(self.clean_title(title_element.get_text()), content)


class SfacgAdapter(SiteAdapter):
    source_name = "SF轻小说（菠萝包）"
    name_prefix = "SF轻小说_"
    CHAPTER_RE = re.compile(r"^/Novel/\d+/\d+/\d+(?:\.html)?$", re.I)

    def book_id(self, url):
        match = re.search(r"/Novel/(\d+)(?:/|$)", urlsplit(url).path, re.I)
        return match.group(1) if match else None

    def is_catalog(self, url):
        return re.fullmatch(r"/Novel/\d+(?:/MainIndex)?/?", urlsplit(url).path, re.I) is not None

    def catalog(self, url, required=False):
        book_id = self.book_id(url)
        if not book_id:
            return None
        index_url = f"{SFACG_BASE}/Novel/{book_id}/MainIndex/"
        try:
            soup = self.dl._get_soup(index_url)
        except (DownloadError, KeyError) as error:
            if required:
                raise DownloadError(f"SF 目录不可访问：{error}") from error
            self.dl.log("SF 目录不可用，退回阅读页下一章导航。")
            return None
        links, seen = [], set()
        for anchor in soup.select("a[href]"):
            try:
                target = normalize_url(urljoin(index_url, anchor["href"]))
            except (DownloadError, ValueError):
                continue
            if (self.book_id(target) == book_id
                    and self.CHAPTER_RE.search(urlsplit(target).path)
                    and target not in seen):
                seen.add(target)
                links.append(target)
        if not links:
            if required:
                raise DownloadError("SF 目录没有识别到章节，请粘贴具体阅读页。")
            return None
        title = soup.find("title")
        name = title.get_text(" ", strip=True).split("-")[0] if title else "SF轻小说作品"
        return name, links

    def prepare(self, url):
        if not self.CHAPTER_RE.search(urlsplit(url).path):
            raise DownloadError("SF 轻小说请粘贴章节页，或提供书籍主页/目录页。")
        soup = self.dl._get_soup(url)
        self.parse_chapter(soup, url)
        self.dl._cache[url] = soup
        title = soup.find("title")
        book_name = title.get_text().split("-")[0].strip() if title else "未命名轻小说"
        return book_name, url

    def parse_chapter(self, soup, url):
        title_element = soup.find(class_="article-title") or soup.find("h1")
        body = soup.find(id="ChapterBody")
        if title_element is None or body is None:
            raise DownloadError("未找到 SF 章节标题或正文；请检查是否需要登录或页面结构已变化。")
        raw_title = title_element.get_text(strip=True)
        # 只移除“1. 标题”这类明确序号，保留“1984年的夏天”等正文标题。
        raw_title = re.sub(r"^\d+[.、]\s*(?=\S)", "", raw_title)
        paragraphs = [p.get_text(" ", strip=True) for p in body.find_all("p")]
        content = "\n\n".join(p for p in paragraphs if p) if paragraphs else body.get_text("\n", strip=True)
        return self.require_content(raw_title, content)


SITE_TABLE = (
    ("www.ihuaben.com", HuabenAdapter),
    ("book.sfacg.com", SfacgAdapter),
)


class NovelDownloader:
    def __init__(self, on_log=None, on_progress=None, stop_event=None, session=None):
        self.log = on_log or print
        self.on_progress = on_progress or (lambda progress: None)
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.session = session if session is not None else requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._cache = {}

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _check_stop(self):
        if self.stop_event.is_set():
            raise DownloadStopped

    def _wait(self, seconds):
        if self.stop_event.wait(seconds):
            raise DownloadStopped

    def _get_soup(self, url):
        self._check_stop()
        if url in self._cache:
            return self._cache.pop(url)
        for attempt in range(MAX_RETRIES):
            self._check_stop()
            retry_after = 0
            try:
                target = url
                for _ in range(6):
                    self._check_stop()
                    # 在访问重定向目标之前检查域名。
                    with self.session.get(
                        target, timeout=REQUEST_TIMEOUT, allow_redirects=False
                    ) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location:
                                raise DownloadError("网站重定向缺少目标地址。")
                            redirected = normalize_url(urljoin(target, location))
                            # 保留站点返回的尾斜杠，避免规范化后被反复重定向。
                            requested = urlsplit(urljoin(target, location))
                            redirected = urlunsplit((
                                "https", urlsplit(redirected).netloc,
                                requested.path or "/", "", "",
                            ))
                            adapter_cls = dict(SITE_TABLE)[urlsplit(url).hostname]
                            adapter_cls(self).validate_related(url, redirected)
                            target = redirected
                            continue
                        if response.status_code == 429:
                            value = response.headers.get("Retry-After", "")
                            retry_after = min(int(value), 120) if value.isdigit() else 0
                        response.raise_for_status()
                        if not response.encoding or response.encoding.lower() == "iso-8859-1":
                            response.encoding = response.apparent_encoding or "utf-8"
                        soup = BeautifulSoup(response.text, "html.parser")
                        soup._source_url = target
                        return soup
                raise DownloadError("网站重定向次数过多，请检查阅读页网址。")
            except requests.RequestException as error:
                status = error.response.status_code if error.response is not None else None
                retryable = status is None or status in (408, 429, 500, 502, 503, 504)
                if not retryable or attempt == MAX_RETRIES - 1:
                    raise DownloadError(f"页面请求失败：{error}") from error
                delay = max(RETRY_WAIT * (2 ** attempt), retry_after)
                self.log(f"请求失败，{delay} 秒后重试（{attempt + 2}/{MAX_RETRIES}）。")
                self._wait(delay)
        raise DownloadError("页面请求失败。")

    @staticmethod
    def _clean_content(text):
        return re.sub(r"\n\s*\n", "\n\n", text).strip()

    @staticmethod
    def _format_title(raw, count):
        return raw if re.search(r"第.{1,20}章", raw) else f"第{count}章 {raw}"

    def run(self, url, output_dir=DEFAULT_OUTPUT_DIR, output_format="txt"):
        if output_format not in ("txt", "epub", "both"):
            raise ValueError("输出格式必须是 txt、epub 或 both。")
        store = None
        ready = False
        output_path = None
        exports = []
        book_name = ""
        saved_count = 0
        total_count = None
        status, message = "failed", "下载未开始。"
        self._cache.clear()
        try:
            self._check_stop()
            url = normalize_url(url)
            adapter = dict(SITE_TABLE)[urlsplit(url).hostname](self)
            output_dir = Path(output_dir).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            state_dir = output_dir / ".novel_state"
            state_dir.mkdir(exist_ok=True)
            key = task_key(url)
            database = state_dir / f"{key}.sqlite3"
            existing_task = database.exists()

            # 优先使用完整目录：比阅读页上的“下一章”导航更稳定。
            # 对具体章节页，如果目录不可用仍可沿导航继续。
            catalog = adapter.catalog(url, required=adapter.is_catalog(url) and not existing_task)
            chapters = catalog[1] if catalog else []
            chapter_positions = {item: index for index, item in enumerate(chapters)}
            # 章节网址作为起点时，进度只计算该章节及之后的内容。
            chapter_start = chapter_positions.get(url, 0)
            eligible_chapters = chapters[chapter_start:]
            total_count = len(eligible_chapters) if chapters else None
            if chapters:
                self.log(f"已识别完整目录：共 {len(chapters)} 章；本任务范围 {total_count} 章。")

            if existing_task:
                store = DownloadStore(database)
                task = store.task()
                if task["start_url"] != url:
                    raise StorageError("记录中的起始网址不匹配，已停止。")
                book_name = task["book_name"]
                current_url = task["current_url"]
                saved_count = store.count()
                ready = True
                self.log(f"恢复任务：{book_name}，已保存 {saved_count} 章。")

            else:
                if adapter.is_catalog(url):
                    if not chapters:
                        raise DownloadError("书籍目录没有找到可下载章节。")
                    book_name, first_url = catalog[0], chapters[0]
                elif catalog and url in chapters:
                    book_name, first_url = catalog[0], url
                else:
                    book_name, first_url = adapter.prepare(url)
                stem = safe_filename(adapter.name_prefix + book_name) + "_" + key[:10]
                output_name = stem + ".txt"
                index = 2
                while (output_dir / output_name).exists():
                    output_name = f"{stem}_{index}.txt"
                    index += 1
                store = DownloadStore(database)
                store.initialize(url, book_name, adapter.source_name, first_url, output_name)
                current_url = first_url
                ready = True

            saved_urls = store.saved_urls()
            if chapters:
                # 目录排序数据只新增辅助表，不重写旧章节和正文。
                store.set_catalog(chapters)
                outside_catalog = saved_urls.difference(chapter_positions)
                if outside_catalog:
                    self.log(
                        f"警告：已有 {len(outside_catalog)} 章不在当前目录中；"
                        "保留其正文，并在导出时排到已知目录章节之后。"
                    )
                first_missing = next(
                    (item for item in eligible_chapters if item not in saved_urls), None
                )
                if first_missing and (current_url is None or current_url in chapter_positions):
                    if first_missing != current_url:
                        store.resume_at(first_missing)
                        current_url = first_missing
                        self.log("发现未下载章节（包括可能插入在中间的章节），正在自动补齐。")

            self.on_progress(DownloadProgress(book_name, "准备下载", saved_count, total_count))
            while current_url:
                self._check_stop()
                normalized = normalize_url(current_url)
                adapter.validate_related(url, normalized)
                if normalized != current_url:
                    raise StorageError("续传记录中的章节地址格式不正确。")
                if store.contains(current_url):
                    raise DownloadError("发现循环章节链接，已停止并保留记录。")
                soup = self._get_soup(current_url)
                raw_title, content = adapter.parse_chapter(soup, current_url)
                content = self._clean_content(content)
                if not content:
                    raise DownloadError("章节正文为空，本章未保存。")

                position = chapter_positions.get(current_url)
                if position is not None:
                    next_url = next(
                        (candidate for candidate in chapters[position + 1:]
                         if candidate not in saved_urls), None
                    )
                else:
                    next_url = adapter.find_next(soup, current_url)
                if next_url == current_url or (next_url and store.contains(next_url)):
                    raise DownloadError("下一章链接回到已下载章节，已停止并保留记录。")
                title_number = position + 1 if position is not None else saved_count + 1
                title = self._format_title(raw_title, title_number)
                self._check_stop()
                store.save_chapter(current_url, title, content, next_url)
                saved_urls.add(current_url)
                saved_count = store.count()
                self.log(f"已保存：{title}")
                self.on_progress(DownloadProgress(book_name, title, saved_count, total_count))
                current_url = next_url
                if current_url:
                    self._wait(REQUEST_DELAY)
            status = "end_reached"
            if total_count is not None:
                message = f"下载任务结束，已保存 {saved_count} 章，本任务目录范围共 {total_count} 章。"
            elif existing_task and not catalog and not current_url:
                message = f"已导出本地 {saved_count} 章；目录不可访问，无法确认网站是否新增章节。"
            else:
                message = f"未发现下一章，已保存 {saved_count} 章。请对照网站目录确认是否完整。"
        except (DownloadStopped, KeyboardInterrupt):
            status, message = "stopped", "已停止；使用相同网址和保存目录可继续。"
        except (DownloadError, StorageError, requests.RequestException, OSError, sqlite3.Error, ValueError) as error:
            message = f"下载失败：{error}"
        finally:
            try:
                if store is not None and ready:
                    saved_count = store.count()
                    if saved_count:
                        if output_format in ("txt", "both"):
                            output_path = store.export(output_dir)
                            exports.append(output_path)
                        if output_format in ("epub", "both"):
                            from novel_epub import export_epub
                            target_name = Path(store.task()["output_name"]).with_suffix(".epub")
                            epub_path = export_epub(store, output_dir / target_name)
                            exports.append(epub_path)
                            if output_path is None:
                                output_path = epub_path
            except (OSError, sqlite3.Error, StorageError, ValueError) as error:
                status = "failed"
                message += f" 导出失败：{error}。章节仍在下载记录中，重试可重新导出。"
            finally:
                if store is not None:
                    store.close()
                self._cache.clear()
        self.log(message)
        for path in exports:
            self.log(f"已导出：{path}")
        return DownloadResult(status, book_name, saved_count, output_path, message, tuple(exports))

