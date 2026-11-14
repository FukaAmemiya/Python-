# Code signing policy / Windows 数字签名政策

## 当前状态

- **v1.1.0 已发布的 Windows EXE 没有 Authenticode 数字签名。**
- GitHub Actions 现在区分两类构建：
  - Push / Pull Request：只构建并测试 **未签名的预览产物**，不会创建 Release；
  - 从 `main` 手动触发带新版本号的正式发布：先完成受信任 Authenticode 签名、RFC 3161 时间戳与 Windows 验证，**全部成功才创建 Release**。
- **配置签名服务前，没有可用的已签名新版本；不能把 GitHub 提供的 SHA-256 校验等同于受信任的 Windows 发布者签名。**
- 仅签署由本仓库正式 GitHub Actions 在 Windows Runner 构建的二进制，不签署用户提交的任意文件或 Pull Request 产物。

## 首选实现：Azure Artifact Signing（原 Trusted Signing）

本仓库使用 [微软官方 Artifact Signing GitHub Action](https://github.com/Azure/artifact-signing-action) 及 [Azure OIDC 登录](https://github.com/Azure/login)，密钥保存在微软管理的 HSM 中，**不需要把 PFX 私钥或 Azure client secret 上传 GitHub**。

> Azure Public Trust 签名服务需要付费 Azure 订阅、身份验证、签名账户和证书配置文件。不同个人/组织及地区的资格要求可能不同，请先以微软当前 [官方要求](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart) 为准。GitHub 工作流无法代替你完成身份验证。

### 需要由仓库管理员完成的准备

1. 在 Azure 中启用 **Artifact Signing**，完成 **Public Trust** 身份验证，创建签名账户与证书配置文件。不要使用仅供企业内部使用的 **Private Trust** 配置文件面向大众发布。
2. 创建 Microsoft Entra 应用注册，给应用授予对应证书配置文件的 **Artifact Signing Certificate Profile Signer** 角色。
3. 在该应用注册中配置 **Federated Credential / GitHub Actions OIDC**：
   - Issuer：`https://token.actions.githubusercontent.com`
   - Organization / repository：`FukaAmemiya/Python-`
   - Entity type：Branch；Branch：`main`
   - Subject 应为：`repo:FukaAmemiya/Python-:ref:refs/heads/main`
   - Audience：`api://AzureADTokenExchange`
   - 只授权正式 `main` 分支；不要允许所有 Pull Request、所有分支调用签名服务。
4. 打开此仓库的 **Settings → Secrets and variables → Actions**：

   **Repository secrets**（来自 Azure 身份/订阅）：

   | 名称 | 内容 |
   | --- | --- |
   | `AZURE_CLIENT_ID` | Entra 应用 Client ID |
   | `AZURE_TENANT_ID` | Azure Tenant ID |
   | `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID |

   **Repository variables**（不包含私钥）：

   | 名称 | 内容 |
   | --- | --- |
   | `AZURE_SIGNING_ENDPOINT` | 与账户区域一致的 HTTPS endpoint，如 `https://weu.codesigning.azure.net` |
   | `AZURE_SIGNING_ACCOUNT` | Artifact Signing 账户名称 |
   | `AZURE_SIGNING_PROFILE` | 通过身份验证的 Public Trust 证书配置文件名称 |

5. 在 GitHub **Actions → Windows EXE build and signed Release → Run workflow** 选择 **main**，填入新的、尚未使用过的版本号，例如 `v1.1.1`。本工作流不会覆盖已有 `v1.1.0`。
6. 发布前自动执行：PyInstaller 打包 → EXE 启动测试 → Azure 证书签名及 SHA-256 时间戳 → `Get-AuthenticodeSignature` 校验 Windows 信任状态、签名证书和时间戳 → `SignTool verify /pa /v /tw` → 计算 **签名后**的 SHA-256 → 上传 Release。
7. 只有所有检查通过时才发布正式 Release。签名服务、凭据、证书链或时间戳出现问题时，工作流会失败，不会退回发布未签名 EXE。

### 如何验证下载的程序

在 Windows PowerShell 中执行：

```powershell
Get-AuthenticodeSignature .\NovelDownloader-Windows-x64.exe |
    Format-List Status,StatusMessage,SignerCertificate,TimeStamperCertificate

Get-FileHash .\NovelDownloader-Windows-x64.exe -Algorithm SHA256
```

签名的 `Status` 应为 `Valid`，签名者与时间戳证书应符合 Release 所述。使用 Windows SDK 还可执行：

```powershell
signtool verify /pa /v /tw .\NovelDownloader-Windows-x64.exe
```

与 Release 中的 `SHA256SUMS.txt` 对比时，使用**最终签名后的文件**，因为签名会改变 EXE 内容。

## 其他可信签名方案

[SignPath Foundation](https://signpath.org/) 提供符合条件的开源项目免费代码签名。项目具有 GPL-3.0 开源许可证，可考虑申请，但必须由维护者提交项目资料并接受审批，**本仓库尚未取得该服务的批准，也没有配置 SignPath 的发布工作流**。若后续选择该方案，可替换本仓库的 Azure 签名步骤。

传统 CA 提供的 OV/EV 证书也可以实现 Authenticode，但通常需要硬件令牌或 HSM，不能简单地把私钥导出到 GitHub Actions。**不要把 PFX、证书私钥、Azure client secret 或令牌提交到仓库、Issue、PR 或聊天记录中。**

## 重要限制

- 数字签名可以证明签名者身份并检测文件篡改，**并不代表软件安全审计通过**。
- 新签名身份仍可能触发 Windows SmartScreen 的信誉提示；没有任何签名工作流能保证首次发布便完全消除警告。
- 旧版 `v1.1.0` 不会因为新工作流而自动被签名；必须有可用的签名身份，并重新发布新版本。
- 维护者应开启多因素认证，限制有权修改签名工作流、Azure 账户和正式 Release 的人员。

参考： [Microsoft SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool) · [Azure Artifact Signing GitHub Actions](https://github.com/Azure/artifact-signing-action) · [微软的 Windows 签名选项](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
