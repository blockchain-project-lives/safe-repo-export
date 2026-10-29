# Safe Repo Export 发布说明

本项目提供 PyPI 发布工作流，当前版本以 `safe_repo_export/_version.py` 为准；历史变更见 [CHANGELOG](../CHANGELOG.md)。包实现为纯 Python，构建产物是平台无关的 `py3-none-any.whl` 和源码包。独立测试 workflow 仅手动触发；发布 tag 仍自动执行发布前验证。

## 名称与唯一版本源

- PyPI 分发名称：`pyproject.toml` 的 `[project].name`，为 `safe-repo-export`。
- Python 导入名称：`safe_repo_export`。PyPI 名与导入名可以不同。
- CLI 名称：`pyproject.toml` 的 `[project.scripts]`，为 `safe-repo-export`、`safe-repo-export-version`。
- 唯一版本源：`safe_repo_export/_version.py`。打包配置动态读取它，无需同步多个版本号。
- GitHub 仓库名和本地目录名：可以独立更改，代码不依赖当前绝对路径。

首次发布前，可以先修改分发名、CLI 名、README 安装示例和 PyPI 认证配置。发布 workflow 从构建元数据读取项目名，无需修改发布 URL。wheel 验证脚本同样读取构建元数据。若同时改 Python 导入名，还需替换源码目录、打包配置、入口、版本路径、测试和脚本里的导入。

## 根目录便捷入口

- `install.sh` → `install.py`：安装到项目内 `.venv`，管理环境所有权、重复安装检测、验证与失败恢复。
- `init_lists.sh` → `scripts/init_lists.py`：把六份默认规则及禁用的 Java 替换示例写到当前仓库根目录 `.safe-repo-export/`，保留已有文件。
- `bump_version.sh` → `scripts/bump_version.py`：增加版本，可附加 `--commit` / `--tag` / `--push`。
- `commit_and_tag.sh`：保留原来的根目录入口名称，接收 `vX.Y.Z` 和可选消息，仅提交版本文件并打 tag。

```console
./install.sh
./bump_version.sh patch --dry-run
./bump_version.sh patch --push
./commit_and_tag.sh v0.1.1 "Release v0.1.1" --push
```

Shell 入口支持 macOS/Linux；Windows 使用 `python install.py` 和 `python scripts/bump_version.py`。安装默认只管理专用 `.venv`，遇到已有未标记环境时停止，请使用 `--venv PATH`。同版本但源码变化会重新安装，源码和有效安装均未变时直接复用；重建成功后清理本次临时备份，失败时恢复旧环境。外部 pip 缓存和下载不会回滚。

## 发布前验证

在虚拟环境执行：

```console
python -m pip install build twine
python -m unittest discover -s tests -v
python -m build
python -m twine check dist/*
python scripts/smoke_test.py --dist dist
```

旧构建产物应清理后再构建；wheel 验证脚本要求 dist 中只有一个 wheel。验证脚本会安装到当前环境，勿用需要保持不变的 Python 环境。

把源码、规则、测试和 `.github/workflows/` 一并提交并推送。发布前将 CHANGELOG 的 Unreleased 条目归入本次版本并填写日期。`workflow_dispatch` 的工作流文件须先存在于默认分支，Actions 页面才会显示手动运行入口。可以在仓库中创建 `pypi` environment，设置适用的发布规则。

## PyPI 认证（二选一）

推荐 Trusted Publishing：

1. 登录 PyPI，在现有项目的 Publishing 页面添加 GitHub publisher；项目尚不存在时，在账号 Publishing 页面添加 pending publisher。
2. 填最终 PyPI 项目名称（pending publisher）、GitHub owner、仓库名。
3. Workflow filename 填 `publish.yml`，不是整个 `.github/workflows/publish.yml` 路径。
4. Environment name 填 `pypi`，与 workflow 一致。
5. 不配置 `PYPI_API_TOKEN`，workflow 自动走 OIDC。`id-token: write` 已限制在 publish job。

参考 [PyPI Trusted Publishing 使用说明](https://docs.pypi.org/trusted-publishers/using-a-publisher/)、[新项目 publisher 配置](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)。

也可使用 API token：在仓库或 `pypi` environment 的 Actions secrets 添加 `PYPI_API_TOKEN`。workflow 检测到该 secret 后使用 token 发布。Token 的项目范围须允许上传目标项目。首次发布新项目时需要可创建项目的 token；首次发布后可改用项目范围 token。不要把 token 写入文件或版本控制。

## 自动发布：本地创建并推送 v tag

已有干净工作区、初始提交和 origin 后：

```console
python scripts/bump_version.py patch --dry-run
python scripts/bump_version.py patch --push
```

第二条命令执行（也可用根目录 `./bump_version.sh patch --push`）：更新唯一版本源 → 只提交版本文件 → 创建带注释的 `vX.Y.Z` tag → 原子推送当前分支及该 tag。`--remote NAME` 可选择其他 Git remote。

首次要发布现有 `0.1.0`，无需增加版本：

```console
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin refs/tags/v0.1.0
```

自动条件是 `push.tags: ["v*"]`。只在本地打 tag 不触发；推送分支不会推送 tag。以 `v` 开头即可触发 workflow，但上传前必须严格通过 `v` + 当前 `X.Y.Z` 包版本检查，例如包版本 `0.1.1` 只允许 tag `v0.1.1`。

GitHub 通过默认 `GITHUB_TOKEN` 产生的事件通常不会再触发其他 workflow；此处版本命令在本地推送，使用用户 Git 凭证。详见 [GitHub 触发说明](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow)。

## 手动发布

Actions → **Publish to PyPI** → **Run workflow**，在 `tag` 输入现有的 `vX.Y.Z`。即使手动运行时选的是默认分支，workflow 仍明确检出 `refs/tags/输入值`，发布该 tag 的代码。

两个入口使用相同流程：

1. 检出指定 tag，校验 tag 与包版本。
2. Windows/macOS/Linux × Python 3.10/3.14：回归测试、构建、twine 元数据检查、离开源码目录安装 wheel 验证。
3. 单独 build job 构建一次 wheel + sdist，上传 Actions artifact。
4. 仅 Ubuntu publish job 下载 artifact，通过 Trusted Publishing 或 token 上传 PyPI。

手动运行发布的是已有版本，不会修改版本、创建 tag 或推送代码。PyPI 不允许覆盖同名同版本文件：已经发布成功的版本无需重复上传，需要新内容时增加版本。失败后若只有部分文件上传，可先检查 PyPI 状态再决定补救，不要重用旧版本发布不同内容。

## 版本命令与失败恢复

```console
python scripts/bump_version.py minor
python scripts/bump_version.py major --commit
python scripts/bump_version.py 1.2.3 --tag
python -m safe_repo_export.release --check-tag v0.1.0
```

安装后也可用 `safe-repo-export-version`。支持稳定版本 `X.Y.Z`，不接受预发布版本。新版本必须严格增大。

提交/tag/推送模式要求工作区干净（含未跟踪文件），且有初始提交和 Git 作者身份。命令只提交版本文件，不会 `git add .`。提交失败时恢复旧版本及暂存状态；tag 或 push 失败时保留已经创建的本地版本提交，便于恢复。推送失败后不要再次运行 patch 增加版本，按错误提示重试现有 tag：

```console
git push --atomic origin HEAD refs/tags/vX.Y.Z
```

## 常见发布问题

| 表现 | 检查 |
|---|---|
| 本地打 tag 后没有 Actions | 是否实际推送 `refs/tags/vX.Y.Z`，tag 内是否含 workflow |
| 找不到手动入口 | workflow 是否已推送到默认分支，Actions 是否启用 |
| 手动检出失败 | tag 是否存在于远端，输入是否含 `v` 前缀 |
| 版本校验失败 | tag 和 `_version.py` 是否完全一致 |
| OIDC / invalid publisher | PyPI owner、repo、`publish.yml`、`pypi` 是否与实际值一致 |
| Token 认证失败 | secret 名是否为 `PYPI_API_TOKEN`，是否可访问当前项目 |
| File already exists | 该版本已上传，PyPI 不能覆盖 |
| Windows/macOS 测试失败 | 查看 test job；未全部通过时不会运行 publish |

详见 [PyPI Trusted Publishing 排错](https://docs.pypi.org/trusted-publishers/troubleshooting/)。
