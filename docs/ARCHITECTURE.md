# Client 仓库架构

仓库按“源数据、领域规则、入口适配、自动化”分层。依赖方向始终从入口指向领域，
领域模块不依赖 GitHub Actions、`argparse` 或具体 provider。

```text
localization/  manifests/  schema/
        │
        ▼
scripts/repo_utils.py       ← 路径、规范化字节、JSON、活动版本
scripts/translation_pipeline.py ← 翻译记录、去重、占位符和回写规则
scripts/repository_validation.py ← Manifest、图片和 Runtime BI 校验
        │
        ├── validate_repo.py
        ├── build_portal_resource_manifest.py
        ├── dispatch_private_build.py
        └── llm_translate_untranslated.py
                         │
                         ▼
                 .github/workflows/
```

## 模块边界

- `RepositoryLayout` 是仓库路径的唯一入口。新增资源目录时先扩展它，再由调用方使用
  accessor，避免在多个脚本中复制路径字符串。
- `repo_utils.py` 只放跨领域的仓库规则：规范化文本字节、哈希、JSON 读写、版本和
  运行时目录定位。它不负责打印 CLI 信息或触发外部服务。
- `translation_pipeline.py` 是翻译领域模块。它接受 `Path` 和普通数据，提供可复用的
  `TranslationPipeline.collect()` / `apply()`，不解析命令行参数，也不读取环境变量。
- `repository_validation.py` 是校验领域模块，返回结构化汇总并抛出 `ValidationError`；
  `validate_repo.py` 只负责把结果格式化给本地命令和 CI。
- `llm_translate_untranslated.py` 是兼容入口，只负责把 CLI 参数转换成领域方法调用并
  输出结果。旧的直接文件调用仍可用，Actions 使用模块入口 `python -m scripts.…`。
- 校验、门户清单和构建通知各自保留流程编排，但共享路径与数据规则；它们不能从 CLI
  模块反向导入领域逻辑。

## 新增资源类型

1. 在 `localization/<client_version>/` 定义源文件和稳定的记录身份。
2. 在 `RepositoryLayout` 增加路径 accessor，并在对应领域模块中实现读取、校验和回写。
3. 让 `validate_repo.py` 调用领域校验；只有需要人工或 CI 参数时才修改 CLI 入口。
4. 在 `build_portal_resource_manifest.py` 中增加汇总适配，不把汇总规则写进领域模块。
5. 增加领域模块的直接单元测试，再通过 `python -m scripts.…` 验证工作流入口。

## 不变量

- 所有文本哈希都经过同一套换行规范化；写回 JSON 统一使用 UTF-8、LF 和末尾换行。
- 资源身份由源内容和记录顺序决定，不能由 provider 返回的译文决定。
- 工作流只负责调度，不能复制翻译状态判断、占位符检查或版本路径推导。
- 兼容层可以保留旧入口，但新功能必须进入领域模块，不能继续扩张兼容脚本。
