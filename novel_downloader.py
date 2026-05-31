"""
双站小说下载器（纯 requests 版，零浏览器依赖）
支持：话本小说 (ihuaben.com) / SF轻小说·菠萝包 (sfacg.com)
用法：直接运行，按提示粘贴网址即可。
依赖：pip install requests beautifulsoup4
"""

import os
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HUABEN_BASE = "https://www.ihuaben.com"
SFACG_BASE = "https://book.sfacg.com"
_ROLE_URL_RE = re.compile(r'/juese/')

# 网络相关
REQUEST_TIMEOUT = 15      # 单次请求超时（秒）
MAX_RETRIES = 3           # 失败重试次数
RETRY_WAIT = 3            # 重试间隔（秒）
REQUEST_DELAY = 0.8       # 每抓一章之间的礼貌延迟，别把人家服务器打挂

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'zh-CN,zh;q=0.9',
}


# ==========================================================
# 站点适配器：每个站只负责“怎么取书名+首章”“怎么解析章节”“怎么找下一章”
# 公共的请求、写文件、断点续传全部交给 NovelDownloader
# ==========================================================
class SiteAdapter:
    source_name = ""
    base = ""
    name_prefix = "小说_"
    CHAPTER_RE = re.compile(r'.*')          # 校验“下一章”链接是否真的是章节页
    NEXT_TEXTS = ('下一章',)                 # “下一章”按钮可能的文字

    def __init__(self, downloader):
        self.dl = downloader

    def prepare(self, url):
        """返回 (书名, 起始章节URL)，失败返回 (None, None)。"""
        raise NotImplementedError

    def parse_chapter(self, soup, url):
        """返回 (原始标题, 正文文本)。"""
        raise NotImplementedError

    def find_next(self, soup):
        """从当前页找下一章的绝对 URL，没有则返回 None。"""
        for a in soup.find_all('a'):
            if a.get_text(strip=True) in self.NEXT_TEXTS:
                nxt = self.dl._resolve_url(a.get('href'), self.base)
                # 找到“下一章”但目标不是章节页（多半指回目录），视为读完
                if nxt and self.CHAPTER_RE.search(nxt):
                    return nxt
                return None
        return None

    @staticmethod
    def _clean_title(raw):
        return raw.replace('《', '').replace('》', '').strip()


# ----------------------------- 话本小说 -----------------------------
class HuabenAdapter(SiteAdapter):
    source_name = "话本小说"
    base = HUABEN_BASE
    name_prefix = "话本_"
    CHAPTER_RE = re.compile(r'/\d+\.html')
    NEXT_TEXTS = ('下一章', '下一篇')

    def prepare(self, url):
        soup = self.dl._get_soup(url)
        if soup is None:
            return None, None

        # 情况一：粘的是某一章 → 直接从这章开始平推
        if soup.find('div', id='contentsource'):
            title = soup.find('title')
            book_name = self._clean_title(title.text.split('-')[0]) if title else "话本小说作品"
            print("✅ 检测到章节页，从当前章开始平推...")
            return book_name, url

        # 情况二：粘的是书籍主页 → 取书名 + 找到第一章
        name_elem = soup.find('h1', class_='text-danger')
        book_name = name_elem.text.strip() if name_elem else "未命名小说"

        print("🔍 正在定位【第一章】...")
        chapters = []
        for p in soup.find_all('p'):
            span = p.find('span', class_='chapterTitle')
            link = span.find('a') if span else None
            if not link:
                continue
            c_url = urljoin(HUABEN_BASE, link.get('href'))
            m = re.search(r'/(\d+)\.html$', c_url)
            if m:
                chapters.append((int(m.group(1)), c_url))

        if not chapters:
            print("😭 没找到章节列表。请确认粘的是书籍主页或某一章的网址。")
            return book_name, None

        chapters.sort(key=lambda x: x[0])
        return book_name, chapters[0][1]

    def _parse_paragraph(self, p):
        """提取单个 <p> 文本，处理角色名前缀（如 角色：对白）"""
        role_links = p.find_all('a', href=_ROLE_URL_RE)
        p_text = ''
        if role_links:
            for link in role_links:
                p_text += link.text.strip() + '：'

        text = p.get_text()
        if text:
            if p_text:
                for role in role_links:
                    text = text.replace(role.text.strip(), '', 1)
                p_text += text.strip()
            else:
                p_text = text.strip()
        return p_text

    def parse_chapter(self, soup, url):
        h1 = soup.find('h1')
        raw_title = self._clean_title(h1.text) if h1 else "未知标题"

        div = soup.find('div', id='contentsource')
        if div:
            lines = [t for p in div.find_all('p') if (t := self._parse_paragraph(p))]
            content = '\n\n'.join(lines) or "⚠️ 内容获取为空。"
        else:
            content = "⚠️ 内容获取失败（未找到正文容器）。"
        return raw_title, content


# ----------------------------- SF轻小说 -----------------------------
class SfacgAdapter(SiteAdapter):
    source_name = "SF轻小说 (菠萝包)"
    base = SFACG_BASE
    name_prefix = "SF轻小说_"
    CHAPTER_RE = re.compile(r'/Novel/\d+/\d+/\d+')
    NEXT_TEXTS = ('下一章',)

    def prepare(self, url):
        soup = self.dl._get_soup(url)
        if soup is None:
            return None, None
        title = soup.find('title')
        book_name = title.text.split('-')[0].strip() if title else "未命名轻小说"
        print("✅ 从当前阅读页开始一路平推...")
        return book_name, url

    def parse_chapter(self, soup, url):
        title_elem = soup.find(class_='article-title') or soup.find('h1')
        raw_title = title_elem.get_text(strip=True) if title_elem else "未知标题"
        # SF 的标题常带 “1.xxx” 形式的数字前缀，去掉
        if not re.search(r'第.*章', raw_title):
            raw_title = re.sub(r'^\d+[\.、\s]*', '', raw_title)

        body = soup.find(id='ChapterBody')
        if body:
            paras = [p.get_text(strip=True) for p in body.find_all('p')]
            paras = [p for p in paras if p]
            content = '\n\n'.join(paras) if paras else body.get_text('\n', strip=True)
            if not content.strip():
                print("⚠️ 正文为空，可能是 VIP 加密章节。")
                content = "⚠️ 此章节内容为空，可能为菠萝包 VIP 章节（文本被转成图片加密，无法抓取）。"
        else:
            content = "⚠️ 内容获取失败（未找到 #ChapterBody）。"
        return raw_title, content


SITE_TABLE = (
    ('ihuaben.com', HuabenAdapter),
    ('sfacg.com', SfacgAdapter),
)


# ==========================================================
# 下载器主体
# ==========================================================
class NovelDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    # ---------- 网络 ----------
    def _get_soup(self, url):
        """带重试 + 编码修正的请求，返回 BeautifulSoup，全部失败返回 None。"""
        for i in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                # requests 在无 charset 时会默认 ISO-8859-1，会把中文搞乱，这里纠正
                if not resp.encoding or resp.encoding.lower() == 'iso-8859-1':
                    resp.encoding = resp.apparent_encoding or 'utf-8'
                return BeautifulSoup(resp.text, 'html.parser')
            except Exception as e:
                if i == MAX_RETRIES - 1:
                    print(f"❌ 连续 {MAX_RETRIES} 次请求失败：{e}")
                    return None
                print(f"⚠️ 请求失败，{RETRY_WAIT}s 后重试（{i + 1}/{MAX_RETRIES}）...")
                time.sleep(RETRY_WAIT)
        return None

    def _resolve_url(self, href, base):
        if not href or 'javascript' in href.lower():
            return None
        return href if href.startswith('http') else urljoin(base, href)

    # ---------- 文件 / 进度 ----------
    def _load_progress(self, progress_file, default_url):
        if os.path.exists(progress_file):
            try:
                lines = open(progress_file, encoding='utf-8').read().strip().split('\n')
                count, saved_url = int(lines[0]), lines[1]
                print(f"🔄 检测到上次进度，从第 {count} 章继续...")
                return count, saved_url
            except Exception as e:
                print(f"⚠️ 进度文件损坏（{e}），将从头开始。")
        return 1, default_url

    def _save_progress(self, progress_file, count, url):
        """原子写入：先写临时文件再替换，写一半崩溃也不会损坏进度。"""
        tmp = progress_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as pf:
            pf.write(f"{count}\n{url}")
        os.replace(tmp, progress_file)

    @staticmethod
    def _clean_content(text):
        return re.sub(r'\n\s*\n', '\n\n', text).strip()

    @staticmethod
    def _format_title(raw, count):
        return raw if re.search(r'第.*章', raw) else f"第{count}章 {raw}"

    # ---------- 主流程 ----------
    def run(self, url):
        adapter_cls = next((cls for key, cls in SITE_TABLE if key in url), None)
        if adapter_cls is None:
            print("😵 暂不支持这个网站。目前只支持话本小说、SF轻小说。")
            return
        adapter = adapter_cls(self)

        print(f"\n🚀 启动【{adapter.source_name}】引擎...")
        book_name, first_url = adapter.prepare(url)
        if not first_url:
            return
        print(f"📖 书名: {book_name}")

        safe_name = re.sub(r'[\\/*?:"<>|]', '', f"{adapter.name_prefix}{book_name}")
        filename = f"{safe_name}.txt"
        progress_file = f"{safe_name}.progress"

        count, current_url = self._load_progress(progress_file, first_url)
        visited = set()  # 防死循环：有些站末章“下一章”会指回旧页

        write_mode = 'a' if count > 1 else 'w'
        with open(filename, write_mode, encoding='utf-8') as f:
            if write_mode == 'w':
                f.write(f"书名：{book_name}\n来源：{adapter.source_name}\n" + "=" * 50 + "\n\n")

            while current_url and current_url not in visited:
                visited.add(current_url)

                soup = self._get_soup(current_url)
                if soup is None:
                    print("⚠️ 页面加载失败，已停在此处，下次可断点续传。")
                    break

                raw_title, content = adapter.parse_chapter(soup, current_url)
                chapter_title = self._format_title(raw_title, count)
                content = self._clean_content(content)
                print(f"👉 正在抓取: {chapter_title}")

                f.write(f"{chapter_title}\n" + "-" * 30 + "\n")
                f.write(content + "\n\n" + "=" * 50 + "\n\n")
                f.flush()  # 关键：先把正文落盘，再存进度，崩溃也不丢章节

                self._save_progress(progress_file, count, current_url)

                next_url = adapter.find_next(soup)
                if next_url:
                    current_url = next_url
                    count += 1
                    time.sleep(REQUEST_DELAY)
                else:
                    print(f"\n🎉 找不到【下一章】了！共抓取 {count} 章！")
                    break

        if os.path.exists(progress_file):
            os.remove(progress_file)
        print(f"💾 已保存到: {os.path.abspath(filename)}\n")


def main():
    print("=" * 50)
    print("📚 双站小说下载器（纯 requests 版，无需浏览器）")
    print("   支持：话本小说 / SF轻小说(菠萝包)")
    print("   话本：粘贴书籍主页或任意章节网址")
    print("   SF  ：粘贴任意章节阅读页网址")
    print("   输入 q 退出")
    print("=" * 50)

    dl = NovelDownloader()
    while True:
        try:
            url = input("\n🔗 请粘贴小说网址：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break
        if not url:
            continue
        if url.lower() in ('q', 'quit', 'exit'):
            print("👋 再见！")
            break
        try:
            dl.run(url)
        except KeyboardInterrupt:
            print("\n⏸️ 已中断，进度已保存，下次粘同一网址可断点续传。")
        except Exception as e:
            print(f"💥 出错了：{e}")


if __name__ == "__main__":
    main()
