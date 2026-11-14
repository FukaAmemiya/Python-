# 双站小说下载器 v1.1.0 — Windows 独立版

## 下载安装

在下方 **Assets** 下载 `NovelDownloader-Windows-x64.exe`，保存后双击运行。

- **无需安装 Python、pip、Tkinter 或其他 Python 依赖**：程序使用 PyInstaller 打包，目标平台为 Windows 10/11 x64。
- 首次打开速度可能比后续稍慢；Windows Defender/SmartScreen 可能提示未签名的新发布程序，请自行核验仓库源码与发布的 SHA-256。
- 小说默认保存到当前用户的 `%LOCALAPPDATA%\NovelDownloader\downloads`，也可以在窗口中自行选择目录。
- 该版本不附加安装器，不写入系统注册表，不需要管理员权限。
- 请遵守小说站点的使用规则；不支持绕过登录、付费和验证码。

## 新增：我的书架

- 从保存目录下的 `.novel_state` 读取已有 SQLite 下载记录
- 按书名、网站、网址搜索
- 查看章数和 TXT/EPUB 是否已导出
- 点击书籍继续下载或检查更新，直接打开已有 TXT/EPUB
- 手动移除下载记录（**只移除 SQLite 断点文件，不删除已有导出小说**）

## 已有数据迁移

如果你以前使用源码版本，**先备份整个旧 `downloads` 文件夹**，特别是隐藏的 `.novel_state` 文件夹。独立 EXE 可以在保存目录输入框里选择旧目录，书架会识别原来的书籍，不要求重新下载。

## 更新内容

保留原有话本小说和 SF 轻小说的目录下载、断点续传、插章补全、TXT + EPUB 导出、GUI 和本机 Web UI 核心。新添 Windows 独立打包、书架管理和跨平台自动化检查。

**文件完整性：** 另附 `SHA256SUMS.txt`，记录 Windows EXE 的 SHA-256 摘要。
