# MLTD 简体中文汉化

这是《偶像大师 百万现场 剧场时光》（MLTD）的个人汉化项目，持续完善游戏界面、字体及图片中的中文内容。

## 下载与安装

请前往 [发布页面](https://github.com/kohakunamori/MLTDTranslationClient/releases) 下载汉化版。

同一次发布中的 `base.apk` 和 `split_config.arm64_v8a.apk` 必须一起下载，使用支持分包安装的工具（例如 [SAI](https://github.com/Aefyr/SAI/releases)）选择两个文件一起安装。请使用兼容的 64 位 Android 设备，更新时也请使用同一次发布的两个文件。

汉化仍在持续完善，部分内容可能存在遗漏或显示问题。各版本的使用说明请以发布页面为准。

配套资源见 [MLTDTranslationAssets](https://github.com/kohakunamori/MLTDTranslationAssets)，汉化内容可在 [查阅站](https://mltd-portal.nyaneko.cn) 浏览。

## 默认画质（9.0.300）

公共汉化客户端保持 **原版 1080p/60 FPS 配置**：自动构建不包含任何 `quality-fps` 原生补丁，游戏画质、帧率及 MSAA 参数由官方客户端原始设置控制。这不是对全场景强制锁定 1080p 或 60 FPS。

另行提供的本地服（`.local`）候选版本由 [MLTDModifiedAPK](https://github.com/kohakunamori/MLTDModifiedAPK) 构建，默认使用 `4k-120`（2160 高度、LIVE/MV 120 FPS 请求）；该候选包含共享 High 渲染高度修改，**不属于本仓库公开汉化版**，其真实稳定帧率仍需设备验收。

## 贡献

如果发现游戏里还有没汉化的地方，或者某处中文读起来不对，请在
[Issues](https://github.com/kohakunamori/MLTDTranslationClient/issues) 提出。
为方便定位，请尽量附上以下信息：

- **截图**：包含没汉化部分的画面，尽量让整个界面都能看清
- **位置**：在哪个界面、怎么进入，例如「主页 → 菜单 → 设置」
- **版本**：汉化包的版本号，例如 v9.0.300
- **原文与建议译文**（可选）：日文原文，以及你认为合适的中文

同一个界面里的多处问题写在一个 Issue 里就好，不必逐条提交。
不确定怎么描述位置时，截图是最有用的信息。
提交前请遮盖截图中的玩家/账号 ID、设备标识、通知内容和网络配置；不要附上令牌、密码、存档或个人联系方式。

代码层面的改动暂未开放，欢迎先以 Issue 形式反馈。

## 隐私与非公开信息

本仓库公开可见。请勿在代码、文档、Issue、PR、截图、日志或构建产物中提交自己或他人的个人联系方式、账号/玩家或设备标识、访问令牌、密码、私钥、Cookie、Authorization 请求头或用户数据。也不要公开非公开的 VPS/服务器地址、内网地址、管理端口、SSH/代理配置、本机用户名和真实部署目录。示例请使用占位符；真实配置放在 Git 忽略的本地文件或 CI Secrets，示例配置只放假值。业务需要的公开服务域名可以保留。

提交前请检查 `git diff --cached`。发现凭证已经公开时，先撤销或轮换，再通过私下渠道告知维护者；不要把敏感值贴在公开 Issue 中。
