"""Read-only library index and Tkinter bookshelf for existing SQLite downloads."""

import sqlite3
import tkinter as tk
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk


@dataclass(frozen=True)
class BookRecord:
    database: Path
    title: str
    source: str
    url: str
    chapters: int
    status: str
    output_name: str
    modified: float

    def export_path(self, suffix):
        filename = Path(self.output_name)
        if (filename.name != self.output_name or not self.output_name.endswith(".txt")
                or suffix not in (".txt", ".epub")):
            return None
        target = self.database.parent.parent / filename.with_suffix(suffix)
        return target if target.is_file() and not target.is_symlink() else None


def scan_books(directory):
    """List saved tasks without modifying their databases or chapter contents."""
    state = Path(directory).expanduser() / ".novel_state"
    if not state.is_dir():
        return []
    records = []
    for database in state.glob("*.sqlite3"):
        if database.is_symlink() or not database.is_file():
            continue
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                task = db.execute(
                    "SELECT book_name, source, start_url, output_name, status "
                    "FROM task WHERE id=1"
                ).fetchone()
                if task is None:
                    continue
                count = db.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
            records.append(BookRecord(
                database, task[0], task[1], task[2], count, task[4],
                task[3], database.stat().st_mtime,
            ))
        except (sqlite3.Error, OSError, ValueError):
            # A damaged task must not make every other book inaccessible.
            continue
    return sorted(records, key=lambda item: item.modified, reverse=True)


class BookshelfWindow:
    def __init__(self, parent, directory, on_update, on_open, busy):
        self.directory = Path(directory).expanduser().resolve()
        self.on_update = on_update
        self.on_open = on_open
        self.busy = busy
        self.window = tk.Toplevel(parent)
        self.window.title("我的书架 · 下载记录")
        self.window.geometry("930x500")
        self.window.minsize(720, 380)
        self.search = tk.StringVar()
        self.books = []
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(2, weight=1)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="我的书架", font=("Microsoft YaHei UI", 17, "bold")
                  ).grid(row=0, column=0, sticky="w")
        filter_frame = ttk.Frame(frame)
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        ttk.Label(filter_frame, text="筛选").pack(side="left", padx=(0, 8))
        ttk.Entry(filter_frame, textvariable=self.search).pack(side="left", fill="x", expand=True)
        ttk.Button(filter_frame, text="刷新", command=self.refresh).pack(side="left", padx=(10, 0))

        table_frame = ttk.Frame(frame)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = ("title", "source", "chapters", "status", "txt", "epub")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        specs = (
            ("title", "书名", 310), ("source", "来源", 130),
            ("chapters", "已保存章数", 100), ("status", "状态", 110),
            ("txt", "TXT", 55), ("epub", "EPUB", 60),
        )
        for key, label, width in specs:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=key == "title", anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda _: self.open_export(".txt"))

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="w", pady=(14, 0))
        ttk.Button(buttons, text="检查更新 / 继续", command=self.update_book).pack(side="left")
        ttk.Button(buttons, text="打开 TXT", command=lambda: self.open_export(".txt")
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="打开 EPUB", command=lambda: self.open_export(".epub")
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="移除下载记录", command=self.remove_record
                   ).pack(side="left", padx=(8, 0))
        self.status = tk.StringVar()
        ttk.Label(frame, textvariable=self.status).grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.search.trace_add("write", lambda *_: self.render())
        self.refresh()

    def refresh(self):
        self.books = scan_books(self.directory)
        self.render()

    def render(self):
        self.tree.delete(*self.tree.get_children())
        word = self.search.get().strip().casefold()
        shown = 0
        for index, book in enumerate(self.books):
            if word and not any(word in value.casefold()
                                for value in (book.title, book.source, book.url)):
                continue
            self.tree.insert("", "end", iid=str(index), values=(
                book.title, book.source, book.chapters,
                "完成" if book.status == "end_reached" else "可续传",
                "有" if book.export_path(".txt") else "—",
                "有" if book.export_path(".epub") else "—",
            ))
            shown += 1
        self.status.set(f"显示 {shown} 本；记录目录：{self.directory}")

    def selected(self):
        choice = self.tree.selection()
        if not choice:
            messagebox.showinfo("未选择小说", "请先在书架中选择一本小说。", parent=self.window)
            return None
        return self.books[int(choice[0])]

    def update_book(self):
        book = self.selected()
        if not book:
            return
        if self.busy():
            messagebox.showwarning("任务运行中", "请先停止或完成当前下载任务。", parent=self.window)
            return
        self.on_update(book.url, str(self.directory))

    def open_export(self, suffix):
        book = self.selected()
        if not book:
            return
        path = book.export_path(suffix)
        if path is None:
            messagebox.showinfo("文件不存在", "此格式尚未导出，可点击检查更新后选择格式生成。",
                                parent=self.window)
            return
        self.on_open(path)

    def remove_record(self):
        book = self.selected()
        if not book:
            return
        if self.busy():
            messagebox.showwarning("任务运行中", "请先完成当前任务。", parent=self.window)
            return
        confirmed = messagebox.askyesno(
            "确认移除记录",
            f"从书架移除《{book.title}》的断点续传数据库？\n\n"
            "不会删除 TXT/EPUB 文件，但此操作不能撤销；请先备份 .novel_state。",
            parent=self.window,
        )
        if not confirmed:
            return
        try:
            book.database.unlink()
        except OSError as error:
            messagebox.showerror("移除失败", str(error), parent=self.window)
            return
        self.refresh()
