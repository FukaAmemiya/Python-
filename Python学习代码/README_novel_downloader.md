# 双站小说下载器

支持话本小说和 SF 轻小说的文本阅读页。需要 Python 3.10 或更新版本，以及包含 Tcl/Tk 的 Python 安装。

## 启动窗口

本项目已经创建独立环境 **.novel_venv**。双击 **启动小说下载器.bat** 即可打开窗口。

也可以在项目目录执行：

~~~powershell
.\.novel_venv\Scripts\python.exe novel_downloader.py
~~~

如果更换电脑，需要重新建立环境（虚拟环境不能直接跨电脑搬运）：

~~~powershell
python -m venv .novel_venv
.\.novel_venv\Scripts\python.exe -m pip install -r requirements_novel.txt
.\.novel_venv\Scripts\python.exe novel_downloader.py
~~~

- 话本：粘贴书籍主页或具体章节页。书籍主页按页面目录的第一项开始；需要指定起点时直接粘贴章节页。
- SF：粘贴具体章节阅读页，网址路径通常是 /Novel/书籍ID/分卷ID/章节ID/。
- 选择目录后点击“开始 / 继续”。
- 点击“停止并保存”会在当前请求结束或超时后停止，保留记录并导出已有章节。
- 关闭下载中的窗口也会先请求停止和保存，不强制终止工作线程。
- 由于没有取得全书目录总数，窗口显示已保存章数和活动进度条，不显示百分比。

## 续传与文件保护

默认保存到项目下的 **downloads**：

- **书名_任务标识.txt**：停止、失败或未发现下一章时导出的正文。
- **.novel_state/任务标识.sqlite3**：每章立即保存的正文及续传位置。

**相同起始网址和相同保存目录会恢复同一个任务。** 网址中的查询参数、片段和尾斜杠不影响任务标识；不同起始章节视为不同任务，不会混合追加。

正文和下一章地址在一个 SQLite 事务中保存。中断发生在提交前会重新下载本章；发生在提交后会从下一章继续。TXT 丢失时可以从记录重新导出，不必重下已有正文。强制退出后 TXT 可能还没更新，下次运行会根据记录恢复。

请保留 **.novel_state** 文件夹。数据库损坏时程序会报错并保留文件，不会把损坏记录当成“从头下载”。

旧脚本生成的 TXT、.progress 文件不会自动导入或覆盖；旧进度没有可靠的章节身份，直接拼接可能重复或漏章。新版本会建立自己的记录，可以从你选定的章节页开始下载。

未发现“下一章”只表示页面上没有可用的后续链接，不能证明全书完整。已到达该状态的任务再次运行会直接重新导出已有内容，不检查网站更新；需要下载新增章节时，请以新增章节网址建立任务。

## 命令行

~~~powershell
.\.novel_venv\Scripts\python.exe novel_downloader.py --cli
.\.novel_venv\Scripts\python.exe novel_downloader.py --url "具体章节网址" --output "D:\Novels"
~~~

## 代码结构

- **novel_downloader.py**：窗口/命令行入口。
- **novel_gui.py**：Tkinter 窗口，使用后台线程与队列传递进度。
- **novel_core.py**：站点适配、链接校验、请求重试和下载流程。
- **novel_storage.py**：SQLite 记录及原子导出 TXT。
- **novel_downloader.py.bak**：改动前的原始脚本。

网络、正文缺失和导航异常不会作为小说正文写入。可重试的临时网络错误会退避重试；明确的 404 等错误直接报告。程序不提供登录、验证码、付费或图片章节处理。

## 离线测试

~~~powershell
.\.novel_venv\Scripts\python.exe -m unittest -v test_novel_downloader test_novel_gui
~~~

测试模拟网页和请求；窗口测试创建隐藏窗口，需要可用的桌面会话。真实网站改版后，可能仍需更新对应适配器的 HTML 选择器。
