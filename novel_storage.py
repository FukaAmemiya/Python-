"""正文与续传位置通过 SQLite 事务一起保存。"""

import os
import sqlite3
import tempfile
from pathlib import Path


class StorageError(Exception):
    """下载记录不完整、损坏或无法安全写入。"""


class DownloadStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA synchronous = FULL")
            if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise StorageError("下载记录损坏，已保留原文件，请选择其他保存目录。")
        except Exception:
            self.connection.close()
            raise

    def initialize(self, start_url, book_name, source, current_url, output_name):
        self.connection.executescript("""
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
        """)
        with self.connection:
            self.connection.execute(
                "INSERT INTO task VALUES (1, ?, ?, ?, ?, ?, 'running')",
                (start_url, book_name, source, current_url, output_name),
            )

    def task(self):
        row = self.connection.execute("SELECT * FROM task WHERE id = 1").fetchone()
        if row is None:
            raise StorageError("下载记录不完整，已保留原文件，请选择其他保存目录。")
        return row

    def count(self):
        return self.connection.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]

    def contains(self, url):
        return self.connection.execute(
            "SELECT 1 FROM chapters WHERE url = ?", (url,)
        ).fetchone() is not None

    def save_chapter(self, url, title, content, next_url):
        # 事务失败会同时撤销正文和进度。
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.task()["current_url"] != url:
                raise StorageError("进度被其他任务修改，请勿同时下载同一任务。")
            self.connection.execute(
                "INSERT INTO chapters VALUES (?, ?, ?, ?)",
                (url, self.count() + 1, title, content),
            )
            self.connection.execute(
                "UPDATE task SET current_url = ?, status = ? WHERE id = 1",
                (next_url, "running" if next_url else "end_reached"),
            )

    def export(self, output_dir):
        task = self.task()
        name = task["output_name"]
        if Path(name).name != name or not name.endswith(".txt"):
            raise StorageError("记录中的导出文件名无效，已停止写入。")
        target = Path(output_dir) / name
        fd, temporary = tempfile.mkstemp(
            prefix=".novel-export-", suffix=".tmp", dir=output_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(f"书名：{task['book_name']}\n来源：{task['source']}\n")
                stream.write(f"起始网址：{task['start_url']}\n" + "=" * 50 + "\n\n")
                for chapter in self.connection.execute(
                    "SELECT * FROM chapters ORDER BY position"
                ):
                    stream.write(chapter["title"] + "\n" + "-" * 30 + "\n")
                    stream.write(chapter["content"] + "\n\n" + "=" * 50 + "\n\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def close(self):
        self.connection.close()
