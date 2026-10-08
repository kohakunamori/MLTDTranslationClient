# 官方 APK → Client 翻译 → Private Build → Release

`llm-translate-client.yml` 每日 02:27 UTC（日本时间 11:27）运行，也可手动触发。
它获取 Hotplay 目录返回的最新 MLTD base APK 和 arm64 split，验证官方发布者
证书及 APK 身份，从内置 `data.unity3d` 导出 runtime `BI_jp.gtx`，自动翻译，
提交源内容后直接通知 Private Build，构建通过后由 Private Build 发布本仓库 Release。

## 数据与复用

`localization/<client_version>/runtime-bi-zhcn.json` 保存官方 APK/Unity entry 的
SHA-256、TextAsset 身份和有序记录。每条记录包含 `record_index`、`key`、
`ja`、`source_sha256`、`zh`、`translatable` 和 `status`。重复 key 不合并。
非文本值和 `title_02` 法律署名标记为 `passthrough`，不送给 LLM。

原文未变的已接受译文优先保留；跨版本复用要求原文完全相同且没有冲突。
LLM 队列按原文 SHA-256 去重，回写时更新所有对应空项。占位符、富文本、
控制符必须保持，`|`、`^` 和 NUL 不得进入译文。回写后刷新 manifest 的 hash/字节数。

翻译引擎及术语表来自 `MLTDTranslationAssets` 的 `main`。正常翻译结果是
`accepted + translation_stage=llm_translated`，直接进入构建。Private Build
只读取指定 Client commit，将记录与构建使用的官方 APK 逐项核对后生成 BI，
重载检查目标明文和非目标 Unity 对象。构建不会继续使用输入包中的旧 BI 译文。

## Secrets 与权限

本仓库沿用两个已有 Actions secrets：

- `MLTD_LLM_API_KEY`：共享 provider pool 的 API key。
- `PRIVATE_BUILD_DISPATCH_TOKEN`：需要 Private Build 仓库的 Contents 读取与
  repository dispatch 写入能力，用于读取私有 APK 工具和通知构建。

工作流用本仓库的 `GITHUB_TOKEN` 提交源内容。由于该 token 的 push 不会触发
另一个 push 工作流，翻译工作流成功提交后显式发送 `client-resources-updated`，
载荷包含 Client commit、版本及官方 base/split SHA-256。通知失败时重新运行
即使没有源文件变化也会重发，Private Build 的现有 poller 负责重复构建去重。
参见 [GitHub token 的触发规则](https://docs.github.com/en/actions/concepts/security/github_token)。

Private Build 保持自己的签名与输入包 secrets，并用其已有 Client Release App
向 `MLTDTranslationClient` 写入 APK Release；本仓库无需拥有签名密钥。

## 手动运行与失败

- 默认运行处理完整队列。`max_items` 可限制处理量；只要当前 BI 仍有空项，
  本次不会通知构建，后续运行继续翻译。队列仍有空项时工作流报告失败。
- `smoke_test=true` 只发送一条合成文本检查 provider，不获取 APK、不改源、不触发构建。
- 未支持的 native 版本：仍保存提取和翻译源，报告失败；需要 Private Build 增加
  对应版本的原生适配与输入包，然后重新运行。不会退回旧版本 APK。
- 下载、官方证书、GTX 格式、源 hash、占位符或构建验证失败都会停止发布。
- `client-translation-report-*` artifact 保存翻译摘要、失败条目和 APK source state；
  不包含 APK、私有工具源码或密钥。

自动提取范围是 runtime BI。底栏沿用已入库图像源并检查目标图集和 Sprite，
任意新增图片文字不自动 OCR/重绘，服务器下发 Assets 仍走独立仓库。
“最新”仅指 Hotplay 当前返回版本，没有独立核对 Google Play。
