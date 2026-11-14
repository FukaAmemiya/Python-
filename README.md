# 双站小说下载器

用于下载话本小说和 SF 轻小说（菠萝包）的公开文本章节，支持 Tkinter GUI、命令行、目录驱动整本下载、SQLite 断点续传以及 UTF-8 TXT / EPUB 3 导出。需要 **Python 3.10+**；GUI 及窗口测试还需要 Tcl/Tk 和可用的桌面会话。

**当前入口为仓库根目录的 `novel_downloader.py`，以下命令均在仓库根目录执行。旧脚本已归档至 [`legacy/`](legacy/README.md)。**

**Windows 用户可以直接下载独立 EXE，完全不需要安装 Python。** 只有需要修改源代码、调试或使用命令行的用户才需要下面的 Python 环境。

## Windows 直接下载 EXE（推荐）

前往 **[Releases 下载页](https://github.com/FukaAmemiya/Python-/releases)**，在最新版本的 Assets 中下载 `NovelDownloader-Windows-x64.exe`，双击即可打开窗口。目标平台为 Windows 10/11 的 64 位系统。

- 使用 PyInstaller 将 Python 运行时、Tkinter 和所需库打包在 EXE 中，接收者无需额外安装任何 Python 依赖。
- Windows EXE 默认保存到 `%LOCALAPPDATA%\\NovelDownloader\\downloads`，可在软件里改为任意已有目录。
- 第一次启动时会解压运行环境，因此可能较慢。程序未进行代码签名，Windows 可能弹出未知发布者的 SmartScreen 提示。请自行从本仓库验证来源及 Release 附带的 SHA-256。
- 无需管理员权限，下载完成后可直接运行，不提供安装向导。
- **升级以前的数据**：保留你原来的 `downloads` 文件夹和内部隐藏的 `.novel_state`；在新版窗口中选择旧目录，书架便会显示既有记录。

## 开发者：从源码运行（需要 Python）

获取仓库并进入程序目录：

```sh
git clone https://github.com/FukaAmemiya/Python-.git
cd Python-
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

使用源码时，Windows 也可在安装依赖后双击 `启动小说下载器.bat`。它优先使用同目录的 `.novel_venv`，不存在时使用系统 `python`，不会自动安装依赖。

粘贴书籍主页、目录或章节网址，选择保存目录和输出格式（TXT、EPUB 或两者），再点击“开始 / 继续”。能够识别完整目录时显示已下载章数/总章数与确定进度；无法识别目录时仍使用活动进度条。

### 下载书架

桌面窗口的 **“我的书架”** 可以在当前保存目录中读取 SQLite 断点续传记录，搜索书名/站点/网址，查看已下载章节数、TXT 和 EPUB 状态。选中一本书后可 **检查更新/继续**，或直接打开导出文件。可选择**移除下载记录**：此操作会删除该书的 SQLite 断点文件，**不会删除 TXT/EPUB 文件**，但不能恢复下载进度。建议操作前先备份 `.novel_state`。

书架扫描仅读取当前选择的保存目录，不访问系统其他用户的小说，不会因打开书架自动发起网络下载。

### 本机 Web UI

不需要安装前端依赖。运行：

```powershell
.\.novel_venv\Scripts\python.exe novel_downloader.py --server
```

然后在浏览器打开 `http://127.0.0.1:18423/`。页面可以粘贴网址、启动/停止下载、查看最近日志，以及下载已经导出的 TXT/EPUB。使用 `--port 18424` 更换本地端口，使用 `--output` 指定保存目录。Web UI **只监听 127.0.0.1**，并校验 Host 和表单 Origin，不面向局域网或公网开放，也没有用户账户、批量任务队列或全站搜索功能。

### CLI

```powershell
# 交互输入网址
.\.novel_venv\Scripts\python.exe novel_downloader.py --cli

# 指定起始网址与保存目录；请替换为实际章节网址
.\.novel_venv\Scripts\python.exe novel_downloader.py --url "https://book.sfacg.com/Novel/书籍ID/分卷ID/章节ID/" --output "D:\Novels"

# 仅生成 EPUB
.\.novel_venv\Scripts\python.exe novel_downloader.py --url "https://www.ihuaben.com/book/书籍ID.html" --format epub

# 同时生成 TXT 和 EPUB（默认）
.\.novel_venv\Scripts\python.exe novel_downloader.py --url "https://www.ihuaben.com/book/书籍ID.html" --format both

# 查看参数
.\.novel_venv\Scripts\python.exe novel_downloader.py --help
```

`--url` 会直接进入命令行下载，无需同时指定 `--cli`；`--output` 用于 CLI，也可与 `--cli` 组合。`--format` 接受 `txt`、`epub`、`both`，默认 `both`。GUI 的保存目录在窗口内选择。交互模式在网址提示处输入 `q`、`quit` 或 `exit` 退出。

## 支持的网址

表中的 ID 均应替换为实际数字，网址需包含 `http://` 或 `https://`。

| 站点 / 页面 | 网址格式 | 起点 |
| --- | --- | --- |
| 话本书籍主页 / 目录 | `https://www.ihuaben.com/book/书籍ID.html` 或 `https://www.ihuaben.com/list/书籍ID.html` | 完整目录中第一章 |
| 话本章节页 | `https://www.ihuaben.com/book/书籍ID/章节ID.html`，也识别 `/书籍ID/章节ID.html`、`/章节ID.html` 路径 | 当前章节 |
| SF 书籍页 / 目录 | `https://book.sfacg.com/Novel/书籍ID/` 或 `https://book.sfacg.com/Novel/书籍ID/MainIndex/` | 目录中第一章 |
| SF 章节页 | `https://book.sfacg.com/Novel/书籍ID/分卷ID/章节ID/` 或 `https://book.sfacg.com/Novel/书籍ID/分卷ID/章节ID.html` | 当前章节 |

两站优先获取章节目录并按网页顺序下载，不按章节 ID 排序；从章节页开始时只下载该章及后续章节。目录不可用时具体章节页退回“下一章”导航；首次使用书籍主页而目录不可用会报错，已有本地记录时仍可离线导出。不会下载付费、需要登录或无法直接访问的章节。

## 保存位置与续传

**源码模式**默认保存目录为仓库根目录下的 `downloads/`。**Windows 独立 EXE**默认保存目录为 `%LOCALAPPDATA%\\NovelDownloader\\downloads`，避免 PyInstaller 临时解压目录重启后丢失数据。两种模式都允许在 GUI 中自行更改保存目录。

| 文件（相对于保存目录） | 用途 |
| --- | --- |
| `话本_书名_任务标识前10位.txt` / `SF轻小说_书名_任务标识前10位.txt` | 按章节顺序导出的 UTF-8 正文；书名会清理非法文件名字符，新任务遇到同名文件会增加编号 |
| `同名.epub` | EPUB 3 电子书，带章节目录；选择 EPUB 或双格式时生成 |
| `.novel_state/任务标识.sqlite3` | 逐章保存正文与续传位置；任务标识为规范化起始网址的 SHA-256 前 20 位 |

**恢复时使用相同起始网址和相同保存目录**，无需改填停止时的章节网址。查询参数、片段、尾斜杠及 HTTP/HTTPS 差异不影响任务标识；支持的域名别名也会统一。不同起始章节会建立独立任务，不会混合追加。

- 每章正文与下一章地址在同一个 SQLite 事务中提交：提交前中断会重下本章，提交后中断会从下一章继续。
- 停止、下载失败或未发现下一章时，只要已有已保存章节且记录可读，就会按所选格式原子导出 TXT / EPUB；尚未保存任何章节时不生成文件。
- TXT 丢失或导出失败后，可用相同网址与目录重新运行，从数据库恢复并重新导出，无需重下已保存正文。强制退出时 TXT 可能尚未更新。
- 请保留 `.novel_state`，不要同时运行同一任务。数据库损坏时程序会报错并保留文件，不会自动清空或从头覆盖。
- 旧版 TXT 和 `.progress` 不会自动导入或覆盖；可用指定章节网址建立新任务。

从旧目录布局升级时，请在 GUI 或 `--output` 中选择原来的 `Python学习代码/downloads/`，或在停止程序后将整个旧 `downloads/`（包括隐藏的 `.novel_state/`）移动到新的仓库根目录。虚拟环境需在新位置重新创建。

## 停止与恢复

GUI 点击“停止并保存”后，会等待当前网络请求结束或超时，再停止并导出已保存章节；下载中关闭窗口也会先请求停止，等待保存完成后关闭。尚未提交的当前章节留待下次重试。

CLI 下载期间按 `Ctrl+C` 会尝试停止并导出；交互模式随后返回网址提示处，使用 `--url` 时结束本次运行。避免在保存过程中再次中断或强制终止进程。

**“未发现下一章”不等于全书完整。** 再次开始任务会重新获取目录：新增在末尾或插入在中间的章节都会自动补抓，并按目录位置重新导出 TXT / EPUB；已保存的正文不重复下载。旧版 SQLite 记录在首次重新打开时自动增加目录排序表，不删除原有正文。如果网站目录暂时打不开，已完成的本地小说仍可导出，但不会误称已检查到最新章节。若目录本身不完整，仍需对照网站核实。

## 已下载小说的更新方式

1. 在开始升级前，先复制整个 `downloads/` 文件夹（特别是其中的 `.novel_state/`）。
2. 更新 GitHub 代码后，保持**原始网址和原保存目录**不变，点击“开始 / 继续”。
3. 程序会检查当前可见的完整目录，只补下尚未保存在 SQLite 中的章节，随后重新生成所选格式的文件。

目录被删除或不再显示的历史章节会保留在数据库里；导出时它们排在当前目录列出的章节之后，日志会显示警告。**不要删除 `.novel_state` 来“重新开始”**，否则无法保留已有断点和离线正文。

## 限制

- 仅处理两站可直接访问的文本阅读页，不提供登录、验证码处理、付费章节解锁或图片章节识别。
- 临时网络错误会退避重试，最多尝试 3 次；明确的 404 等错误直接报告。正文缺失、无效导航等错误不会作为小说正文写入。
- 网站改版可能导致 HTML 选择器失效；离线测试通过不代表真实网站始终可用。
- 不含参考项目番茄小说专属 API、全站搜索、语音合成或可公网部署的 Web UI；本项目仅有本地浏览器界面。请遵守站点规则及作品授权。

## 离线测试

在仓库根目录运行，测试使用模拟网页和请求，不访问小说网站：

```powershell
# 核心、存储与网络处理测试，不需要桌面
.\.novel_venv\Scripts\python.exe -m unittest -v test_novel_downloader

# 完整测试：窗口测试会创建隐藏窗口，需要 Tcl/Tk 和可用的桌面会话
.\.novel_venv\Scripts\python.exe -m unittest -v test_novel_downloader test_novel_web test_novel_library test_novel_gui
```

## Windows EXE 的自动构建与发布

`.github/workflows/windows-release.yml` 在 Windows GitHub Actions Runner 上运行回归测试、PyInstaller `--onefile --windowed` 打包和冻结程序冒烟检查，再上传 EXE 与 SHA-256 到构建产物。**只有合并到 main 的正式提交**才会尝试创建 `v1.1.0` Release；PR 仅测试，不会发布。后续版本必须同步更改工作流的版本标记和 Release notes，避免旧版本的二进制文件被覆盖。

## 主要文件

- `novel_downloader.py`：GUI / CLI 入口。
- `novel_gui.py`：Tkinter 窗口与后台下载线程。
- `novel_core.py`：站点解析、链接校验、请求重试与下载流程。
- `novel_storage.py`：SQLite 状态保存与 TXT 原子导出。
- `novel_epub.py`：不依赖额外库的 EPUB 3 导出。
- `novel_web.py`：仅在本机访问的浏览器界面。\n- `novel_library.py`：下载书架与下载记录的只读索引。

许可证见 [LICENSE](LICENSE)。
