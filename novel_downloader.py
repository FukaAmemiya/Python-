"""运行此文件打开窗口；--cli 使用交互命令行，--url 下载指定网址。"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="话本小说 / SF轻小说下载器")
    parser.add_argument("--cli", action="store_true", help="使用交互命令行")
    parser.add_argument("--self-test", metavar="FILE", help=argparse.SUPPRESS)
    parser.add_argument("--server", action="store_true", help="启动仅在本机访问的 Web UI")
    parser.add_argument("--port", type=int, default=18423, help="Web UI 本地端口")
    parser.add_argument("--url", help="直接下载指定网址")
    parser.add_argument("--output", help="保存目录，默认使用项目内的 downloads")
    parser.add_argument("--format", choices=("txt", "epub", "both"), default="both", help="导出格式，默认双格式")
    args = parser.parse_args()
    try:
        from novel_core import DEFAULT_OUTPUT_DIR, NovelDownloader
    except ModuleNotFoundError as error:
        if error.name not in ("requests", "bs4"):
            raise
        print("缺少依赖。请先执行：python -m pip install -r requirements_novel.txt")
        return 1

    if args.self_test:
        # Used only by Windows CI to verify the frozen GUI executable's imports.
        from pathlib import Path
        from novel_epub import export_epub
        from novel_library import scan_books
        from novel_gui import NovelApp
        from novel_web import DownloadDashboard
        assert export_epub and scan_books and NovelApp and DownloadDashboard
        Path(args.self_test).write_text("bundle-ok", encoding="utf-8")
        return 0

    if args.server:
        from novel_web import serve
        serve(args.port, args.output or DEFAULT_OUTPUT_DIR)
        return 0

    if not args.cli and not args.url:
        from novel_gui import main as gui_main
        gui_main()
        return 0

    output_dir = args.output or DEFAULT_OUTPUT_DIR
    with NovelDownloader() as downloader:
        if args.url:
            result = downloader.run(args.url, output_dir, output_format=args.format)
            return 1 if result.status == "failed" else 0
        print("双站小说下载器。话本和 SF 均可输入书籍主页、目录或章节页。")
        print("输入 q 退出；相同网址和保存目录会恢复已有任务。")
        while True:
            try:
                url = input("\n小说网址：").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if url.lower() in ("q", "quit", "exit"):
                break
            if url:
                downloader.run(url, output_dir, output_format=args.format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
