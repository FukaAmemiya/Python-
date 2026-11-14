# Privacy policy / 隐私政策

本软件是开源的本地小说下载工具，不要求用户创建账户，不提供广告、遥测或后台分析服务，也不会主动把小说下载记录上传到开发者服务器。

## 网络请求

只有用户主动输入小说网址并开始下载、检查更新或继续任务时，程序才向相应小说网站请求公开页面。目前支持以下站点：

- https://www.ihuaben.com （话本小说）
- https://book.sfacg.com （SF 轻小说）

访问目标网站时，网站或其网络服务提供商会获得常见 HTTP 连接信息，例如来源 IP、浏览器标识及访问路径。它们各自的隐私政策适用于这些请求。本软件没有能力控制这些网站如何处理访问日志。

本机 Web UI 只监听 `127.0.0.1`；它不负责向外部服务器上传用户输入的数据。用户主动点击链接或更新下载时，将按其操作访问相应站点。

## 本地存储与删除

小说章节、书名、来源网址与断点续传数据保存在用户选择的目录下，包括 `TXT` / `EPUB` 和 `.novel_state` 中的 SQLite 文件。程序不会自动同步这些文件。用户可以在书架中移除下载记录，或手动删除下载目录中的文件；移除断点记录不会删除已导出的 TXT/EPUB。

软件无需安装器，无后台常驻服务或自动更新任务。用户可删除下载的 EXE 以及自行保存的文件完成卸载。

## Third-party components

Windows EXE 使用 Python / Tkinter、requests、Beautiful Soup 和 PyInstaller 及其依赖项打包。本仓库的依赖清单和构建脚本可供公开审查；其他组件的许可与隐私政策由其维护者提供。

## English summary

This application does not transmit user data to other networked systems unless specifically requested by the user operating the application (for example, downloading or checking chapters from a URL they supply). It does not include tracking, analytics, advertising, or accounts. Downloaded book files and SQLite checkpoints are stored locally. Requests to the user-selected novel websites necessarily reveal standard connection information to those sites; their respective privacy policies apply.
