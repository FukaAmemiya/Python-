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


@dataclass(frozen=True)
class DownloadResult:
    status: str  # end_reached / stopped / failed
    book_name: str
    saved_count: int
    output_path: Path | None
    message: str


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

    def validate_related(self, current_url, target):
        if urlsplit(current_url).hostname != urlsplit(target).hostname:
            raise DownloadError("章节链接跳转到了其他网站，已停止。")
        current_id, target_id = self.book_id(current_url), self.book_id(target)
        if current_id and target_id and current_id != target_id:
            raise DownloadError("章节链接指向另一本书，已停止。")

    def find_next(self, soup, current_url):
        page_url = getattr(soup, "_source_url", None) or current_url
        for anchor in soup.find_all("a"):
            if re.sub(r"\s+", "", anchor.get_text()) not in self.NEXT_TEXTS:
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
        match = re.search(r"/book/(\d+)(?:/|\.html|$)", urlsplit(url).path)
        return match.group(1) if match else None

    def is_catalog(self, url):
        return re.fullmatch(r"/book/\d+(?:\.html)?", urlsplit(url).path) is not None

    def prepare(self, url):
        soup = self.dl._get_soup(url)
        if soup.find("div", id="contentsource"):
            title = soup.find("title")
            name = self.clean_title(title.get_text().split("-")[0]) if title else "话本小说作品"
            self.dl._cache[url] = soup
            self.dl.log("检测到章节页，从当前章节开始。")
            return name, url
        name_element = soup.find("h1", class_="text-danger")
        if name_element is None:
            raise DownloadError("未识别到话本书籍页或正文，请检查网址和访问状态。")
        for span in soup.select("span.chapterTitle"):
            link = span.find("a", href=True)
            if link:
                chapter_url = normalize_url(urljoin(
                    getattr(soup, "_source_url", None) or url, link["href"]
                ))
                self.validate_related(url, chapter_url)
                if self.CHAPTER_RE.search(urlsplit(chapter_url).path):
                    self.dl.log("从页面目录中的第一项开始下载。")
                    return self.clean_title(name_element.get_text()), chapter_url
        raise DownloadError("没有找到章节列表，请尝试粘贴第一章阅读页网址。")

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
        return re.fullmatch(r"/Novel/\d+(?:/MainIndex)?", urlsplit(url).path, re.I) is not None

    def prepare(self, url):
        if not self.CHAPTER_RE.search(urlsplit(url).path):
            raise DownloadError("SF 轻小说请粘贴具体章节的阅读页网址。")
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

    def run(self, url, output_dir=DEFAULT_OUTPUT_DIR):
        store = None
        ready = False
        output_path = None
        book_name = ""
        saved_count = 0
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
            if database.exists():
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
                self.log(f"正在识别 {adapter.source_name} 页面……")
                book_name, first_url = adapter.prepare(url)
                # prepare 请求过的章节页由缓存供主循环复用。
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
            self.on_progress(DownloadProgress(book_name, "准备下载", saved_count))
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
                next_url = adapter.find_next(soup, current_url)
                if next_url == current_url or (next_url and store.contains(next_url)):
                    raise DownloadError("下一章链接回到已下载章节，已停止并保留记录。")
                title = self._format_title(raw_title, saved_count + 1)
                self._check_stop()
                store.save_chapter(current_url, title, content, next_url)
                saved_count = store.count()
                self.log(f"已保存：{title}")
                self.on_progress(DownloadProgress(book_name, title, saved_count))
                current_url = next_url
                if current_url:
                    self._wait(REQUEST_DELAY)
            status = "end_reached"
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
                        output_path = store.export(output_dir)
            except (OSError, sqlite3.Error, StorageError) as error:
                status = "failed"
                message += f" TXT 导出失败：{error}。章节仍在下载记录中，重试可重新导出。"
            finally:
                if store is not None:
                    store.close()
                self._cache.clear()
        self.log(message)
        if output_path:
            self.log(f"TXT 已保存到：{output_path}")
        return DownloadResult(status, book_name, saved_count, output_path, message)
