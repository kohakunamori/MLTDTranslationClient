# APK 文字资源自动化

Client 是汉化资源的唯一权威仓库。版本无关的精确原文目录位于
`localization/shared/apk-text-zhcn.json`，复用已有译文后，尚未翻译的行进入现有
LLM provider pool。原文 SHA-256、格式占位符、富文本标签必须通过校验；失败的行
保持待翻译状态，已完成的合法译文仍保存。新增图片翻译禁用。

Private Build 的每日官方 APK 扫描及 `apk-text-discovered` 事件共用此目录。
APK 获取、解包和资源扫描全部在 Private Build；Client 仅导入有界文字清单。
只接受语义已确认且有补丁实现的文字，或者 BI 原文伴随资源。版权行不进入队列。
对象名称、回调、未确认字段、图片以及无法解码的资源继续交给 Agent。

Private 请求固定资产 ID、SHA-256、原始 APK、checkpoint 和 CI 来源。
Client 验证请求来源后导入目录，不会把较旧 APK 设置成当前 Client 版本。
译文同步到当前 component/Android 目录；未来版本 CI 还会按精确 Client 提交
取得共享目录，为目标 APK 重新生成 BI/component/Android 补丁输入。

请求保存在 `manifests/apk-text-requests.json`。满足请求的全部文字通过校验后，
Client 用 `client-candidate-text-updated` 回调原 checkpoint 和精确提交。
每日运行也会恢复未完成请求；Private 按 checkpoint、工具及 Client 提交去重。

Private 构建、签名及隔离 ARM64 Android 冷启动通过后，CN 包发布到 Client，
Local 包发布到 Private Build 的版本候选 Release。候选标签为
`v<版本>-candidate-<适配摘要>`，始终为非 latest 的预发布版。
实机、登录和 LIVE/MV 验收仍是正式版晋级条件。
