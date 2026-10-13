# APK 内置界面文字补齐

`localization/9.0.300/component-text-zhcn.json` 收录在 9.0.100、9.0.300 实际
APK 中发现的组件文字。1,730 条精确源文已有简体中文译文，另有 23 条 Android
系统提示译文；78 条版权署名、开发调试和排版样例保留原文。原有 585 条 BI
汉化和 7 项底栏资源继续使用。

新版增加的 9 条文字包括演员角色、造型选择、兑换确认、备注、公演信息、
公演名称、连续工作、举办地点、举办时间，均已纳入译文。

构建工具仅修改已验证的显示字段：Unity UI.Text.m_Text、Imas.DLText 继承的
m_Text、原生 TextMesh.m_Text、PictgraphText.mText、InputField.m_Text 和 IGP 加载失败提示。TextKey、
回调参数、对象名及其他字节保持原样。Android 提示保留格式化参数和资源索引。
按源文摘要与精确文本复用译文，不要求源 APK 与资源目录版本相同。

Private Build 清点官方 APK 后自动推入 `localization/<version>/discovery/`：
已验证显示字段的新文字进入 `component-untranslated.jsonl`；未确认语义的字段
和图片另列待检查清单。可自动补丁的新文字由 Client 翻译并回调构建；这些译文
未完成前不发布候选。未确认字段继续保留原文并报告，不计为汉化完成。
具体闭环见 [文字自动化](apk-text-automation.md)。新增图片翻译禁用。

译文完整性、文件摘要、富文本及格式化参数由仓库验证与构建验证检查。
组件写入须重读 Unity 数据，确认对象总数、所有未修改对象以及每个字段前后
字节保持一致。文本资源通过静态验证不代表所有游戏画面已经完成运行验收。
