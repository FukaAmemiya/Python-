"""窗口离线冒烟测试：隐藏窗口、后台线程、停止和关闭。"""
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import novel_gui
from novel_core import DownloadProgress, DownloadResult


class FakeDownloader:
    entered = threading.Event()
    wait_for_stop = False

    def __init__(self, on_log, on_progress, stop_event):
        self.log, self.progress, self.stop_event = on_log, on_progress, stop_event

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def run(self, url, directory):
        self.entered.set()
        self.log("离线测试日志")
        self.progress(DownloadProgress("测试作品", "第一章", 1))
        if self.wait_for_stop:
            self.stop_event.wait(5)
            return DownloadResult("stopped", "测试作品", 1, None, "已停止")
        return DownloadResult("end_reached", "测试作品", 1, None, "未发现下一章")


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = novel_gui.NovelApp(self.root)
        self.app.url.set("https://book.sfacg.com/Novel/1/1/1")
        FakeDownloader.entered = threading.Event()
        FakeDownloader.wait_for_stop = False
        self.mock = patch.object(novel_gui, "NovelDownloader", FakeDownloader)
        self.mock.start()

    def tearDown(self):
        self.app.stop_event.set()
        if self.app.worker:
            self.app.worker.join(timeout=6)
        self.mock.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def pump_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            if time.monotonic() > deadline:
                self.fail("窗口事件未在限定时间内完成")
            self.root.update()
            time.sleep(0.01)

    def test_success_events_update_ui(self):
        self.app.start()
        self.pump_until(lambda: not self.app.busy)
        self.assertEqual(self.app.status.get(), "未发现下一章")
        self.assertIn("已保存 1 章", self.app.detail.get())
        self.assertIn("离线测试日志", self.app.log_widget.get("1.0", "end"))
        self.assertEqual(str(self.app.start_button["state"]), "normal")

    def test_window_stays_responsive_and_stops_worker(self):
        FakeDownloader.wait_for_stop = True
        self.app.start()
        marker = []
        self.root.after(10, lambda: marker.append(True))
        self.pump_until(lambda: bool(marker) and FakeDownloader.entered.is_set())
        self.assertTrue(self.app.busy)
        self.assertEqual(str(self.app.url_entry["state"]), "disabled")
        self.app.stop()
        self.pump_until(lambda: not self.app.busy)
        self.assertEqual(self.app.status.get(), "已停止")

    def test_close_requests_stop_before_destroying(self):
        FakeDownloader.wait_for_stop = True
        self.app.start()
        self.pump_until(FakeDownloader.entered.is_set)
        self.app.on_close()
        self.assertTrue(self.app.closing)
        self.assertTrue(self.app.stop_event.is_set())
        self.pump_until(lambda: not self.app.busy)


if __name__ == "__main__":
    unittest.main()
