from DrissionPage import ChromiumPage, ChromiumOptions
from bs4 import BeautifulSoup
import time
import os
import re
from urllib.parse import urljoin

HUABEN_BASE = "https://www.ihuaben.com"
SFACG_BASE = "https://book.sfacg.com"
_ROLE_URL_RE = re.compile(r'/juese/')

PAGE_LOAD_WAIT = 1.5
INITIAL_WAIT = 2
DETECTION_INTERVAL = 1.5
MAX_RETRIES = 3
RETRY_WAIT = 3


class DualCoreSpider:
    def __init__(self):
        print("🤖 正在启动【双核引擎】自动化浏览器...")
        co = ChromiumOptions()
        co.set_local_port(9222)
        try:
            self.page = ChromiumPage(co)
            print("✅ 成功接管浏览器！反爬虫系统已瘫痪！\n")
        except Exception as e:
            print(f"❌ 接管失败！错误：{e}")
            print("请确保你已经启动了带有 9222 端口的浏览器！")
            self.page = None

    def _get_page(self, url) -> bool:
        """带重试的页面加载，全部失败返回 False"""
        for i in range(MAX_RETRIES):
            try:
                self.page.get(url)
                time.sleep(PAGE_LOAD_WAIT)
                return True
            except Exception as e:
                if i == MAX_RETRIES - 1:
                    print(f"❌ 连续 {MAX_RETRIES} 次加载失败：{e}")
                    return False
                print(f"⚠️ 加载失败，{RETRY_WAIT}s 后重试（{i + 1}/{MAX_RETRIES}）...")
                time.sleep(RETRY_WAIT)
        return False

    def _resolve_next_url(self, href, base) -> str | None:
        """将相对 href 转为绝对 URL，无效链接返回 None"""
        if not href or 'javascript' in href.lower():
            return None
        return href if href.startswith('http') else urljoin(base, href)

    def _load_progress(self, progress_file, default_url) -> tuple[int, str]:
        """读取断点进度，返回 (章节数, URL)"""
        if os.path.exists(progress_file):
            try:
                lines = open(progress_file, encoding='utf-8').read().strip().split('\n')
                chapter_count = int(lines[0])
                saved_url = lines[1]
                print(f"🔄 检测到上次进度，从第 {chapter_count} 章继续...")
                return chapter_count, saved_url
            except Exception:
                pass
        return 1, default_url

    def _save_progress(self, progress_file, chapter_count, current_url):
        with open(progress_file, 'w', encoding='utf-8') as pf:
            pf.write(f"{chapter_count}\n{current_url}")

    def clean_content(self, text) -> str:
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text.strip()

    def _parse_paragraph(self, p) -> str:
        """提取话本小说单个 <p> 的文本，处理角色名前缀"""
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

    # ==========================================
    # 雷达：监听浏览器 URL，路由分发
    # ==========================================
    def wait_for_target(self):
        if not self.page:
            return

        print("👀 双核雷达已开启，正在后台静默监视...")
        print("👉 支持网站 1：在浏览器中打开【话本小说】的某本书的主页。")
        print("👉 支持网站 2：在浏览器中打开【SF轻小说(菠萝包)】的某本书的【第一章阅读页】。")
        print("等待目标出现...\n")

        while True:
            try:
                current_url = self.page.url
            except Exception as e:
                print(f"⚠️ 获取 URL 失败：{e}")
                time.sleep(1)
                continue

            if "ihuaben.com/book/" in current_url:
                print(f"🎯 锁定目标！检测到【话本小说】主页：{current_url}")
                time.sleep(INITIAL_WAIT)
                self.run_huaben(current_url)
                break

            elif re.search(r'book\.sfacg\.com/Novel/\d+/\d+/\d+', current_url):
                print(f"🎯 锁定目标！检测到【SF轻小说】阅读页：{current_url}")
                time.sleep(INITIAL_WAIT)
                self.run_sfacg(current_url)
                break

            time.sleep(DETECTION_INTERVAL)

    # ==========================================
    # 引擎一：话本小说解析核心
    # ==========================================
    def run_huaben(self, start_url):
        print("\n🚀 启动【话本小说】专属引擎...")
        if not self._get_page(start_url):
            return

        soup = BeautifulSoup(self.page.html, 'html.parser')

        book_name_elem = soup.find('h1', class_='text-danger')
        book_name = book_name_elem.text.strip() if book_name_elem else "未命名小说"

        safe_name = re.sub(r'[\\/*?:"<>|]', '', f"话本_{book_name}")
        filename = f"{safe_name}.txt"
        progress_file = f"{safe_name}.progress"

        print(f"📖 书名: {book_name}")
        print("🔍 正在定位【第一章】的起始坐标...")

        chapters = []
        for p in soup.find_all('p'):
            title_span = p.find('span', class_='chapterTitle')
            if title_span:
                chapter_link = title_span.find('a')
                if chapter_link:
                    url = urljoin(HUABEN_BASE, chapter_link.get('href'))
                    c_id = re.search(r'/(\d+)\.html$', url)
                    if c_id:
                        chapters.append({'url': url, 'id': int(c_id.group(1))})

        if not chapters:
            print("😭 找不到起始章节。可能是网络延迟或页面改版。")
            return

        chapters.sort(key=lambda x: x['id'])
        chapter_count, current_url = self._load_progress(progress_file, chapters[0]['url'])

        write_mode = 'a' if chapter_count > 1 else 'w'
        with open(filename, write_mode, encoding='utf-8') as f:
            if write_mode == 'w':
                f.write(f"书名：{book_name}\n来源：话本小说\n" + "=" * 50 + "\n\n")

            while current_url:
                if not self._get_page(current_url):
                    print("⚠️ 页面加载失败，跳出。")
                    break

                soup = BeautifulSoup(self.page.html, 'html.parser')
                title_elem = soup.find('h1')
                raw_title = title_elem.text.strip() if title_elem else "未知标题"
                raw_title = raw_title.replace('《', '').replace('》', '')

                chapter_title = (
                    f"第{chapter_count}章 {raw_title}"
                    if not re.search(r'第.*章', raw_title)
                    else raw_title
                )
                print(f"👉 正在抓取: {chapter_title}")

                content_div = soup.find('div', id='contentsource')
                if content_div:
                    lines = [
                        text for p in content_div.find_all('p')
                        if (text := self._parse_paragraph(p))
                    ]
                    content = self.clean_content('\n\n'.join(lines))
                    f.write(f"{chapter_title}\n" + "-" * 30 + "\n")
                    f.write(content if content else "⚠️ 内容获取为空。\n")
                    f.write("\n\n" + "=" * 50 + "\n\n")
                else:
                    f.write(f"{chapter_title}\n⚠️ 内容获取失败。\n\n\n")

                self._save_progress(progress_file, chapter_count, current_url)

                next_btn = (
                    self.page.ele('tag:a@@text():下一章', timeout=2)
                    or self.page.ele('tag:a@@text():下一篇', timeout=2)
                )
                next_url = self._resolve_next_url(
                    next_btn.attr('href') if next_btn else None, HUABEN_BASE
                )
                if next_url:
                    current_url = next_url
                    chapter_count += 1
                else:
                    break

        if os.path.exists(progress_file):
            os.remove(progress_file)
        print(f"\n💾 话本小说爬取结束，保存在: {os.path.abspath(filename)}")

    # ==========================================
    # 引擎二：SF轻小说 (菠萝包) 解析核心
    # ==========================================
    def run_sfacg(self, start_url):
        print("\n🚀 启动【SF轻小说】专属引擎...")

        raw_title = self.page.title
        book_name = raw_title.split('-')[0].strip() if '-' in raw_title else "未命名轻小说"

        safe_name = re.sub(r'[\\/*?:"<>|]', '', f"SF轻小说_{book_name}")
        filename = f"{safe_name}.txt"
        progress_file = f"{safe_name}.progress"

        print(f"📖 书名: {book_name}")
        print("✅ 从当前阅读页开始一路平推...\n")

        chapter_count, current_url = self._load_progress(progress_file, start_url)

        write_mode = 'a' if chapter_count > 1 else 'w'
        with open(filename, write_mode, encoding='utf-8') as f:
            if write_mode == 'w':
                f.write(f"书名：{book_name}\n来源：SF轻小说 (菠萝包)\n" + "=" * 50 + "\n\n")

            while current_url:
                if self.page.url != current_url:
                    if not self._get_page(current_url):
                        print("⚠️ 页面加载失败，跳出。")
                        break

                title_elem = self.page.ele('.article-title', timeout=2)
                raw_chapter_title = title_elem.text.strip() if title_elem else "未知标题"

                if not re.search(r'第.*章', raw_chapter_title):
                    clean_title = re.sub(r'^\d+[\.、\s]*', '', raw_chapter_title)
                    chapter_title = f"第{chapter_count}章 {clean_title}"
                else:
                    chapter_title = raw_chapter_title

                print(f"👉 正在抓取: {chapter_title}")

                content_elem = self.page.ele('#ChapterBody', timeout=2)
                if content_elem:
                    content = content_elem.text
                    if not content.strip():
                        print("⚠️ 正文为空，可能为 VIP 加密章节。")
                        content = "⚠️ 此章节内容为空，可能为菠萝包 VIP 章节（文本已被转化为图片加密）。"
                    f.write(f"{chapter_title}\n" + "-" * 30 + "\n")
                    f.write(content + "\n\n" + "=" * 50 + "\n\n")
                else:
                    print("⚠️ 未找到正文内容！")
                    f.write(f"{chapter_title}\n⚠️ 内容获取失败。\n\n\n")

                self._save_progress(progress_file, chapter_count, current_url)

                next_btn = self.page.ele('tag:a@@text():下一章', timeout=2)
                next_url = self._resolve_next_url(
                    next_btn.attr('href') if next_btn else None, SFACG_BASE
                )
                if next_url:
                    current_url = next_url
                    chapter_count += 1
                else:
                    print(f"\n🎉 找不到【下一章】了！共抓取了 {chapter_count} 章！")
                    break

        if os.path.exists(progress_file):
            os.remove(progress_file)
        print(f"💾 SF轻小说已安全保存在: {os.path.abspath(filename)}")


def main():
    spider = DualCoreSpider()
    spider.wait_for_target()


if __name__ == "__main__":
    main()
