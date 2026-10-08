# MLTDTranslationClient — APK 内置汉化源

本仓库只管理 **Client 轴** 的 APK 内置汉化输入。它不管理服务器下发的
Assets，也不保存 `asset_version`、`base_version` 或任何把 Client 与 Assets
拼接在一起的复合版本。

## 仓库边界

- `localization/<client_version>/`：该 APK 版本的可编辑汉化文字、普通图片和
  资源元数据；提交的是源内容，不是 Unity3D 二进制。
- `manifests/apk-builtin.manifest.json`：Client 版本、输入资源路径和 SHA-256。
  `provenance.client_version` 是唯一版本轴。
- `manifests/bottom-bar.manifest.json`：底栏翻译源、Unity 目标定位信息，以及
  `localization/9.0.200/visuals/` 中按**原生 946×76** 条带保存的 OFF/ON 图像源
  （`segment_x = [0,138,272,406,540,674,808,946]`，槽宽 138/134，7 槽共 946）。
  原生尺寸让生成器每槽的 `crop → resize(rect)` 退化为恒等操作，像素零重采样。
  这两份图像源优先于字体重绘，避免生成器改变底栏长宽比或在不同颜色状态下
  引入不连续的底色。
- `schema/` 与 `scripts/validate_repo.py`：提交门禁。

官方基线 APK、字体、密钥等私有输入不进入此仓库。CI 在私有构建仓库中读取
本仓库某个明确 commit 的汉化源，然后生成最终 APK 内置 Unity3D 内容；APK
通过私有构建流水线发布到本仓库的 GitHub Release。生成物与源输入的版本边界
分别由 `client_version`、`source_commit`、`translation_commit` 和构建报告记录。

## 版本与复用

同一套汉化内容可以被多个 Client 版本复用，但必须在目标版本的 manifest 中
重新声明并通过 CI 校验。Assets 仓库的复用规则（`exact`、
`verified-compatible`、`suggested`、`blocked`）不在本仓库复制；APK 构建也
不会读取 Assets manifest、NAS 或 R2。

## 变更流程

本仓库**不接受外部贡献**，只有维护者直接提交，没有 fork、Portal 提交和
Pull Request 环节：

1. 维护者在本地修改 `localization/<client_version>/`、`manifests/` 或
   `schema/`；
2. push 到 `main` 触发 `.github/workflows/validate-client.yml`：校验 manifest、
   资源路径和 hash，并允许 `scripts/build_portal_resource_manifest.py` 刷新
   `manifests/portal-resource-manifest.json`；
3. push 到 `main` 的 commit 就是私有 APK 构建的唯一 Client 输入。

维护者直推 `main`，因此没有「合并前审核」这道关卡：`scripts/validate_repo.py`
必须在本地跑过，`main` 上的每个 commit 都是可直接构建的输入。

## LLM 翻译 CI

`.github/workflows/llm-translate-client.yml` 每日运行，也支持手动触发。它
复用 Assets 仓库的 provider pool 和术语表，自动处理
`localization/**/*.json` 中 `zh` 为空的 `ja` 条目；结果写为
`accepted + translation_stage=llm_translated`，翻译结果直接进入构建。当前
Client 仓库没有未翻译的 JSON 条目，因此手动运行只执行校验，
不会调用 provider。APK 中
未提交到仓库的 `data.unity3d` 二进制文本不在此 CI 的输入范围内。

LLM 提交到 `main` 后，`notify-private-build.yml` 会把同一个 commit SHA 发送给
私有 APK 构建仓库，自动开始 Client 构建。

## 当前状态

当前 `9.0.200` 的底栏源已进入 `localization/9.0.200/`，经维护者人工验收后直接
发布。仓库只保留机械校验（路径、hash、字节数、图像几何），不再记录审核状态：
验收由人眼完成，不写进 manifest，也没有 `unreviewed_candidate` 之类的中间态。

本仓库不包含可执行 APK；APK 发布由私有仓库负责，发布前必须同时通过其
arm64 构建、签名、验证和 release gate。
