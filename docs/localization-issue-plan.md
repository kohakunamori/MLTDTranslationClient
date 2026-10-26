# 汉化缺口上报与记录规划

状态：待评审。本文件只描述方案，不改变任何现有构建行为。

归档说明（2026-10-15）：本轮将既有同事草案纳入版本管理。下文统计与现场描述是先前调查快照（约 2026-10-12），不是当前覆盖率或本轮验收结论；引用数据需在实施前重新核对。Issue 表单、账本脚本、标签/看板和发版联动均是待评审建议，本次没有实施，也没有创建 Issue 或调用外部服务。现有维护者 PAT 单行编辑、同源中继与浏览器直连退路仍然保留。

## 一句话

用 Issue 当"上报口"，用仓库里的一份清单当"账本"：玩家在 Issue 里说哪里还是日文，
维护者把每一条落成账本里的一行，修好、发版、再关掉 Issue。
Issue 负责收，账本负责记，两者缺一不可。

## 一、先看清现状：为什么"进度 100%"却"看起来没汉化"

三个仓库各自都对外报"几乎做完"，但玩家看到的现象和这些数字对不上。
原因是每个数字只统计了**它已经登记过的那部分内容**。

查阅站线上此刻显示的是 99.98%：409,350 条里 6 条未译、94 条待确认、1,258 条无需翻译。
这个百分比是按**文字**算的，图片和字体不在里面。

| 账本上的说法 | 数字 | 现实 |
| --- | --- | --- |
| Client 仓库：底栏 + APK 内置文本 | 592 / 592（100%） | 只覆盖 7 个底栏格 + 632 条内置文本（其中可译 585 条）。APK 里的图片类界面完全没进这个统计；构建时其实还改了应用名，但这一项根本没登记 |
| Assets 仓库：文本 | 395,673 条里 99 条待处理（99.97%） | 这一项确实基本做完了 |
| Assets 仓库：歌词 | 491 首、13,729 个歌词位，已采纳 12,465，真正待翻 **6** 个 | 歌词是单独统计的，不在上面那个 395,673 里。**这里有个坑**：源文件里有 1,263 行标着"未翻译"，但其中 1,257 行的原文是英文歌词（如 "Show goes on"），压根不需要翻。直接按状态字段数会虚报 200 倍 |
| 图片：937 张 UI 图 | 清单里 937 张全部"已本地化" | 整套图片覆盖层其实已经做好了（231 个资源包、1,228 张贴图、541 MB），但状态是 `staged_not_published`——备好了却没发布。而且只跟到资源版本 1077741，游戏已经更新到 1077750 |
| 非 GTX 的 APK 文字 | 无任何登记 | 烘在界面里的文字、系统层面的日文串，从来没进过生产流程（详见下一节） |

结论：**真正让玩家觉得"没汉化"的，主要不是"还没翻译"，而是"翻译好了却没下发"，以及"从来没被任何清单登记过"的内容。**
后一类只能靠玩家上报才能发现——这正是 Issue 通道的价值。

### 一个已经确认的实例

仓库里留着一张真机截图 `local-data/device-shot-after-fix.png`（底栏修复后的验收截图）。
画面里的剧情标题和正文都已经变成中文，但右下角仍然是英文的 **"Now Loading…"**。

在客户端的内置文本清单里搜"loading / ローディング / 読込"，**一条都没有**。
也就是说：这个玩家一眼就能看到的文字，既不在 592 条统计里，也不在任何清单里，
更不会有人去翻译它。这类东西有多少，目前没人知道——只能靠上报一条条收集。

原因也查到了：构建工具里备着三份"只看不改"的排查脚本，分工正好覆盖这类东西——
一份找烘在 APK 界面里的文字，一份找 Unity 之外的文本文件，一份找系统层面的日文串。
但它们的产物被明确标成"不允许回写""日文筛查尚未开始""已复核图片 0 张"。
翻译成大白话：**探测工具造好了，从来没真正跑完，也没接进生产流程。**
所以"Now Loading…"这类文字目前处于"没人负责"的状态。

## 二、方案：三层

先说一句历史：查阅站当初做过一整套社区投稿功能——玩家用 GitHub 登录，
在网页上直接提交改动。这套东西在一比一的真实环境里联调通过了，
随后在 2026-10-12 被整体删除，改成了纯静态站点，后台数据表也清空了。
所以现在改走 Issue 这条路，是**延续当时的简化方向**，不是另起炉灶，
也不需要再把登录和后台建回来。

### 第一层 入口 —— 三个上报表单

放 3 个表单在 Client 仓库（发布页所在、玩家最可能找到的地方），
而不是让玩家去猜该报哪个仓库。表单（Issue Forms）能强制要求填关键信息，
普通 Issue 做不到这一点，收到的多半是无法处理的"这里还是日文"。

| 表单 | 什么时候用 | 必填项 |
| --- | --- | --- |
| 还没汉化（仍是日文/英文） | 漏译、图片没换、整块没做 | 版本号、位置、截图 |
| 翻译不对 | 中文看不懂、术语不一致、读起来别扭 | 版本号、位置、现在的中文、期望的中文、截图 |
| 显示异常 | 方块、缺字、重叠、溢出、错位 | 版本号、位置、截图、异常表现类型 |

表单里"属于哪一类"这个选项清单要包含**歌词**，否则歌词问题会被当成普通文本，
而它的处理流程和存放位置都不一样（在 Assets 仓库，且要先把"英文原词"和"漏翻"分开）。

配套 `.github/ISSUE_TEMPLATE/config.yml`：

- `blank_issues_enabled: false`，强制走表单，保证每条上报都带版本号和截图。
- 加一个链接指向查阅站（https://mltd-portal.nyaneko.cn ），提示"先搜一下是否已经有人报过"。

表单落到 `labels:` 上的默认标签直接驱动后面的分流，不需要人工再判断。
截图走 GitHub 自带的图片上传，图存在 GitHub 的图床上，不占仓库体积。

查阅站已经有"只看未翻译"的筛选和独立的图片浏览页，可以直接当作
"报之前先看一眼"的地方，不必再单独做一个查询页面。

### 第二层 账本 —— 仓库里的一份清单

新增 `manifests/localization-backlog.json`（放 `manifests/`，**不要**放 `localization/`，
原因见附录 C 的第 3 条）。每一条记录一件事：

```
id / 状态 / 影响范围 / 发现版本 / 修复版本 / 界面位置
日文原文 / 当前中文 / 期望中文 / 关联的 issue 编号 / 证据 / 备注
```

状态流转：`上报 → 已确认 → 处理中 → 已修复 → 已发版`，
另有 `不处理`（版权、风格取舍、技术上做不到）和 `重复`（合并到已有条目）。

为什么不能只靠 Issue：

1. Issue 的作者可以改标题、删内容，记录会失真；仓库文件不会。
2. Issue 关掉之后就沉底了，半年后没人知道当时为什么这么定。
3. 仓库文件能跟着版本走，能进发布说明，能被自动检查，也能直接生成"还剩多少"。
4. 这正是"个人记录"该待的地方——Issue 是别人写给你的便条，账本是你的工作台账。

配套加一个脚本 `scripts/localization_backlog.py`，四个动作：

- `validate`：检查清单格式、编号不重复、状态和字段互相自洽（例如"已发版"必须填修复版本）。
- `coverage`：按范围算出"还剩多少"，并能报告"哪些范围根本没纳入统计"。
- `report`：输出一段 Markdown 表格，用于置顶说明 Issue 和发布说明。
- `list`：从账本生成待办列表（供本地查看，不联网）。

在 `validate-client.yml` 里加一步跑 `validate`，防止手改把清单改坏。
`tests/` 下补一个对应的测试文件，和现有测试风格保持一致。

### 第三层 闭环 —— 标签、里程碑、看板、发版联动

- **标签**：见附录 A。用 `类型/` `范围/` `状态/` `来源/` 四个前缀分组。
  其中 `来源/社区` 与 `来源/自查` 的区分直接满足"社区贡献"和"个人记录"两个诉求，
  在 Issue 列表里按标签一筛就分开了。
- **里程碑**：一个客户端版本一个里程碑（如 9.0.300、9.0.310）。
  做到"这个版本收了哪些上报、修了哪些"一目了然。
- **看板**：GitHub Projects 建三个视图——待确认 / 我的待办 / 等待发版。
- **转移规则**：剧情、卡面、歌词类问题属于 Assets 仓库，用 `gh issue transfer` 转过去。
  Client 仓库保持"唯一入口"，玩家不用关心仓库划分。注意转移会丢掉标签，先看后转。
- **发版联动**：发版时把该里程碑下状态为"已修复待发版"的 Issue
  自动评论"已在 x.y.z 修复"、打上 `状态/已发版`、关闭并同步账本。
- **流水线自报**：像 Assets 仓库那样（issue #39，作者 github-actions），
  翻译或构建失败时自动开一条带 `来源/CI` 标签的 Issue。
  这类记录不用等玩家反馈，是纯"个人记录"用途。
  现成做法可照抄：`MLTDTranslationAssets/.github/workflows/llm-translate-assets.yml`
  里名叫 `Report a real failure as a tracking issue` 的那一步——先按标题搜有没有还开着的同类
  Issue，有就追加评论，没有才新建；同时要给工作流加 `issues: write` 权限。

## 三、顺带要纠正的一件事：把覆盖度口径说清楚

查阅站现在按分类汇总显示进度（Client 那个分类的 `progress_percent` 是 100），
而图片只出现在"图片"浏览页里，不参与进度计算。对外只说 100%，玩家一进游戏看到日文图片
就会来质疑，反而把愿意帮忙的人也赶走。建议改成
"已登记范围 100%，另有若干类内容尚未纳入统计"。

做法：给 Client 的 `portal_manifest.py` 输出增加一个 `coverage_scope` 段，
列出"已统计"和"未统计"两类，未统计的至少包含：

- APK 图片类界面（未建模，没有条目级清单）
- 字体是否缺字（只有二进制，没有条目级统计）
- 从未被任何清单登记的内容（数量未知，只能靠上报发现）

查阅站这一点做得对：歌词已经单独列成一行了（13,729 个位置，6 个待翻），
和文本分开统计。真正的问题不在歌词，而在下面这三类**从来没有被单独列出来**的东西。

注意：`schema/apk-builtin.schema.json` 根节点是 `additionalProperties: false`，
新增字段必须同时改 schema，否则校验会失败。

## 四、分阶段执行清单

| 阶段 | 内容 | 工作量 | 验收 |
| --- | --- | --- | --- |
| 第 0 步 | 3 个表单 + config + 标签 + README「贡献」一节改写 + 一条置顶说明 Issue | 约 30 分钟，零代码 | 随便点"新建 Issue"能看到 3 个表单、必填项生效、标签自动打上 |
| 第 1 步 | 账本文件 + 格式定义 + `localization_backlog.py` + CI 校验一步 + 测试 + 一份 docs 说明 | 约 2 小时 | `python -m scripts.validate_repo` 通过；故意改坏账本会被拦下 |
| 第 2 步 | 覆盖度口径纠正（manifest + schema + `portal_manifest.py`），查阅站显示范围说明 | 约 1～2 小时 | 查阅站不再单纯显示 100%，能看到"未纳入统计"的说明 |
| 第 3 步 | 里程碑 + Projects 看板 + 发版自动关单 + `gh issue transfer` 转移规则 | 约 1 小时 | 发版后对应 Issue 自动收到评论并关闭 |
| 第 4 步 | 与 Issue 无关但收益最大，分两件：①把已经备好的图片覆盖层推出去（它卡在"同名地址可能命中旧缓存"这个待确认问题上，不是卡在没做完）；②重新打开图片生成流水线，否则图片会停在 1077741 这一版跟不上游戏更新 | ①要先在隔离测试机上确认缓存行为；②要先选图像模型供应商 | 游戏内图片类界面变中文 |

第 0 步可以立刻做，做完当天就能开始收上报。第 1 步是让上报"不白收"的关键，
建议紧跟着做。第 2、3 步可以等上报量上来再说。

## 五、风险与不做的事

- **公开仓库的 Issue 无法设为私有**。所以"个人记录"不能靠"悄悄记在 Issue 里"，
  只能靠标签区分，真正的长期记录在账本文件里。
- **不收 Pull Request** 是这个仓库现有的明确决定（`validate-client.yml` 里的注释写了
  "External pull requests are no longer accepted"）。因此社区贡献的形式是
  "上报 + 建议译文"，不直接改文件。要不要开一条只允许改某个特定文件的 PR 通道，
  是另一个需要单独决定的问题。
- **重复上报**是必然的。规则：同一界面同一类问题合并成账本里的一条，
  其余的标记为 `重复` 并指回主条目，不逐条处理。
- **图片类问题玩家很难描述位置**，所以截图是硬性必填；没有截图的上报直接按"待确认"挂起。
- **账本文件不能放 `localization/` 下**：那里的所有 `*.json` 都会被当成译文来源扫描，
  会被自动翻译流水线误抓（`scripts/repo_utils.py` 的 `translation_sources()`）。
  放 `manifests/` 则不会触发私有构建通知，只触发校验，这是想要的行为。
- **新增一个"汉化面"要同时改三处**，容易漏：
  `scripts/repository_validation.py` 的 `KNOWN_SURFACES`、
  `schema/apk-builtin.schema.json` 里 `name` 的 `enum`、以及 manifest 本身。
- **歌词有两个数字陷阱**：①索引文件 `lyrics_manifest.json` 里写"已译 11,065"，
  而源文件实际已采纳 12,465，这个字段陈旧，引用前必须重新统计；
  ②源文件里有 1,263 行标着"未翻译"，但其中 1,257 行的原文是英文歌词。
  只看状态字段会虚报约 200 倍，必须同时判断原文里有没有日文。
  这一条我在写本规划时先犯过一次，改正后记录在此。
- **字体是否缺字还没结论**：9.0.200 有覆盖率证据，9.0.300 找不到同等证据。
  不要对外说"字体没问题"，也不要说"字体缺字"，两种说法目前都没有证据。
- **图片"没下发"有更硬的证据了，而且不是简单开个开关**：覆盖层自己的清单里写着
  `status: "staged_not_published"`，并标着"未在真机验证""文本覆盖未合并"；
  同时留了一个待确认问题——同名地址可能取到旧缓存，真机测试前要先确认。
  另外，重开生成流水线还需要先选一个图像模型供应商。这两件事本规划都不包。

## 附录 A：标签表

| 标签 | 建议颜色 | 含义 |
| --- | --- | --- |
| `类型/漏译` | `#1d76db` | 还是日文或英文 |
| `类型/误译` | `#d93f0b` | 中文不对、看不懂、术语不一致 |
| `类型/显示` | `#fbca04` | 方块、缺字、重叠、溢出、错位 |
| `类型/覆盖` | `#5319e7` | 整块内容还没纳入汉化 |
| `范围/文本` | `#c5def5` | 对话、剧情、卡面文字 |
| `范围/歌词` | `#d0bfff` | 歌曲歌词（单独统计，待翻只剩 6 个位置） |
| `范围/图片` | `#bfd4f2` | 按钮、横幅、活动图 |
| `范围/字体` | `#d4c5f9` | 字形、缺字 |
| `范围/底栏` | `#c2e0c6` | 底栏与系统界面（本仓库可直接改） |
| `状态/待确认` | `#ededed` | 需要复现或补充信息 |
| `状态/已确认` | `#0e8a16` | 已核实，等待处理 |
| `状态/已修复待发版` | `#f9d0c4` | 改好了，还没进版本 |
| `状态/已发版` | `#0e8a16` | 已在某个版本修复 |
| `状态/不处理` | `#ffffff` | 版权、风格取舍或技术上做不到 |
| `来源/社区` | `#d4c5f9` | 玩家上报 |
| `来源/自查` | `#fef2c0` | 自己发现 |
| `来源/CI` | `#e11d21` | 流水线自动创建 |

## 附录 B：账本条目示例

```json
{
  "id": "LB-0001",
  "status": "confirmed",
  "area": "image",
  "route": "client",
  "found_in": "9.0.300",
  "fixed_in": null,
  "location": "主页 → 菜单 → 个人资料",
  "ja": "プロフィール",
  "zh_current": "プロフィール",
  "zh_expected": "个人资料",
  "issue": 12,
  "source": "community",
  "evidence": ["https://github.com/kohakunamori/MLTDTranslationClient/issues/12"],
  "notes": "图片类界面，属于当前暂停的图片覆盖范围"
}
```

字段约定：

- `status`：`reported` / `confirmed` / `fixing` / `fixed` / `released` / `wontfix` / `duplicate`
- `area`：`text` / `image` / `lyrics` / `cjk-font` / `bottom-bar` / `unknown`
- `route`：`client` 或 `assets`（决定修在哪个仓库）
- `source`：`community` / `self` / `ci`
- `fixed_in` 在 `status` 为 `released` 时必填

## 附录 C：事实索引（用于核对，可跳过）

1. Client 覆盖数字：`manifests/portal-resource-manifest.json`（`totals` 与 `categories`）。
2. Client 内置文本规模：`manifests/apk-source-state.json` 的 `records: 632`、
   `translatable_records: 585`。
3. 译文来源扫描范围：`scripts/repo_utils.py` 的 `translation_sources()` 会递归
   `localization/` 下所有 `*.json`；`scripts/translation_pipeline.py` 的 `records()`
   会把任何含 `ja`/`zh` 键的对象当作条目。
4. 新增"面"的三处改动：`scripts/repository_validation.py` 的 `KNOWN_SURFACES`、
   `schema/apk-builtin.schema.json` 的 `name.enum`、以及 manifest。
5. schema 限制：`schema/apk-builtin.schema.json` 根节点 `additionalProperties: false`。
6. 不接受外部 PR：`.github/workflows/validate-client.yml` 中 `concurrency` 段的注释。
   README 的「贡献」一节已于本次改动中替换为 Issue 上报指引，
   并保留一句"代码层面的改动暂未开放"。Assets 仓库的 README 仍是"后续开放贡献仍在规划"。
7. 图片暂停：`MLTDTranslationAssets/configs/localization-pipeline.json` 的
   `images.enabled: false`；`MLTDTranslationAssets/docs/LOCALIZATION_PIPELINE.md`
   第 14～18 行说明"生成构建会略过图片覆盖"。
8. 图片规模与存量覆盖：`MLTDTranslationAssets/manifests/images.manifest.json`
   （937 张）；已备好的覆盖层在 `MLTDTranslationAssets/image-overlay/1077741/`，
   其 `overlay-manifest.json` 写着 `status: "staged_not_published"`、
   `image_bundles: 231`、`image_textures: 1228`、`image_bytes: 541380840`，
   并同时标着 `real_client_verified: false`、`text_translation_complete: false`，
   `blocker` 一栏写的是"同名地址可能取到旧缓存，真机测试前要先确认缓存语义"。
   当前资源版本见 `MLTDTranslationAssets/manifests/asset-version.json`（1077750）。
9. Assets 文本数字：`MLTDTranslationAssets/manifests/portal-resource-manifest.json`
   的 `totals`（395,673 / 已译 395,574 / 待审 99）。这两个数每天跟着同步变动，
   以最新一次生成为准。
10. 对外进度以查阅站的线上数据为准：
    `https://mltd-portal.nyaneko.cn/data/portal.json`（无需登录即可取），
    实测 2026-10-12 那一版为 `total 409350 / translated 407992 / pending 94 /
    untranslated 6 / not_needed 1258 / progress_percent 99.98`，
    其中歌词单独一行：13,729 个位置、12,465 已译、1,258 无需翻译、6 待翻。
    注意查阅站仓库里 `public/data/portal.json` 是本地生成产物，可能是旧快照
    （本地那份是 2026-10-08 的，歌词数字已经和现在对不上），不要拿它当现状。
11. 歌词的统计陷阱（本规划踩过一次）：`MLTDTranslationAssets/lyrics/songs/` 491 个
    文件、13,732 行里，`untranslated` 有 1,263 行，但按原文里有没有日文去筛，
    只剩 6 行是真待翻，另外 1,257 行是英文歌词。查阅站线上把英文那批算成
    "无需翻译 1,258"，与我的 1,257 差 1 行，属判定边界差异，不影响结论。
    按状态字段直接统计会虚报约 200 倍。
    `lyrics/lyrics_manifest.json` 的 `translated_slots: 11065` 也是陈旧字段。
12. 流水线自动开 Issue 的先例：`kohakunamori/MLTDTranslationAssets` issue #39，
    作者为 `github-actions`；对应步骤是
    `MLTDTranslationAssets/.github/workflows/llm-translate-assets.yml` 里的
    `Report a real failure as a tracking issue`，按标题查重、有则评论、无则新建，
    没有标签也没有自动关闭。
13. "Now Loading…" 这一实例：截图 `local-data/device-shot-after-fix.png`；
    在 `localization/9.0.200/runtime-bi-zhcn.json` 与
    `localization/9.0.300/runtime-bi-zhcn.json` 的 632 行里，按
    `loading` / `ローディング` / `読込` 检索均无匹配。
14. 只审计不落地的三份脚本分别排查内置界面文字、Unity 之外的文本文件和系统层面的
    日文串；它们的交接产物把边界固定为 `writeback_allowed: False`、
    `japanese_screening_status: "not_started"`、`reviewed_images: 0`。
15. 构建系统实际只会改三类 Unity 对象（内置文本 `BI_jp.gtx`、字体、底栏图集），
    其余对象强制逐字节不变，且代码里直接写着
    `scope: 'runtime BI only; other APK UI/textures excluded'`。
    应用名会改，但没有登记进 Client 仓库的三个面里。
16. 字体缺字情况：9.0.200 有覆盖率证据（3129/3129），但 9.0.300 找不到同类证据，
    **是否缺字未证实**，不要当成已知缺口对外说。
17. 查阅站的历史：它曾经做过一整套社区投稿功能（GitHub 登录 → 自动开分支 → 提改动），
    并在一比一真实环境里联调通过；随后在 2026-10-12 的提交
    `fe3fa28`「refactor: 纯静态译文查阅站（无 Worker/D1/协作）」里连同后台一起被删除，
    Cloudflare 侧的数据表也已清空。所以改走 Issue 这条路，是延续了当时的简化方向，
    不是另起炉灶。相关残留见 `public/lib/github-write.js` 的注释和
    `README.md` 的「贡献」一节。
18. 当前基线是绿的，动手前已确认：`python -m scripts.validate_repo` 通过、
    `python -m unittest discover -s tests` 20 个测试全过。
