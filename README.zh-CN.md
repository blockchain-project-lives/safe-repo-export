# Safe Repo Export

[English](README.md) | [简体中文](README.zh-CN.md) | [Changelog / 更新记录](CHANGELOG.md)

过滤、脱敏并导出 Git 仓库快照，用于分享或代码分析。Python 3.10+，支持 Windows/macOS/Linux，使用标准库，无运行时 Python 包依赖；需要 Git，Gitleaks 可选。

## 安装与快速使用

```sh
python -m pip install --upgrade safe-repo-export
safe-repo-export --version
safe-repo-export init
safe-repo-export --output ../sanitized --archive zip
```

在目标仓库内执行。默认导出 `HEAD`，规则需要先提交；本地调试无需提交时使用：

```sh
safe-repo-export --worktree --output ../sanitized --replace
```

`--worktree` 使用磁盘上的最新内容和工作区规则，包括已跟踪文件的修改与删除。新文件先 `git add` 即可；未跟踪文件不导出。不会创建源仓库提交或修改暂存区；导出过程中请避免同时编辑文件。

```sh
safe-repo-export --ref v0.1.3 --output ../release-export
safe-repo-export --repo /path/to/project --output /path/to/export --archive tar.gz
```

Windows 路径含空格时加引号，例如 `--repo "C:\Projects\my project"`。按本机环境将 `python` 换为 `python3` 或 `py`。

## 命令与模块入口

| 入口 | 用途 |
|---|---|
| `safe-repo-export [options]` | 过滤、脱敏、扫描、导出及可选归档 |
| `safe-repo-export init` / `init-policies` | 生成六份默认规则，不覆盖已有文件 |
| `python -m safe_repo_export ...` | 与主命令等价；使用当前 Python 环境 |
| `python safe_repo_export.py ...` | 源码仓库入口，无需安装 |
| `safe-repo-export-version ...` | 维护工具自身版本，不用于被导出的项目 |
| `python -m safe_repo_export.release ...` | 与版本命令等价 |

## 导出参数（完整）

| 参数 | 说明 |
|---|---|
| `--repo PATH` | 当前目录所属 Git 仓库；可从子目录执行 |
| `--ref REF` | 已提交的分支、tag 或 commit，默认 HEAD |
| `--output PATH` | 必填；输出目录必须位于源仓库之外，且不能包含源仓库 |
| `--worktree` | 导出已跟踪文件的当前内容，包括暂存/未暂存修改和删除；仅支持 HEAD |
| `--allow-dirty` | 允许源仓库有修改，但仍只导出已提交内容 |
| `--archive none\|zip\|tar.gz` | 归档格式，默认 none；归档旁生成 .sha256 |
| `--replace` | 允许替换不同的已有输出和归档，失败时恢复 |
| `--salt-file PATH` | 持久私有盐，默认 OUTPUT.pseudonym-salt；必须位于源仓库及输出之外 |
| `--require-gitleaks` | 要求已安装 Gitleaks；发现和扫描错误仍为提示 |
| `--gitleaks-strict` | 要求 Gitleaks，发现或扫描/报告错误会阻止导出 |
| `--include-list PATH` | 覆盖包含路径规则 |
| `--exclude-list PATH` | 覆盖排除路径规则 |
| `--skip-list PATH` | 覆盖免脱敏/免扫描路径规则 |
| `--redact-keys PATH` | 覆盖敏感键正则规则 |
| `--public-hosts PATH` | 覆盖公共主机白名单 |
| `--gitleaks-ignore PATH` | 覆盖仅针对 Gitleaks 的忽略规则 |
| `--version` | 显示安装版本 |
| `-h, --help` | 显示帮助；不带参数也显示帮助 |

`--repo` 不指定时寻找当前目录所属仓库的根目录；相对输出路径按执行命令时的当前目录解析。`--worktree` 只能搭配默认 `HEAD`，不能与其他 `--ref` 混用。

## 规则初始化与优先级

```sh
safe-repo-export init
safe-repo-export init --directory /path/to/rules
```

`init` 默认写入当前仓库根目录 `.safe-repo-export/`；仓库子目录也会找到根目录。非 Git 目录则写到当前目录。参数只有 `--directory PATH` 和 `-h/--help`。已有文件保留。

| 文件（均位于 .safe-repo-export/） | 说明 |
|---|---|
| `safe-repo-export-include.list` | 区分大小写的路径/通配符；默认 ** |
| `safe-repo-export-exclude.list` | 始终移除的路径/通配符 |
| `safe-repo-export-redact-keys.list` | 不区分大小写的敏感键正则 |
| `safe-repo-export-public-hosts.list` | 可保留的主机名，也匹配其子域名 |
| `safe-repo-export-sanitize-skip.list` | 跳过脱敏、内置扫描及 Gitleaks 的路径 |
| `safe-repo-export-gitleaks-ignore.list` | 仅忽略 Gitleaks：整行、regex: 或 path: |

优先级：显式命令行规则文件 > 所选 commit 中的规则（`--worktree` 时为工作区规则）> 包内默认规则。每个文件完整替换同类默认规则；空 include 不保留任何源文件。空行和 `#` 注释忽略；路径统一使用 `/`，`**/` 可匹配零层目录。保留的 `.list` 文件字节不变，但仍受路径过滤及内置扫描约束。

白名单也匹配子域名；带凭据或查询参数的 URL 不因白名单免于脱敏。`sanitize-skip` 同时跳过脱敏和扫描，`gitleaks-ignore` 只影响 Gitleaks。忽略规则示例：

```text
assertEquals("example", result);
regex:assertEquals\(.*\);
path:tests/fixtures/**
```

## 导出与脱敏行为

- 默认包含所有已跟踪路径，再移除依赖、构建产物、缓存、本地 `.env`、密钥材料及二进制文件。移除软链接，不导出子模块内容，也不会下载 LFS 对象。
- 输出是独立 Git 仓库，仅含一个脱敏提交，无远端和源历史。归档不含 `.git`；生成 `.safe-repo-export/EXPORT-REPORT.md` 和 `MANIFEST.sha256`。
- 相同输入及盐重复运行保持输出不变；不同输出需 `--replace`。替换失败会回滚，但不是跨文件的断电安全事务。旁路锁文件会保留，进程退出时释放锁。
- 配置按敏感键及 URL/IP/域名等规则处理。YAML 数字、布尔、null、空值及仅含空格的引号值保留；替换保留冒号后空格、行尾注释和 CRLF。
- POM 仅将带 `http://`、`https://` 的内容作为 URL，其他值按敏感键处理。保留 Maven groupId、Java 类名、依赖坐标及 URL 属性引用。
- 源码采用更窄的凭据规则：保留业务常量、地址、哈希和普通词表；明确的密码字段、Map/字典凭据及可识别 token/私钥仍脱敏。词表里的 `"secret", "section"` 不视为键值对。
- 独立 SQL 文件保留 DDL/注释，移除 INSERT/REPLACE/UPDATE/DELETE/LOAD DATA/COPY 数据语句；MyBatis XML 不当作 SQL dump。
- 内置残留扫描发现高可信问题时阻止导出，报告不含命中值。Gitleaks 默认仅提示，严格模式会阻止导出。自动规则不是完整语言解析器，分享前应复核报告和保留的配置。
- 私有盐默认在输出旁的 `OUTPUT.pseudonym-salt`，不进入导出或归档。复用盐可保持假名稳定。Unix 要求 0600；Windows 使用账户/文件系统权限。

## 本地源码安装与命令位置

```sh
./install.sh                         # macOS/Linux
python install.py                    # Windows / cross-platform
./install.sh --venv ../safe-repo-export-env
```

| 参数 | 说明 |
|---|---|
| `--venv PATH` | 专用环境位置，默认项目/.venv |
| `--commands-dir PATH` | 命令入口目录，默认 ~/.local/bin |
| `--no-register` | 仅安装环境，不注册命令或 PATH |
| `--force` | 强制重建安装环境 |
| `--dry-run` | 只预览目标位置 |
| `-h, --help` | 显示帮助 |

安装包位于专用虚拟环境；`~/.local/bin` 的两个命令只是入口，并非安装进系统 Python。必要时配置用户 PATH，新终端可直接调用。环境由安装器管理，源码未变时复用；失败重建恢复旧环境。可用 `SAFE_REPO_EXPORT_PYTHON` 指定 Shell 安装器的解释器。

若 pip 显示新版本但命令仍是旧版，用 `type -a safe-repo-export` 检查入口。切回 pyenv 安装时，可删除安装器入口再刷新：

```sh
rm -f ~/.local/bin/safe-repo-export ~/.local/bin/safe-repo-export-version
pyenv rehash
rehash
safe-repo-export --version
```

## 维护版本与发布

在工具自身源码仓库根目录执行，或指定 `--repo`。这不是升级已安装工具的命令；升级用 `python -m pip install --upgrade safe-repo-export`。

```sh
safe-repo-export-version patch --dry-run
./bump_version.sh 0.1.4 --push
# Windows / cross-platform:
python scripts/bump_version.py 0.1.4 --push
```

| 参数 | 说明 |
|---|---|
| `patch / minor / major / X.Y.Z` | 位置参数：自增或指定更大的稳定版本号 |
| `--repo PATH` | 工具自身源码根目录，默认当前目录；不自动寻找根目录 |
| `--commit` | 仅提交版本源文件，要求工作区干净 |
| `--tag` | 隐含 --commit，并创建注释 tag vX.Y.Z |
| `--push` | 隐含 --tag，原子推送分支和 tag |
| `--remote NAME` | 推送远端，默认 origin |
| `--message TEXT` | 自定义提交和 tag 消息 |
| `--dry-run` | 预览，不修改文件 |
| `--check-tag vX.Y.Z` | 只校验 tag 与包版本；不能与版本变更/发布参数混用 |
| `-h, --help` | 显示帮助 |

根目录入口：`bump_version.sh` 委托给 `scripts/bump_version.py`；`commit_and_tag.sh vX.Y.Z [MESSAGE] [--push]` 支持显式版本；`init_lists.sh`（Windows：`python scripts/init_lists.py`）保留调用者目录并初始化规则。

独立 Tests and package workflow 仅手动触发，push/PR 不运行。推送 `v*` tag 自动触发发布，保留三平台 × Python 3.10/3.14 的发布前测试、构建和安装验证。也可手动发布已有 tag。详见 [发布说明](docs/RELEASING.md) 和 [更新记录](CHANGELOG.md)。

## 高级流水线子命令

普通导出会自动调用这些步骤；通常无需单独执行。以下列出所有必填参数，每个命令均支持 `-h/--help`。

| 命令 | 必填参数 | 用途 |
|---|---|---|
| `safe-repo-export generate-salt` | `--output PATH` | 生成/验证私有盐文件 |
| `safe-repo-export sanitize` | `--root PATH, --include PATH, --exclude PATH, --redact-keys PATH, --public-hosts PATH, --salt-file PATH, --state PATH` | 过滤、脱敏并写状态；直接修改 --root |
| `safe-repo-export summarize-gitleaks` | `--input PATH` | 汇总 Gitleaks JSON 报告 |
| `safe-repo-export finalize` | `--root PATH, --state PATH, --gitleaks-status TEXT` | 生成导出报告和校验清单 |

可选参数：

- `sanitize`: `--skip-list PATH`, `--gitleaks-ignore PATH`, `--ignore-state PATH`.
- `summarize-gitleaks`: `--root PATH`, `--skip-list PATH`, `--ignore-state PATH`, `--summary PATH`.
- `finalize`: `--gitleaks-summary PATH`.

其中 `--state` / `--ignore-state` 是流水线 JSON 状态文件；`--input` 是 Gitleaks JSON 报告，`--summary` 是汇总输出，`--gitleaks-summary` 读取该汇总，`--gitleaks-status` 是写入报告的状态文本。

## 开发验证

```sh
python -m unittest discover -s tests -v
python -m pip install build twine
python -m build
python -m twine check dist/*
python scripts/smoke_test.py --dist dist
```

请在测试虚拟环境执行 smoke test：它会安装 wheel 到当前 Python。构建前清理旧 dist，确保其中只有一个 wheel。源码更改需在下一次发布后才进入 PyPI 包。
