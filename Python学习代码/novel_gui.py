"""Tkinter 桌面窗口；网络和文件操作在后台线程运行。"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from novel_core import DEFAULT_OUTPUT_DIR, DownloadError, DownloadResult, NovelDownloader, normalize_url


class NovelApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.busy = False
        self.closing = False
        self.output_path = None

        root.title("小说下载器 · 话本 / SF轻小说")
        root.geometry("920x680")
        root.minsize(760, 580)
        root.configure(background="#f3f5f8")
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#f3f5f8")
        style.configure("TLabel", background="#f3f5f8", foreground="#263349")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Muted.TLabel", foreground="#64748b")
        style.configure("TButton", padding=(12, 7))
        style.configure("Primary.TButton", background="#2563eb", foreground="white")
        style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("disabled", "#cbd5e1")])
        style.configure("TEntry", padding=8)
        style.configure("Horizontal.TProgressbar", background="#2563eb", troughcolor="#e2e8f0")

        page = ttk.Frame(root, padding=26)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(9, weight=1)
        ttk.Label(page, text="小说下载器", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(page, text="粘贴阅读网址，保存章节；下次可以从停止处继续。",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 22))

        self.url = tk.StringVar()
        self.directory = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        form = ttk.Frame(page)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="小说网址").grid(row=0, column=0, padx=(0, 14), sticky="w")
        self.url_entry = ttk.Entry(form, textvariable=self.url)
        self.url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(form, text="保存目录").grid(row=1, column=0, padx=(0, 14), sticky="w")
        self.directory_entry = ttk.Entry(form, textvariable=self.directory)
        self.directory_entry.grid(row=1, column=1, sticky="ew")
        self.browse_button = ttk.Button(form, text="选择目录", command=self.choose_directory)
        self.browse_button.grid(row=1, column=2, padx=(10, 0))
        ttk.Label(page, text="话本：书籍主页或章节页    ·    SF：具体章节阅读页",
                  style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 16))

        buttons = ttk.Frame(page)
        buttons.grid(row=4, column=0, sticky="ew")
        self.start_button = ttk.Button(buttons, text="开始 / 继续", style="Primary.TButton",
                                       command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="停止并保存", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=10)
        self.open_text_button = ttk.Button(buttons, text="打开 TXT", command=self.open_text, state="disabled")
        self.open_text_button.pack(side="right")
        ttk.Button(buttons, text="打开目录", command=self.open_directory).pack(side="right", padx=10)

        self.status = tk.StringVar(value="准备就绪")
        self.detail = tk.StringVar(value="已保存 0 章")
        ttk.Label(page, textvariable=self.status, wraplength=700).grid(
            row=5, column=0, sticky="w", pady=(22, 4)
        )
        ttk.Label(page, textvariable=self.detail, style="Muted.TLabel", wraplength=700).grid(
            row=6, column=0, sticky="w"
        )
        self.progress = ttk.Progressbar(page, mode="indeterminate")
        self.progress.grid(row=7, column=0, sticky="ew", pady=(12, 18))
        ttk.Label(page, text="下载日志").grid(row=8, column=0, sticky="w", pady=(0, 7))
        self.log_widget = scrolledtext.ScrolledText(
            page, height=10, state="disabled", wrap="word", relief="flat",
            padx=12, pady=12, background="white", foreground="#334155",
            font=("Microsoft YaHei UI", 10),
        )
        self.log_widget.grid(row=9, column=0, sticky="nsew")
        ttk.Label(page, text="相同网址 + 相同保存目录 = 继续任务。停止或结束时导出 TXT。",
                  style="Muted.TLabel").grid(row=10, column=0, sticky="w", pady=(12, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Return>", lambda _: self.start() if not self.busy else None)
        self.url_entry.focus_set()
        root.after(100, self.poll_events)

    def choose_directory(self):
        directory = filedialog.askdirectory(parent=self.root, title="选择小说保存目录")
        if directory:
            self.directory.set(directory)

    def append_log(self, message):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", message + "\n")
        lines = int(self.log_widget.index("end-1c").split(".")[0])
        if lines > 1500:
            self.log_widget.delete("1.0", f"{lines - 1500}.0")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.start_button, self.url_entry, self.directory_entry, self.browse_button):
            widget.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def start(self):
        if self.busy or self.closing:
            return
        url = self.url.get().strip()
        directory = self.directory.get().strip()
        try:
            normalize_url(url)
            if not directory:
                raise ValueError("请选择保存目录。")
        except (ValueError, DownloadError) as error:
            messagebox.showerror("输入有误", str(error), parent=self.root)
            return
        # 在线程启动前读取 Tk 变量，后台线程只写 Queue。
        self.stop_event = threading.Event()
        self.output_path = None
        self.open_text_button.configure(state="disabled")
        self.status.set("正在识别页面……")
        self.detail.set("已保存 0 章 · 总章数未知")
        self.append_log("\n—— 开始任务 ——")
        self.set_busy(True)
        self.worker = threading.Thread(
            target=self.download, args=(url, directory, self.stop_event), daemon=False
        )
        self.worker.start()

    def download(self, url, directory, stop_event):
        try:
            with NovelDownloader(
                on_log=lambda message: self.events.put(("log", message)),
                on_progress=lambda progress: self.events.put(("progress", progress)),
                stop_event=stop_event,
            ) as downloader:
                result = downloader.run(url, directory)
        except Exception as error:
            result = DownloadResult("failed", "", 0, None, f"程序运行失败：{error}")
        self.events.put(("done", result))

    def stop(self):
        if self.busy:
            self.stop_event.set()
            self.stop_button.configure(state="disabled")
            self.status.set("正在停止，等待当前请求结束并导出 TXT……")

    def poll_events(self):
        # 每轮限制事件数，下载日志很多时也让出主线程。
        for _ in range(100):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.append_log(value)
            elif kind == "progress":
                if not self.stop_event.is_set():
                    self.status.set(value.book_name or "正在下载")
                self.detail.set(f"已保存 {value.saved_count} 章 · {value.chapter_title}")
            elif kind == "done":
                self.set_busy(False)
                self.output_path = value.output_path
                self.status.set(value.message)
                self.detail.set(f"已保存 {value.saved_count} 章" +
                                (f" · {value.output_path.name}" if value.output_path else ""))
                self.open_text_button.configure(state="normal" if value.output_path else "disabled")
                if self.closing:
                    self.root.destroy()
                    return
        self.root.after(100, self.poll_events)

    def open_path(self, path):
        try:
            if not path.exists():
                raise OSError("路径尚不存在，请先开始下载或选择已有目录。")
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as error:
            messagebox.showerror("无法打开", str(error), parent=self.root)

    def open_directory(self):
        self.open_path(Path(self.directory.get()).expanduser())

    def open_text(self):
        if self.output_path:
            self.open_path(self.output_path)

    def on_close(self):
        if self.busy:
            self.closing = True
            self.stop()
            self.status.set("正在保存并关闭窗口，请稍候……")
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    NovelApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
