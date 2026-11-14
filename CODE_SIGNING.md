# Code signing policy / 代码签名政策

**当前状态：v1.1.0 为未签名版本。SignPath Foundation 申请尚需仓库维护者本人提交并通过审核，当前没有已获批的免费签名账户或已签名 EXE。**

**Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).** 这段说明描述的是计划采用的签名服务，**不表示当前版本已经获得签名**。

## 源代码、发布与团队角色

- **项目**：双站小说下载器 (FukaAmemiya) / FukaAmemiya Novel Downloader
- **源代码**：https://github.com/FukaAmemiya/Python-
- **发布与下载**：https://github.com/FukaAmemiya/Python-/releases
- **许可证**：GNU GPL-3.0，源码和构建工作流均公开。
- **Authors / committers**：项目 GitHub 仓库所有者 [FukaAmemiya](https://github.com/FukaAmemiya) 及其明确授权的提交成员。
- **Reviewers**：由仓库维护者审查外部贡献者的 PR，特别是依赖、构建脚本、安全相关修改。
- **Signing approver**：计划由仓库维护者 FukaAmemiya 承担。正式使用时必须在 SignPath 中设置**每个发行版本人工审批**。
- **仓库与 SignPath 账户**：参与代码签名和版本发布的人员必须启用多因素认证 (MFA)。

仓库必须在申请通过后检查/完善 GitHub 分支保护和审查制度。只有被授权的维护者才能批准正式发行，不能用未审查的 PR 直接触发发布签名。

## Privacy policy / 隐私政策

请参阅 [PRIVACY.md](PRIVACY.md)。除用户主动发起的小说下载/更新请求外，应用不向其他联网系统发送用户数据；不包含账号、广告、遥测或后台数据分析。下载内容和 SQLite 续传记录保存在用户指定的本地目录。用户主动下载时，相应小说网站可以看到正常 HTTP 连接信息。

## 签名发布流程

- 普通 Pull Request / main 构建：只进行单元测试、PyInstaller 单文件打包、启动冒烟检查，上传**未签名的预览 artifact**。不会发布新的正式 Release。
- 正式签名：由项目维护者在 **GitHub Actions → Windows EXE build and SignPath Release → Run workflow** 的 **main** 分支填写全新版本号（例如 \`v1.1.1\`）触发。
- GitHub-hosted Windows Runner 生成带 Windows PE 版本元数据的 EXE，并通过 \`actions/upload-artifact@v4\` 创建有来源证明的构建产物。
- 官方 \`signpath/github-action-submit-signing-request@v2\` 通过 artifact ID 提交签名请求，要求 SignPath 校验 GitHub 仓库、构建环境、分支和提交来源；**发行签名需 SignPath 人工审批**。
- 使用 SignPath Foundation 的可信发行证书签名。私钥由签名服务管理，不存在 GitHub 仓库或工作流。
- 工作流下载签名产物，并使用 Windows \`Get-AuthenticodeSignature\` 与 \`SignTool verify /pa /v /tw\` 核验可信证书、发布者及时间戳。
- **所有检查通过才**对最终签名 EXE 计算 SHA-256 并上传正式 Releases。若未配置账号、签名请求被拒、签名或时间戳验证失败，将终止，不会退回发布未签名文件。
- 版本号只用于新的、未使用的 Git tag；不能覆盖 \`v1.1.0\` 的未签名历史发行文件。

注意：代码签名本身不等于安全审计，也不能保证 Windows SmartScreen 不再显示信誉警告。

## SignPath Foundation 申请后如何配置

申请入口：https://signpath.org/apply ，条款：https://signpath.org/terms 。

1. 在申请表填写 Project Name = \`双站小说下载器 (FukaAmemiya)\`，仓库 URL = \`https://github.com/FukaAmemiya/Python-\`，Homepage 同仓库 URL，Download URL = \`https://github.com/FukaAmemiya/Python-/releases\`。若 SignPath 要求英文简介，可介绍本项目为下载话本小说和 SF 轻小说公开文本章节的 Windows 桌面工具，提供断点续传、书架、TXT/EPUB 导出。
2. 签署者身份、项目声誉、开源许可证、现有发行、代码审查和隐私声明由 SignPath Foundation 审核。**该项目较新，申请可能不会被批准；不能声称已经获批。**
3. **审核通过后**，按 SignPath 提供的组织信息登录 SignPath.io。将 GitHub.com 作为 Trusted Build System，并按要求安装 SignPath GitHub App、授权此仓库、为项目启用 Origin Verification。
4. 在 SignPath 项目中建立符合发行条件的签名策略，例如 slug \`release-signing\`：使用 Foundation 发行证书、只允许 GitHub-hosted CI 来自 \`main\`、每次签名需维护者手动批准。不要使用测试证书代替发行证书。
5. 将仓库中的 [SignPath Artifact Configuration XML](.signpath/artifact-configuration.xml) 配置到 SignPath 项目中（例如使用 \`novel-downloader-exe\` 作为配置 slug）。它要求 GitHub Actions 上传的 ZIP 内有单个 \`NovelDownloader-Windows-x64.exe\`，并严格核验 ProductName、FileVersion、ProductVersion、CompanyName 和原文件名。构建脚本 [build_version_info.py](build_version_info.py) 生成 Windows 资源信息，发布时从版本号派生 \`1.1.1.0\` 这样的资源版本。
6. 在 GitHub **Settings → Secrets and variables → Actions** 配置：

   | 类型 | 名称 | 内容 |
   | --- | --- | --- |
   | Secret | \`SIGNPATH_API_TOKEN\` | 仅有项目/策略签名请求权限的 SignPath API token，**切勿公开** |
   | Variable | \`SIGNPATH_ORGANIZATION_ID\` | SignPath Organization ID |
   | Variable | \`SIGNPATH_PROJECT_SLUG\` | SignPath 项目 slug |
   | Variable | \`SIGNPATH_SIGNING_POLICY_SLUG\` | 发行签名策略 slug，如 \`release-signing\` |
   | Variable | \`SIGNPATH_ARTIFACT_CONFIGURATION_SLUG\` | 发行工件配置 slug，如 \`novel-downloader-exe\` |

7. 从 \`main\` 手动触发新的发行（如 \`v1.1.1\`），SignPath 收到申请后在网页批准签名请求。GitHub Actions 会等待有限时间；如果审批超时或未通过，**不会发布任何未签名 EXE**。
8. 验证新版 Windows 文件属性中的 **数字签名**，发布者证书应显示 SignPath Foundation；与 Release 提供的签名后 \`SHA256SUMS.txt\` 一致。

## 如何在 Windows 上验证

\`\`\`powershell
Get-AuthenticodeSignature .\NovelDownloader-Windows-x64.exe |
    Format-List Status,SignerCertificate,TimeStamperCertificate

Get-FileHash .\NovelDownloader-Windows-x64.exe -Algorithm SHA256

# 若 Windows SDK 已安装，也可以使用：
signtool verify /pa /v /tw .\NovelDownloader-Windows-x64.exe
\`\`\`

检查状态应为 \`Valid\`、签名者为 SignPath Foundation，签名时间戳存在。签名后 EXE 字节与旧未签名版本不同，**必须比较对应签名版本发布的 SHA-256**。

## 官方资料

- [SignPath Foundation 申请条件](https://signpath.org/terms)
- [SignPath GitHub Actions / Origin Verification](https://docs.signpath.io/trusted-build-systems/github)
- [SignPath Artifact Configuration](https://docs.signpath.io/artifact-configuration/)
- [SignPath Foundation 免费申请](https://signpath.org/apply)
