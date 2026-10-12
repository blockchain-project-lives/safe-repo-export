# Safe Repo Export

通用项目过滤导出与脱敏工具。

[English](README.md) | [简体中文](README.zh-CN.md)

从任意 Git 项目导出经过过滤、脱敏的提交快照，供分享或代码分析使用。工具全部用 Python 标准库实现，适用于 Windows、macOS 和 Linux，没有运行时 Python 包依赖。需要安装 Git 并加入 PATH；Gitleaks 是可选的额外扫描工具。

仓库及 PyPI 包名统一为 `safe-repo-export`，Python 模块为 `safe_repo_export`。首次发布流程见 [发布说明](docs/RELEASING.md)。

## 安装与使用

需要 Python 3.10 或以上。发布到 PyPI 后：

```console
python -m pip install safe-repo-export
safe-repo-export --repo /path/to/project --output /path/to/exports/project --archive zip
```

未安装时，可以直接在本项目目录执行：

```console
python -m safe_repo_export --repo /path/to/project --output /path/to/exports/project --archive tar.gz
```

Windows PowerShell / CMD 示例：

```console
python -m safe_repo_export --repo "C:\Projects\my project" --output "C:\Exports\my project" --archive zip
```

如果系统命令是 `python3` 或 `py`，将示例中的 `python` 替换即可。核心功能无需 Bash、GNU 工具、Homebrew 组件或外部压缩程序。也可直接使用 `python safe_repo_export.py ...` 源码入口。根目录 Shell 脚本是调用 Python 实现的可选便捷入口。

## 一键本地安装

macOS/Linux 在项目根目录执行：

```console
./install.sh
# 新开终端后直接使用
safe-repo-export --version
```

Windows 使用同一套 Python 安装逻辑：

```console
python install.py
safe-repo-export --version
```

PowerShell 激活命令为 `& .venv\Scripts\Activate.ps1`。也可以直接调用 `.venv/bin/` 或 `.venv\Scripts\` 中的命令。

安装脚本管理项目内的专用 `.venv`，验证包、命令和六份内置规则；源码未变且安装正常时，重复执行会跳过重装。已有非本脚本管理的环境会保留，可用 `--venv PATH` 选择其他位置。重建失败时恢复上一次正常环境。构建依赖可能从当前 pip 源下载。

```console
./install.sh --dry-run
./install.sh --force
./install.sh --venv /path/to/dedicated/environment
```

可通过 `SAFE_REPO_EXPORT_PYTHON` 指定 Python 解释器路径。Shell 入口适用于 macOS/Linux Bash；Windows 直接使用等价 Python 入口。

安装完成后会把 `safe-repo-export`、`safe-repo-export-version` 的用户级入口放到 `~/.local/bin`，必要时配置当前 shell 的 PATH。新终端可直接运行，无需每次激活虚拟环境；当前终端可执行安装输出的 PATH 命令。Windows 会更新用户 PATH，新开终端后使用。已有不属于本工具的同名命令会保留并报冲突。`--commands-dir PATH` 可指定入口位置，`--no-register` 可只安装虚拟环境。

## Usage / 帮助

```console
safe-repo-export --help
safe-repo-export init --help
safe-repo-export --output ../sanitized --archive zip
```

不带参数运行 `safe-repo-export` 也会显示 usage。导出默认使用当前 Git 仓库和 `HEAD`，默认不生成压缩包；必须指定仓库外的 `--output` 目录。

## 导出行为

- 只导出指定 `--ref` 的已提交内容，默认 `HEAD`。未跟踪文件和未提交修改不进入结果；`--allow-dirty` 允许工作区有已跟踪修改，但仍只导出提交。
- 输出目录必须位于源仓库外，也不能是源仓库的父目录。导出不会修改源项目。
- 默认允许全部已跟踪文件，再排除依赖目录、构建产物、缓存、本地 `.env`、密钥证书、压缩包及二进制文件。规则适用于多种语言，也可通过 include 文件缩小范围。
- `.github/`、`.idea/`、`.vscode/`、`.safe-repo-export/` 等配置仍受过滤、脱敏规则约束。
- 所有符号链接都省略，避免链接越界和 Windows 创建符号链接的权限要求。不递归导出子模块，不下载 Git LFS 对象。
- 输出目录创建新的 Git 仓库，仅含一个脱敏提交，没有原始历史和 remote。ZIP/TAR 只包含脱敏文件和报告，不打包 `.git`。
- 生成并验证 `.safe-repo-export/MANIFEST.sha256`；可选 ZIP/TAR.GZ 及旁边的 `.sha256` 校验文件。
- 相同内容重复执行保持不变；不同内容必须加 `--replace`。先检查所有目标是否冲突，再执行替换；普通失败或中断会回滚旧输出和旧压缩包。
- 使用 Python 标准库调用系统文件锁，进程退出自动释放。目标旁边的隐藏 `.safe-repo-export.*.lock` 文件保留，确保并发进程锁定同一文件。

每个目标使用原子移动，但多个文件整体不构成断电或强制终止后仍保证恢复的事务。

## 自定义规则

在目标仓库里，一键写出六份默认 list：

```console
safe-repo-export init
```

目录统一为仓库根目录的 `.safe-repo-export/`，从仓库子目录执行也会定位到根目录。尚未 `git init` 时使用当前目录。已有规则不会覆盖，`init-policies` 保留为别名。可用 `safe-repo-export init --directory /path/to/project/.safe-repo-export` 指定位置。

工具根目录也提供 `./init_lists.sh`，Windows 可直接运行 `python scripts/init_lists.py`。给其他仓库生成规则时，在目标仓库中使用脚本的绝对路径：

```console
/path/to/safe-repo-export/init_lists.sh
```

脚本保留调用时的工作目录。生成或修改规则后先提交 Git，再导出，才会使用这些仓库规则。

| 文件 | 用途 |
|---|---|
| `safe-repo-export-include.list` | 允许导出的相对路径/通配符，区分大小写 |
| `safe-repo-export-exclude.list` | 强制排除的相对路径/通配符 |
| `safe-repo-export-redact-keys.list` | 配置敏感键名正则，不区分大小写 |
| `safe-repo-export-public-hosts.list` | 可保留的公开主机名 |
| `safe-repo-export-sanitize-skip.list` | 跳过脱敏、内置扫描和 Gitleaks 的文件 |
| `safe-repo-export-gitleaks-ignore.list` | 仅忽略 Gitleaks 告警的完整行/正则/路径 |

优先级：CLI 显式指定文件 > 选定提交中的 `.safe-repo-export/` 文件 > 包内默认规则。每份规则整体替换对应默认文件；空文件表示空列表，空 include 不保留源文件。空行与 `#` 注释忽略。所有平台路径规则统一使用 `/`，`**/` 也能匹配零层目录。默认没有扫描豁免或 Gitleaks 忽略规则。

```console
safe-repo-export --repo /path/to/project --output /path/to/exports/project --include-list /path/to/include.list --exclude-list /path/to/exclude.list --redact-keys /path/to/keys.list
```

include 示例：

```text
src/**
tests/**
docs/**
pyproject.toml
package.json
.safe-repo-export/**
```

包内模板位于 `safe_repo_export/policies/`，随 wheel 一起安装。保留的 `.list` 文件逐字节导出，包括正则转义和 CRLF，仍受路径过滤及内置残留扫描约束。自动生成的报告会替换源 `.safe-repo-export/` 中的同名文件。

## 脱敏与扫描

配置文件（YAML、JSON、XML、properties、INI、TOML 等）按敏感键进行严格脱敏，同时对 URL、IP、域名及上下文标识生成稳定化名。公开主机白名单同时适用于配置 URL 键和普通 URL；带认证信息、查询参数的 URL，以及凭证/webhook 字段仍会脱敏。Maven `pom.xml` 的 `groupId` 保留原坐标。

源码使用较窄的凭证字面量规则，支持 Java、JS/TS、Python、Go、Kotlin、Rust、C/C++、Shell 等扩展名。普通业务常量、地址、哈希、协议 topic 保留；显式凭证字面量，以及可识别的私钥块、JWT、Telegram/AWS/GitHub/Slack token 和带用户凭证的 URL 会脱敏。关键词/正则定义保留，可识别的真实秘密格式仍会处理。

独立 `.sql` 文件保留 DDL 和注释，删除 `INSERT`、`REPLACE`、`UPDATE`、`DELETE`、`LOAD DATA`、`COPY` 数据语句；MyBatis XML 不按 SQL dump 处理。源码脱敏是词法处理，不是各语言的完整语法解析器。

内置高置信度残留扫描发现问题时阻止导出。报告只含规则和位置，不含命中值。分享前检查 `.safe-repo-export/EXPORT-REPORT.md`、配置和保留的规则文件；自动规则无法识别所有业务秘密。

安装 Gitleaks 后自动使用 `gitleaks dir` 额外扫描。默认告警及扫描/报告错误不阻止导出；`--require-gitleaks` 要求已安装，`--gitleaks-strict` 还会阻止剩余告警和扫描/报告错误。安装和命令见 [Gitleaks 官方说明](https://github.com/gitleaks/gitleaks#usage)。

Gitleaks 忽略规则示例：

```text
# 完整原始行，仅忽略首尾空白
assertEquals("example", result);
# 完整行 Python 正则
regex:assertEquals\(\s*"example"\s*,\s*result\s*\);
# 仓库相对路径
path:tests/fixtures/**
```

ignore 只影响 Gitleaks；skip-list 同时豁免脱敏和扫描。多行告警必须每行都匹配才能忽略。直接运行 Gitleaks 不读取本工具规则。

## 私有盐文件

默认持久保存在 `OUTPUT.pseudonym-salt`，位于输出旁边。复用盐文件可保持化名稳定、支持重复导出。可用 `--salt-file` 指定其他位置，但必须在源仓库、输出和压缩包目标之外。盐不会进入导出或压缩包。失败时删除本次新建盐文件，已有盐文件保留。

Unix 权限要求 `0600`；Windows 使用账户/文件系统访问控制，不按 Unix 权限位检查。请私下保存盐文件。

## 开发、版本与发布

```console
python -m unittest discover -s tests -v
python -m pip install build twine
python -m build
python -m twine check dist/*
python scripts/smoke_test.py --dist dist
```

安装验证脚本会把 wheel 安装到当前 Python 环境，再离开源码目录验证，建议在虚拟环境执行。CI 配置 Windows/macOS/Linux × Python 3.10/3.14 测试及 wheel 安装验证。

一键版本更新：

```console
python scripts/bump_version.py patch --dry-run
python scripts/bump_version.py patch
python scripts/bump_version.py minor --tag
python scripts/bump_version.py patch --push
```

根目录也提供版本更新与发布的 Shell 入口：

```console
./bump_version.sh patch --dry-run
./bump_version.sh patch
./bump_version.sh patch --push
./commit_and_tag.sh v0.1.1 "Release v0.1.1"
```

`commit_and_tag.sh` 已恢复在根目录，接收显式版本（可带 `v`）和可选消息，自动提交版本并创建带注释的 tag；加 `--push` 可一并推送。两个 Shell 入口都支持从其他工作目录调用，实际逻辑交给 `scripts/bump_version.py`，无需先安装项目。

支持 `patch`、`minor`、`major` 或显式 `X.Y.Z`。不带 Git 选项只修改唯一版本源；`--tag` 自动提交版本并生成 `vX.Y.Z` tag；`--push` 自动提交、打 tag，并原子推送当前分支和该 tag。发布 workflow 支持推送 `v*` 自动触发，或手动选择已存在的 tag。首次发布、认证配置和改名见 [RELEASING.md](docs/RELEASING.md)。
