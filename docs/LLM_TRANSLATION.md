# Client LLM 翻译 CI

`.github/workflows/llm-translate-client.yml` 与 Assets 使用同一个 provider
pool 和术语表。Client 的翻译源是嵌套 JSON，因此
`scripts/llm_translate_untranslated.py` 会收集 `localization/**/*.json` 中
`zh` 为空的 `ja` 条目，按源文本 SHA-256 调用共享翻译池，再把结果写回原
JSON。

工作流每天定时运行，也可以手动触发。结果写为 `status=pending` 和
`translation_stage=llm_translated`，随后仍需人工审核。当前仓库的 Client 源
只有已经填写的底栏条目；运行时不会翻译 APK 中未提交到仓库的二进制
`data.unity3d` 文本。

工作流从 `MLTDTranslationAssets` 的 `main` 读取 provider 配置、术语表和
翻译引擎，API key 仍只从 Actions secret `MLTD_LLM_API_KEY` 注入。
