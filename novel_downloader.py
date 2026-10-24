"""运行此文件打开窗口；--cli 使用交互命令行，--url 下载指定网址。"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="话本小说 / SF轻小说下载器")
    parser.add_argument("--cli", action="store_true", help="使用交互命令行")
    parser.add_argument("--url", help="直接下载指定网址")
    parser.add_argument("--output", help="保存目录，默认使用项目内的 downloads")
    args = parser.parse_args()
    try:
        from novel_core import DEFAULT_OUTPUT_DIR, NovelDownloader
    except ModuleNotFoundError as error:
        if error.name not in ("requests", "bs4"):
            raise
        print("缺少依赖。请先执行：python -m pip install -r requirements_novel.txt")
        return 1

    if not args.cli and not args.url:
        from novel_gui import main as gui_main
        gui_main()
        return 0

    output_dir = args.output or DEFAULT_OUTPUT_DIR
    with NovelDownloader() as downloader:
        if args.url:
            result = downloader.run(args.url, output_dir)
            return 1 if result.status == "failed" else 0
        print("双站小说下载器。话本可输入书籍或章节页，SF请输入章节阅读页。")
        print("输入 q 退出；相同网址和保存目录会恢复已有任务。")
        while True:
            try:
                url = input("\n小说网址：").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if url.lower() in ("q", "quit", "exit"):
                break
            if url:
                downloader.run(url, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
