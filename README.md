# MLTD 客户端内置汉化资源库 (THE IDOLM@STER MILLION LIVE! THEATER DAYS Client Built-in Localization)

本仓库承载**只能随 APK 下发**的汉化面：它们被烘焙进 APK 内的
`assets/bin/Data/data.unity3d`，assets 服务器（`/cn/<asset>/` overlay）不会也不路由器。

文本译文与贴图等经服务器下发的面，由配套仓库
[MLTDTranslationAssets](https://github.com/kohakunamori/MLTDTranslationAssets) 维护。

> 状态：`manifests/apk-builtin.manifest.json` 的 `provenance.artifact_status`
> 记录每个被打包面的验收状态（当前为 `unreviewed_candidate`，即未人工审校的候选）。
> 本仓库只做元数据索引，不携带任何二进制。

## 目录结构

- `manifests/bottom-bar.manifest.json`：底栏 7 个标签的日/中对照与图集坐标
  （`sharedassets1.assets` path_id 4 / `theater_system_footer_main` 512×512）。
- `manifests/apk-builtin.manifest.json`：APK 内置面总索引——底栏图集、运行时 BI 文案表
  （`BI_jp.gtx`）与 CJK 字体对象，各带 SHA-256 与来源验证报告。
- `manifests/asset-version.json`：**APK 实际构建所用**的客户端 + 资源 cohort
  （由 APK 构建流水线回写，本仓库不跟随上游资源版本）。
- `schema/apk-builtin.schema.json`：上述索引的 JSON Schema。

## 版本分支与标签

`main` 与 `manifests/asset-version.json` 由 APK 构建流水线推进，**不做上游版本跟随**；
每条用于构建 APK 的 cohort 另以两个 ref 冻结：

- 标签 `assets-<资源版本>`（如 `assets-1077100`）。
- 分支 `release/<客户端版本>+<资源版本>`（如 `release/9.0.200+1077100`）。

## 为什么单独成库

底栏标签是图集里的**像素**（`Texture2D` atlas），BI 文案是 `data.unity3d` 内的加密
`TextAsset`，字体是同文件内的 Font 对象——三者都不能通过文本 overlay 替换。它们与文本
译文的生产方、验收门槛与发布通道完全不同，因此各自独立成库，避免一方的版本冻结或
CI 规则误伤另一方。

## 许可证与致谢

游戏原始文本、角色、图片、字体与音频著作权均归 Bandai Namco Entertainment Inc. 所有。
汉化成果遵循 [CC-BY-NC-SA 4.0](LICENSE)。
