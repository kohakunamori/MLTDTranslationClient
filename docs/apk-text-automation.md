# APK 文字资源自动化

Client 是汉化资源的唯一权威仓库。版本无关的精确原文目录位于
`localization/shared/apk-text-zhcn.json`，复用已有译文后，尚未翻译的行进入现有
LLM provider pool。原文 SHA-256、格式占位符、富文本标签必须通过校验；失败的行
保持待翻译状态，已完成的合法译文仍保存。新增图片翻译禁用。

Client 的临时引擎 checkout 使用现有的纯文字 JSONL/格式校验函数，旧 GTX 入口的
Unity/AES 依赖改为仅在实际处理 bundle 时加载。启动检查无需 APK 解析依赖；
Provider、术语和格式校验的实现不变，资源和译文仍只回写 Client。

引擎检出按发布源码直接消费，不在运行前改写其中任何 Python 文件。
`llm-translate-client.yml` 的导入检查验证 provider、queue 与 quality 的纯文本
闭包，并拒绝意外导入 bundle codec。它与翻译步骤一样，只在待翻译队列非空
时运行；队列为空时显示 skipped，不能作为真实翻译路径已经验收的证据。

Private Build 的每日官方 APK 扫描把
`localization/<版本>/discovery/automatic-text-request.json` 写入 Client 检出并提交到
Client `main`，随后派发 `apk-source-discovered`。APK 获取、解包和资源扫描全部在
Private Build；Client 仅导入有界文字清单。
只接受语义已确认且有补丁实现的文字，或者 BI 原文伴随资源。版权行不进入队列。
对象名称、回调、未确认字段、图片以及无法解码的资源继续交给 Agent。

Private 在 `automatic-text-request.json` 中固定原始 APK（`source_apk_sha256`）与
Client 版本。Client 用 `python -m scripts.apk_text_requests import-local-scan`
校验并导入共享目录，不会把较旧 APK 设置成当前 Client 版本。
译文同步到当前 component/Android 目录；未来版本 CI 还会按精确 Client 提交
取得共享目录，为目标 APK 重新生成 BI/component/Android 补丁输入。

请求不再作为仓库状态保存。Private 每次扫描直接覆盖同目录的清单文件；Client
翻译并提交到 `main` 后，由 `.github/workflows/notify-private-build.yml` 比较该
提交实际送入 APK 的资源，按精确提交派发 `client-resources-updated`；不支持的原生
版本改派 `client-native-recovery-requested`。Private 按内容与提交去重。

Private 构建、签名及隔离 ARM64 Android 冷启动通过后，CN 包发布到 Client。
实机、登录和 LIVE/MV 验收仍是正式版晋级条件。
