from DrissionPage import ChromiumPage, ChromiumOptions
from bs4 import BeautifulSoup
import time
import os
import re
from urllib.parse import urljoin

HUABEN_BASE = "https://www.ihuaben.com"
SFACG_BASE = "https://book.sfacg.com"
_ROLE_URL_RE = re.compile(r'/juese/')

# 等待相关：等元素出现的超时（秒），不再用固定 sleep 空等
ELEMENT_WAIT = 5
NEXT_BTN_WAIT = 2
INITIAL_WAIT = 2
DETECTION_INTERVAL = 1.5
MAX_RETRIES = 3
RETRY_WAIT = 3


# ==========================================================
# 站点适配器：每个网站只需实现“怎么取书名+首章”“怎么取章节”“怎么找下一章”
# 公共的主循环、写文件、存进度全部交给 DualCoreSpider 统一处理
# ==========================================================
class SiteAdapter:
    source_name = ""          # 写进文件头的来源名
    base = ""                 # 拼相对链接用的 base URL
    name_prefix = "小说_"      # 文件名前缀

    def __init__(self, spider):
        self.spider = spider
        self.page = spider.page

    def prepare(self, start_url):
        """加载起始页，返回 (书名, 第一章URL)。失败返回 (None, None)。"""
        raise NotImplementedError

    def extract_chapter(self):
        """从当前已加载的章节页提取 (清洗后的原始标题, 正文)。"""
        raise NotImplementedError

    def find_next_url(self):
        """返回下一章的绝对 URL，没有则返回 None。"""
        raise NotImplementedError


class HuabenAdapter(SiteAdapter):
    source_name = "话本小说"
    base = HUABEN_BASE
    name_prefix = "话本_"

    def prepare(self, start_url):
        if not self.spider._get_page(start_url):
            return None, None

        soup = BeautifulSoup(self.page.html, 'html.parser')
        name_elem = soup.find('h1', class_='text-danger')
        book_name = name_elem.text.strip() if name_elem else "未命名小说"

        print("🔍 正在定位【第一章】的起始坐标...")
        chapters = []
        for p in soup.find_all('p'):
            title_span = p.find('span', class_='chapterTitle')
            if not title_span:
                continue
            link = title_span.find('a')
            if not link:
                continue
            url = urljoin(HUABEN_BASE, link.get('href'))
            c_id = re.search(r'/(\d+)\.html$', url)
            if c_id:
                chapters.append({'url': url, 'id': int(c_id.group(1))})

        if not chapters:
            print("😭 找不到起始章节。可能是网络延迟或页面改版。")
            return book_name, None

        chapters.sort(key=lambda x: x['id'])
        return book_name, chapters[0]['url']

    def _parse_paragraph(self, p):
        """提取话本单个 <p> 文本，处理角色名前缀"""
        role_links = p.find_all('a', href=_ROLE_URL_RE)
        p_text = ''
        if role_links:
            for link in role_links:
                p_text += link.text.strip() + '：'

        text_content = p.get_text()
        if text_content:
            if p_text:
                for role in role_links:
                    text_content = text_content.replace(role.text.strip(), '', 1)
                p_text += text_content.strip()
            else:
                p_text = text_content.strip()
        return p_text

    def extract_chapter(self):
        # 等正文容器出现，替代固定 sleep
        self.page.ele('#contentsource', timeout=ELEMENT_WAIT)
        soup = BeautifulSoup(self.page.html, 'html.parser')

        title_elem = soup.find('h1')
        raw_title = title_elem.text.strip() if title_elem else "未知标题"
        raw_title = raw_title.replace('《', '').replace('》', '')

        content_div = soup.find('div', id='contentsource')
        if content_div:
            lines = [
                text for p in content_div.find_all('p')
                if (text := self._parse_paragraph(p))
            ]
            content = '\n\n'.join(lines) or "⚠️ 内容获取为空。"
        else:
            content = "⚠️ 内容获取失败。"
        return raw_title, content

    def find_next_url(self):
        btn = (
            self.page.ele('tag:a@@text():下一章', timeout=NEXT_BTN_WAIT)
            or self.page.ele('tag:a@@text():下一篇', timeout=NEXT_BTN_WAIT)
        )
        return self.spider._resolve_next_url(
            btn.attr('href') if btn else None, HUABEN_BASE
        )


class SfacgAdapter(SiteAdapter):
    source_name = "SF轻小说 (菠萝包)"
    base = SFACG_BASE
    name_prefix = "SF轻小说_"

    def prepare(self, start_url):
        # SF 是直接从当前阅读页开始平推，页面已经在 start_url 上
        raw_title = self.page.title
        book_name = raw_title.split('-')[0].strip() if '-' in raw_title else "未命名轻小说"
        print("✅ 从当前阅读页开始一路平推...")
        return book_name, start_url

    def extract_chapter(self):
        title_elem = self.page.ele('.article-title', timeout=NEXT_BTN_WAIT)
        raw_title = title_elem.text.strip() if title_elem else "未知标题"
        if not re.search(r'第.*章', raw_title):
            raw_title = re.sub(r'^\d+[\.、\s]*', '', raw_title)

        content_elem = self.page.ele('#ChapterBody', timeout=ELEMENT_WAIT)
        if content_elem:
            content = content_elem.text
            if not content.strip():
                print("⚠️ 正文为空，可能为 VIP 加密章节。")
                content = "⚠️ 此章节内容为空，可能为菠萝包 VIP 章节（文本已被转化为图片加密）。"
        else:
            print("⚠️ 未找到正文内容！")
            content = "⚠️ 内容获取失败。"
        return raw_title, content

    def find_next_url(self):
        btn = self.page.ele('tag:a@@text():下一章', timeout=NEXT_BTN_WAIT)
        return self.spider._resolve_next_url(
            btn.attr('href') if btn else None, SFACG_BASE
        )


class DualCoreSpider:
    def __init__(self):
        print("🤖 正在启动【双核引擎】自动化浏览器...")
        co = ChromiumOptions()
        co.set_local_port(9222)
        try:
            self.page = ChromiumPage(co)
            print("✅ 成功接管浏览器！\n")
        except Exception as e:
            print(f"❌ 接管失败！错误：{e}")
            print("请确保你已经启动了带有 9222 端口的浏览器！")
            self.page = None

    # ---------- 基础工具 ----------
    def _get_page(self, url) -> bool:
        """带重试的页面加载。get() 本身会阻塞到加载完成，不再额外 sleep。"""
        for i in range(MAX_RETRIES):
            try:
                self.page.get(url)
                return True
            except Exception as e:
                if i == MAX_RETRIES - 1:
                    print(f"❌ 连续 {MAX_RETRIES} 次加载失败：{e}")
                    return False
                print(f"⚠️ 加载失败，{RETRY_WAIT}s 后重试（{i + 1}/{MAX_RETRIES}）...")
                time.sleep(RETRY_WAIT)
        return False

    def _resolve_next_url(self, href, base):
        if not href or 'javascript' in href.lower():
            return None
        return href if href.startswith('http') else urljoin(base, href)

    def _load_progress(self, progress_file, default_url):
        if os.path.exists(progress_file):
            try:
                lines = open(progress_file, encoding='utf-8').read().strip().split('\n')
                chapter_count = int(lines[0])
                saved_url = lines[1]
                print(f"🔄 检测到上次进度，从第 {chapter_count} 章继续...")
                return chapter_count, saved_url
            except Exception as e:
                print(f"⚠️ 进度文件损坏（{e}），将从头开始。")
        return 1, default_url

    def _save_progress(self, progress_file, chapter_count, current_url):
        """原子写入：先写临时文件再替换，避免写一半崩溃导致进度损坏。"""
        tmp = progress_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as pf:
            pf.write(f"{chapter_count}\n{current_url}")
        os.replace(tmp, progress_file)

    def clean_content(self, text) -> str:
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text.strip()

    def _format_title(self, raw_title, count) -> str:
        if re.search(r'第.*章', raw_title):
            return raw_title
        return f"第{count}章 {raw_title}"

    # ---------- 统一主循环 ----------
    def _scrape(self, adapter):
        book_name, first_url = adapter.prepare(adapter._start_url)
        if not first_url:
            return
        print(f"📖 书名: {book_name}")

        safe_name = re.sub(r'[\\/*?:"<>|]', '', f"{adapter.name_prefix}{book_name}")
        filename = f"{safe_name}.txt"
        progress_file = f"{safe_name}.progress"

        chapter_count, current_url = self._load_progress(progress_file, first_url)
        visited = set()  # 防死循环：有些站点末章“下一章”会指回旧页

        write_mode = 'a' if chapter_count > 1 else 'w'
        with open(filename, write_mode, encoding='utf-8') as f:
            if write_mode == 'w':
                f.write(f"书名：{book_name}\n来源：{adapter.source_name}\n" + "=" * 50 + "\n\n")

            while current_url and current_url not in visited:
                visited.add(current_url)

                # 已经在目标页（如 SF 首章）就不重复加载
                if self.page.url != current_url:
                    if not self._get_page(current_url):
                        print("⚠️ 页面加载失败，跳出。")
                        break

                raw_title, content = adapter.extract_chapter()
                chapter_title = self._format_title(raw_title, chapter_count)
                content = self.clean_content(content)
                print(f"👉 正在抓取: {chapter_title}")

                f.write(f"{chapter_title}\n" + "-" * 30 + "\n")
                f.write(content + "\n\n" + "=" * 50 + "\n\n")
                f.flush()  # 关键：先把正文落盘，再存进度，避免崩溃丢章节

                self._save_progress(progress_file, chapter_count, current_url)

                next_url = adapter.find_next_url()
                if next_url:
                    current_url = next_url
                    chapter_count += 1
                else:
                    print(f"\n🎉 找不到【下一章】了！共抓取了 {chapter_count} 章！")
                    break

        if os.path.exists(progress_file):
            os.remove(progress_file)
        print(f"💾 已安全保存在: {os.path.abspath(filename)}")

    # ---------- 雷达路由 ----------
    def wait_for_target(self):
        if not self.page:
            return

        print("👀 双核雷达已开启，正在后台静默监视...")
        print("👉 支持网站 1：在浏览器中打开【话本小说】的某本书的主页。")
        print("👉 支持网站 2：在浏览器中打开【SF轻小说(菠萝包)】某本书的【第一章阅读页】。")
        print("等待目标出现...\n")

        while True:
            try:
                current_url = self.page.url
            except Exception as e:
                print(f"⚠️ 获取 URL 失败：{e}")
                time.sleep(1)
                continue

            adapter = None
            if "ihuaben.com/book/" in current_url:
                print(f"🎯 锁定【话本小说】主页：{current_url}")
                adapter = HuabenAdapter(self)
            elif re.search(r'book\.sfacg\.com/Novel/\d+/\d+/\d+', current_url):
                print(f"🎯 锁定【SF轻小说】阅读页：{current_url}")
                adapter = SfacgAdapter(self)

            if adapter:
                adapter._start_url = current_url
                time.sleep(INITIAL_WAIT)
                self._scrape(adapter)
                break

            time.sleep(DETECTION_INTERVAL)


def main():
    spider = DualCoreSpider()
    spider.wait_for_target()


if __name__ == "__main__":
    main()
