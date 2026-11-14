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
            # 向旧版 SQLite 数据库添加目录排序表，不修改原章节与任务字段。
            with self.connection:
                self.connection.execute("""
                    CREATE TABLE IF NOT EXISTS chapter_catalog (
                        url TEXT PRIMARY KEY, catalog_position INTEGER NOT NULL UNIQUE
                    )
                """)
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

    def saved_urls(self):
        return {
            row[0] for row in self.connection.execute("SELECT url FROM chapters")
        }

    def set_catalog(self, urls):
        """单事务更新目录快照，TXT 与 EPUB 按目录顺序导出。"""
        if len(urls) != len(set(urls)):
            raise StorageError("目录含有重复章节网址，已保留上次目录。")
        with self.connection:
            self.connection.execute("DELETE FROM chapter_catalog")
            self.connection.executemany(
                "INSERT INTO chapter_catalog(url, catalog_position) VALUES (?, ?)",
                ((url, position) for position, url in enumerate(urls)),
            )

    def iter_chapters(self):
        """目录中的章节按目录排序；未出现在当前目录的历史章节排在后面。"""
        return self.connection.execute("""
            SELECT chapters.* FROM chapters
            LEFT JOIN chapter_catalog AS catalog ON catalog.url = chapters.url
            ORDER BY
                CASE WHEN catalog.catalog_position IS NULL THEN 1 ELSE 0 END,
                catalog.catalog_position, chapters.position
        """)

    def last_chapter_url(self):
        row = self.connection.execute(
            "SELECT url FROM chapters ORDER BY position DESC LIMIT 1"
        ).fetchone()
        return row["url"] if row else None

    def resume_at(self, url):
        """恢复误判结束的任务；已有章节正文保持不变。"""
        if self.contains(url):
            raise StorageError("续传目标已保存，无法重复插入。")
        with self.connection:
            self.connection.execute(
                "UPDATE task SET current_url = ?, status = 'running' WHERE id = 1",
                (url,),
            )

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
                for chapter in self.iter_chapters():
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
