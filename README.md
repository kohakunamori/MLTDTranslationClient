# MLTDTranslationClient — APK 内置汉化源

本仓库只管理 **Client 轴** 的 APK 内置汉化输入。它不管理服务器下发的
Assets，也不保存 `asset_version`、`base_version` 或任何把 Client 与 Assets
拼接在一起的复合版本。

## 仓库边界

- `localization/<client_version>/`：该 APK 版本的可编辑汉化文字、普通图片和
  资源元数据；贡献者提交的是源内容，不是 Unity3D 二进制。
- `manifests/apk-builtin.manifest.json`：Client 版本、输入资源路径、SHA-256
  和审核状态。`provenance.client_version` 是唯一版本轴。
- `manifests/bottom-bar.manifest.json`：底栏翻译源与 Unity 目标定位信息。
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

## 协作流程

1. 普通用户通过 Portal 登录 GitHub；
2. Portal 在用户 fork 中创建 branch 并写入 `localization/<client_version>/`；
3. Portal 向本仓库创建 Pull Request；
4. GitHub Actions 校验 manifest、资源路径和 hash；
5. 维护者在 GitHub 审核并合并；
6. 合并后的 commit 成为私有 APK 构建的唯一 Client 输入。

GitHub PR 是审核权威，Portal 只镜像状态和 diff，不在 D1 中复制一份最终审核
结论。

## 当前状态

当前 `9.0.200` 的底栏源已进入 `localization/9.0.200/`，整体 APK 内置汉化
仍标记为 `unreviewed_candidate`。这意味着它可以参与候选构建，但不能被文档
或 CI 宣称为已完成的稳定设备验收。

本仓库不包含可执行 APK；APK 发布由私有仓库负责，发布前必须同时通过其
arm64 构建、签名、验证和 release gate。
