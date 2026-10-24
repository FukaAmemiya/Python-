# 双站小说下载器

用于下载话本小说和 SF 轻小说（菠萝包）的文本章节，支持 Tkinter GUI、命令行、SQLite 断点续传和 UTF-8 TXT 导出。需要 **Python 3.10+**；GUI 及窗口测试还需要 Tcl/Tk 和可用的桌面会话。

**新版代码位于 `Python学习代码/`，仓库根目录的 `novel_downloader.py` 是旧版。以下操作均使用子目录中的新版。**

## 安装依赖

获取仓库并进入程序目录：

```sh
git clone https://github.com/FukaAmemiya/Python-.git
cd Python-
cd "Python学习代码"
```

Windows PowerShell：

```powershell
python -m venv .novel_venv
.\.novel_venv\Scripts\python.exe -m pip install -r requirements_novel.txt
```

macOS / Linux：

```sh
python3 -m venv .novel_venv
./.novel_venv/bin/python -m pip install -r requirements_novel.txt
```

依赖为 `requests>=2.32.4,<3` 和 `beautifulsoup4>=4.13.4,<5`；SQLite 使用 Python 标准库。虚拟环境需在本机创建，不能假定克隆仓库后已经存在，也不要跨电脑复制。GUI 所需的 Tkinter/Tcl/Tk 应通过 Python 安装程序或系统软件包安装。

## 启动与使用

以下命令以 Windows PowerShell 为例；macOS / Linux 将 `.\.novel_venv\Scripts\python.exe` 替换为 `./.novel_venv/bin/python`。

### GUI

```powershell
.\.novel_venv\Scripts\python.exe novel_downloader.py
```

Windows 也可在安装依赖后双击 `Python学习代码/启动小说下载器.bat`。它优先使用同目录的 `.novel_venv`，不存在时使用系统 `python`，不会自动安装依赖。

粘贴网址、选择保存目录，再点击“开始 / 继续”。窗口显示已保存章数和活动进度条；由于未获取全书总章数，不显示百分比。

### CLI

```powershell
# 交互输入网址
.\.novel_venv\Scripts\python.exe novel_downloader.py --cli

# 指定起始网址与保存目录；请替换为实际章节网址
.\.novel_venv\Scripts\python.exe novel_downloader.py --url "https://book.sfacg.com/Novel/书籍ID/分卷ID/章节ID/" --output "D:\Novels"

# 查看参数
.\.novel_venv\Scripts\python.exe novel_downloader.py --help
```

`--url` 会直接进入命令行下载，无需同时指定 `--cli`；`--output` 用于 CLI，也可与 `--cli` 组合。GUI 的保存目录在窗口内选择。交互模式在网址提示处输入 `q`、`quit` 或 `exit` 退出。

## 支持的网址

表中的 ID 均应替换为实际数字，网址需包含 `http://` 或 `https://`。

| 站点 / 页面 | 网址格式 | 起点 |
| --- | --- | --- |
| 话本书籍主页 | `https://www.ihuaben.com/book/书籍ID.html` 或 `https://www.ihuaben.com/book/书籍ID` | 页面目录中第一个可识别的章节链接 |
| 话本章节页 | `https://www.ihuaben.com/book/书籍ID/章节ID.html`，也识别 `/书籍ID/章节ID.html`、`/章节ID.html` 路径 | 当前章节 |
| SF 章节页 | `https://book.sfacg.com/Novel/书籍ID/分卷ID/章节ID/` 或 `https://book.sfacg.com/Novel/书籍ID/分卷ID/章节ID.html` | 当前章节 |

话本主页按页面目录顺序选取起点，不按章节 ID 排序；需要明确起点时请粘贴章节页。SF 必须提供具体章节阅读页，不支持从书籍主页或 `MainIndex` 目录页开始。下载从起点沿“下一章”链接继续，不会补下载起点之前的章节。

## 保存位置与续传

默认保存目录是 **`Python学习代码/downloads/`**，与启动命令所在的工作目录无关；也可在 GUI 或 CLI 中另行指定。

| 文件（相对于保存目录） | 用途 |
| --- | --- |
| `话本_书名_任务标识前10位.txt` / `SF轻小说_书名_任务标识前10位.txt` | 按章节顺序导出的 UTF-8 正文；书名会清理非法文件名字符，新任务遇到同名文件会增加编号 |
| `.novel_state/任务标识.sqlite3` | 逐章保存正文与续传位置；任务标识为规范化起始网址的 SHA-256 前 20 位 |

**恢复时使用相同起始网址和相同保存目录**，无需改填停止时的章节网址。查询参数、片段、尾斜杠及 HTTP/HTTPS 差异不影响任务标识；支持的域名别名也会统一。不同起始章节会建立独立任务，不会混合追加。

- 每章正文与下一章地址在同一个 SQLite 事务中提交：提交前中断会重下本章，提交后中断会从下一章继续。
- 停止、下载失败或未发现下一章时，只要已有已保存章节且记录可读，就会尝试原子导出 TXT；尚未保存任何章节时不生成 TXT。
- TXT 丢失或导出失败后，可用相同网址与目录重新运行，从数据库恢复并重新导出，无需重下已保存正文。强制退出时 TXT 可能尚未更新。
- 请保留 `.novel_state`，不要同时运行同一任务。数据库损坏时程序会报错并保留文件，不会自动清空或从头覆盖。
- 旧版 TXT 和 `.progress` 不会自动导入或覆盖；可用指定章节网址建立新任务。

## 停止与恢复

GUI 点击“停止并保存”后，会等待当前网络请求结束或超时，再停止并导出已保存章节；下载中关闭窗口也会先请求停止，等待保存完成后关闭。尚未提交的当前章节留待下次重试。

CLI 下载期间按 `Ctrl+C` 会尝试停止并导出；交互模式随后返回网址提示处，使用 `--url` 时结束本次运行。避免在保存过程中再次中断或强制终止进程。

**“未发现下一章”不等于全书完整。** 请对照网站目录确认。到达该状态的任务再次运行只重新导出已有内容，不检查网站更新；下载新增章节需以新增章节网址建立任务。

## 限制

- 仅处理两站可直接访问的文本阅读页，不提供登录、验证码处理、付费章节解锁或图片章节识别。
- 临时网络错误会退避重试，最多尝试 3 次；明确的 404 等错误直接报告。正文缺失、无效导航等错误不会作为小说正文写入。
- 网站改版可能导致 HTML 选择器失效；离线测试通过不代表真实网站始终可用。

## 离线测试

在 `Python学习代码/` 中运行，测试使用模拟网页和请求，不访问小说网站：

```powershell
# 核心、存储与网络处理测试，不需要桌面
.\.novel_venv\Scripts\python.exe -m unittest -v test_novel_downloader

# 完整测试：窗口测试会创建隐藏窗口，需要 Tcl/Tk 和可用的桌面会话
.\.novel_venv\Scripts\python.exe -m unittest -v test_novel_downloader test_novel_gui
```

## 主要文件

- `Python学习代码/novel_downloader.py`：GUI / CLI 入口。
- `Python学习代码/novel_gui.py`：Tkinter 窗口与后台下载线程。
- `Python学习代码/novel_core.py`：站点解析、链接校验、请求重试与下载流程。
- `Python学习代码/novel_storage.py`：SQLite 状态保存与 TXT 原子导出。

许可证见 [LICENSE](LICENSE)。
