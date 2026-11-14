"""Local browser dashboard for the dual-site novel downloader.

Only binds to loopback; this is intentionally not a public-facing web service.
"""

import html
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from novel_core import DEFAULT_OUTPUT_DIR, DownloadError, NovelDownloader, normalize_url


class DownloadDashboard:
    def __init__(self, output_dir=DEFAULT_OUTPUT_DIR):
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.logs = []
        self.status = "准备就绪"
        self.detail = "尚未开始下载"

    def snapshot(self):
        with self.lock:
            return self.status, self.detail, list(self.logs[-80:])

    def log(self, text):
        with self.lock:
            self.logs.append(str(text))
            self.logs = self.logs[-300:]

    def progress(self, progress):
        with self.lock:
            if progress.total_count:
                count = f"{progress.saved_count}/{progress.total_count}"
            else:
                count = str(progress.saved_count)
            self.detail = f"{progress.book_name} · {count} 章 · {progress.chapter_title}"

    def start(self, url, output_format):
        url = normalize_url(url)
        if output_format not in ("txt", "epub", "both"):
            raise ValueError("输出格式必须为 TXT、EPUB 或两者。")
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("已有任务运行中。请先停止当前任务。")
            self.stop_event = threading.Event()
            self.status = "下载中"
            self.detail = "正在识别书籍和章节目录"
            self.logs = []
            self.thread = threading.Thread(
                target=self._worker, args=(url, output_format, self.stop_event),
                daemon=True,
            )
            self.thread.start()

    def _worker(self, url, output_format, stop_event):
        try:
            with NovelDownloader(
                on_log=self.log, on_progress=self.progress, stop_event=stop_event
            ) as downloader:
                result = downloader.run(url, self.output_dir, output_format)
            with self.lock:
                self.status = result.message
        except Exception as error:
            self.log(f"程序错误：{error}")
            with self.lock:
                self.status = f"下载失败：{error}"

    def stop(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.stop_event.set()
                self.status = "正在停止并保存"

    def files(self):
        # No arbitrary file paths are accepted from the web request.
        return sorted(
            (path for path in self.output_dir.iterdir()
             if path.is_file() and path.suffix.lower() in (".txt", ".epub")),
            key=lambda path: path.stat().st_mtime, reverse=True,
        )


def serve(port=18423, output_dir=DEFAULT_OUTPUT_DIR):
    dashboard = DownloadDashboard(output_dir)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, text, content_type="text/html; charset=utf-8"):
            data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            target = urlsplit(self.path)
            if target.path == "/":
                self.reply(200, self.page())
                return
            if target.path == "/file":
                name = parse_qs(target.query).get("name", [""])[0]
                # Use the exact basename from the managed output directory.
                if not name or Path(name).name != name or "/" in name or "\\" in name:
                    self.send_error(400, "Invalid file name")
                    return
                path = dashboard.output_dir / name
                if (not path.is_file() or
                        path.suffix.lower() not in (".txt", ".epub")):
                    self.send_error(404, "File not found")
                    return
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header(
                    "Content-Disposition", "attachment; filename*=UTF-8''" + quote(name)
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)

        def do_POST(self):
            if self.path not in ("/start", "/stop"):
                self.send_error(404)
                return
            # A random form token prevents unrelated pages from starting work.
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8192 or length < 1:
                self.send_error(413)
                return
            data = parse_qs(self.rfile.read(length).decode("utf-8"))
            if data.get("token", [None])[0] != dashboard.token:
                self.send_error(403)
                return
            try:
                if self.path == "/stop":
                    dashboard.stop()
                else:
                    dashboard.start(
                        data.get("url", [""])[0],
                        data.get("format", ["both"])[0],
                    )
            except (DownloadError, ValueError) as error:
                dashboard.log(str(error))
                with dashboard.lock:
                    dashboard.status = f"操作失败：{error}"
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def page(self):
            status, detail, logs = dashboard.snapshot()
            status, detail = html.escape(status), html.escape(detail)
            messages = "\n".join(html.escape(line) for line in logs)
            entries = "".join(
                '<li><a href="/file?name=' + quote(path.name) + '">'
                + html.escape(path.name) + "</a></li>"
                for path in dashboard.files()
            ) or "<li>尚无导出文件</li>"
            return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>setInterval(() => {{ if (document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "SELECT") location.reload(); }}, 5000);</script>
<title>小说下载器</title>
<style>
body{{font:16px system-ui,sans-serif;max-width:850px;margin:3em auto;
padding:0 1.2em;background:#f5f7fb;color:#223}}
section{{background:#fff;padding:1.4em;margin:1.2em 0;border-radius:12px;
box-shadow:0 2px 9px #2231}}
input{{width:98%;padding:.7em;margin:.6em 0;font-size:1em}}
button,select{{padding:.6em 1em;margin:.4em;font-size:1em}}
pre{{overflow:auto;white-space:pre-wrap;max-height:20em;background:#f1f5f9;padding:1em}}
a{{color:#2563eb}}
</style></head><body><h1>小说下载器</h1>
<p>话本小说 / SF 轻小说 · 本机 Web UI（闲置时每 5 秒刷新）</p>
<section><h2>开始下载</h2>
<form method="post" action="/start">
<input type="hidden" name="token" value="{dashboard.token}">
<input name="url" type="url" required placeholder="书籍主页、目录或章节网址">
<label>导出格式：<select name="format"><option value="both">TXT + EPUB</option>
<option value="txt">TXT</option><option value="epub">EPUB</option></select></label>
<button type="submit">开始下载</button></form>
<form method="post" action="/stop">
<input type="hidden" name="token" value="{dashboard.token}">
<button type="submit">停止并保存</button></form></section>
<section><h2>任务状态</h2><p>{status}</p><p>{detail}</p>
<pre>{messages}</pre></section>
<section><h2>已保存文件</h2><ul>{entries}</ul></section>
</body></html>"""

    with ThreadingHTTPServer(("127.0.0.1", int(port)), Handler) as server:
        print(f"本机浏览器访问：http://127.0.0.1:{port}")
        print(f"导出目录：{dashboard.output_dir}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    serve()
