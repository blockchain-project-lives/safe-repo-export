# Changelog / 更新记录

[English README](README.md) | [中文说明](README.zh-CN.md)

Versions and dates follow repository tags and commits. A tag records source history, not confirmation of a successful PyPI upload.
版本与日期以仓库 tag、提交为准；存在 tag 不代表 PyPI 上传已成功。后续每次发布前将未发布条目归入对应版本。

## 0.1.4 — 2026-10-29

- Fix the built-in scan falsely flagging Java PEM `String.format` assembly with a `%s` body and variable argument; retain detection/redaction of embedded or incomplete private-key material.
  修复内置扫描将 Java 的 PEM 格式拼接（`%s` 正文、变量参数）误判为私钥的问题，仍处理实际或不完整的私钥内容。

- Use `.java.txt` for generated stub templates and examples to avoid IDE Java syntax errors; keep extension-independent loading and compatibility with existing templates.
  初始化模板及文档示例统一使用 `.java.txt`，避免 IDE 按完整 Java 文件报错；读取逻辑仍兼容已有扩展名。

- Add Java method-body replacements selected by repository path, qualified class, method and ordered parameter types. Read private templates under `.safe-repo-export/stubs/`, preserve declarations, then redact and scan the replacement output.
  新增 Java 方法体替换：按仓库路径、完整类名、方法名及参数类型定位，读取 `.safe-repo-export/stubs/` 模板，保留定义并继续脱敏和扫描。
- Generate disabled YAML/template demos during non-overwriting init; package them in wheel/sdist. Support committed refs and current working rules/templates; fail closed on missing/ambiguous/unsafe inputs. Strip private inputs and report only replacement paths/counts.
  init 补齐默认禁用的 YAML/模板示例并纳入 wheel/源码包；支持 ref/工作区规则，缺失/歧义/不安全输入阻止导出，移除私有输入，报告只含路径与次数。
- Remain stdlib-only with restricted YAML and conservative Java lexical matching; document type-matching and syntax limits.
  保持标准库实现，采用受限 YAML 和保守 Java 词法定位，说明类型匹配和语法限制。

- Add a default-rule guide covering policy precedence, source/config differences, Redis keys, EVM literals and format-specific behavior; link it from both READMEs.
  新增默认规则说明，涵盖优先级、源码/配置差异、Redis key、EVM 字面量及格式专门行为，中英文 README 均引用。

- Rewrite both READMEs with complete CLI/module, export, initialization, installation, version and advanced pipeline references; link this changelog.
  重整中英文 README，完整列出命令、模块入口、导出、初始化、安装、版本维护及高级流水线参数，并引用更新记录。
- Correct outdated release documentation and include this changelog in source distributions.
  修正过时的发布说明，将更新记录纳入源码分发包。

## 0.1.3 — 2026-10-29

- Add `--worktree`: export tracked files from disk, including staged/unstaged edits and deletions, without source commits or index changes. Stage new files to include them; use current working-tree policies. Reject non-HEAD refs, unresolved merges and unsafe paths; omit links/submodules.
  新增 `--worktree`：导出已跟踪文件的暂存/未暂存修改和删除，不创建源提交、不改变暂存区；新增文件先暂存，采用工作区规则。拒绝其他 ref、未解决冲突及不安全路径，跳过链接与子模块。
- Make standalone CI manual-only; retain automatic `v*` tag publishing and release validation.
  独立测试仅手动触发；保留 `v*` tag 自动发布及发布前验证。

## 0.1.2 — 2026-10-28

- Preserve YAML numeric, boolean/null and empty/whitespace-only values. Keep colon spacing, inline comments and CRLF when replacing sensitive scalar values.
  YAML 保留数字、布尔/null、空值及纯空格值；替换敏感值时保留冒号后空格、行尾注释及 CRLF。
- Add `mybatis.org` to the bundled public-host policy.
  内置公共主机白名单新增 `mybatis.org`。

## 0.1.1 — 2026-10-13

- Fix package imports in temporary Python scripts used by the publish workflow; accept CRLF version assignments and avoid checkout newline conversion for release tags.
  修复发布工作流临时 Python 脚本的模块导入；版本校验兼容 CRLF，发布 tag 检出禁用换行转换。
- Preserve ordinary source string lists such as `"secret", "section"`; keep redaction for actual credential assignments and Map/dict values.
  普通字符串词表不再误判为敏感键值对，真正的凭据赋值及 Map/字典值继续脱敏。
- Narrow POM redaction to explicit HTTP(S) URLs and sensitive keyed values. Preserve Java class names, Maven coordinates and URL property references.
  收窄 POM 脱敏：识别明确的 HTTP(S) URL 和敏感键值，保留 Java 类名、Maven 坐标及 URL 属性引用。
- Expand public package-repository/documentation hosts in the bundled allowlist.
  扩充公共包仓库及文档服务主机白名单。

## 0.1.0 — 2026-10-12

- Introduce the `safe-repo-export` Python package/CLI for Windows, macOS and Linux, with filtering, redaction, residual scanning, optional Gitleaks, deterministic archives and independent sanitized Git snapshots.
  提供跨 Windows/macOS/Linux 的纯 Python 包与命令，支持过滤、脱敏、残留扫描、可选 Gitleaks、确定性归档和独立脱敏 Git 快照。
- Add six bundled policies, non-overwriting `init`, local environment installers/launchers, and version/commit/tag/push helpers.
  提供六份内置规则、不覆盖文件的 `init`、本地环境安装与命令入口，以及版本更新/提交/tag/推送工具。
- Add cross-platform validation and tag/manual PyPI publishing workflows; upgrade checkout/setup-python/artifact actions to Node.js 24 versions.
  提供跨平台验证和 tag/手动 PyPI 发布工作流，相关 GitHub Actions 升级到 Node.js 24 版本。
- Fix Git for Windows rejecting `nul` as the snapshot’s global excludes file; isolate snapshots from external global excludes/attributes.
  修复 Windows Git 不接受 `nul` 排除规则文件的问题，隔离外部全局 excludes/attributes 配置。
