# Safe Repo Export

[English](README.md) | [简体中文](README.zh-CN.md) | [Changelog / 更新记录](CHANGELOG.md)

Export filtered, sanitized Git snapshots for sharing or code analysis. Python 3.10+, Windows/macOS/Linux, standard library only and no runtime Python package dependencies. Git is required; Gitleaks is optional.

Default preservation/redaction decisions, Redis keys, EVM addresses/hashes, YAML/JSON differences and all six policies: [Default rules](docs/DEFAULT_RULES.md).

## Install and quick start

```sh
python -m pip install --upgrade safe-repo-export
safe-repo-export --version
safe-repo-export init
safe-repo-export --output ../sanitized --archive zip
```

Run inside the target repository. Default export uses `HEAD` and committed policies. For local debugging without committing:

```sh
safe-repo-export --worktree --output ../sanitized --replace
```

`--worktree` reads current disk contents and working-tree policies, including edits/deletions of tracked files. Stage new files with `git add` to include them; untracked files are excluded. It creates no source commit and does not change the index. Avoid editing files during export.

```sh
safe-repo-export --ref v0.1.3 --output ../release-export
safe-repo-export --repo /path/to/project --output /path/to/export --archive tar.gz
```

Quote Windows paths containing spaces, e.g. `--repo "C:\Projects\my project"`. Use `python3` or `py` instead of `python` where appropriate.

## Commands and module entry points

| Entry point | Purpose |
|---|---|
| `safe-repo-export [options]` | Filter, redact, scan, export and optionally archive |
| `safe-repo-export init` / `init-policies` | Write six default policies, preserving existing files |
| `python -m safe_repo_export ...` | Equivalent CLI using the selected Python environment |
| `python safe_repo_export.py ...` | Source checkout entry; no installation needed |
| `safe-repo-export-version ...` | Maintain this toolkit’s version, not the exported project |
| `python -m safe_repo_export.release ...` | Equivalent version command |

## Export options (complete)

| Option | Meaning |
|---|---|
| `--repo PATH` | Git repository containing the current directory; accepts a subdirectory |
| `--ref REF` | Committed branch, tag or commit; default HEAD |
| `--output PATH` | Required; output must be outside the source repository and must not contain it |
| `--worktree` | Export tracked files from disk, including staged/unstaged edits and deletions; HEAD only |
| `--allow-dirty` | Allow tracked edits but export only committed content |
| `--archive none\|zip\|tar.gz` | Archive format; default none; also write an adjacent .sha256 |
| `--replace` | Replace differing output/archive destinations with rollback on failure |
| `--salt-file PATH` | Persistent private salt; default OUTPUT.pseudonym-salt; keep outside source and destinations |
| `--require-gitleaks` | Require Gitleaks installation; findings/scan errors remain advisory |
| `--gitleaks-strict` | Require Gitleaks and block on findings or scan/report errors |
| `--include-list PATH` | Override included paths |
| `--exclude-list PATH` | Override excluded paths |
| `--skip-list PATH` | Override paths exempt from redaction and scanning |
| `--redact-keys PATH` | Override sensitive-key regular expressions |
| `--public-hosts PATH` | Override public-host allowlist |
| `--gitleaks-ignore PATH` | Override Gitleaks-only ignore rules |
| `--version` | Print installed version |
| `-h, --help` | Show help; no arguments also show help |

Without `--repo`, discover the Git root containing the current directory. Relative output paths use the command’s current directory. `--worktree` requires default `HEAD` and cannot use another `--ref`.

## Policy initialization and precedence

```sh
safe-repo-export init
safe-repo-export init --directory /path/to/rules
```

`init` writes to the repository root’s `.safe-repo-export/`, including when run from a subdirectory. Outside Git it uses the current directory. Its only options are `--directory PATH` and `-h/--help`. Existing files are preserved.

| File (under .safe-repo-export/) | Meaning |
|---|---|
| `safe-repo-export-include.list` | Case-sensitive paths/globs; default ** |
| `safe-repo-export-exclude.list` | Paths/globs always removed |
| `safe-repo-export-redact-keys.list` | Case-insensitive sensitive-key regexes |
| `safe-repo-export-public-hosts.list` | Hosts allowed to remain, including their subdomains |
| `safe-repo-export-sanitize-skip.list` | Paths exempt from redaction, built-in scan and Gitleaks |
| `safe-repo-export-gitleaks-ignore.list` | Gitleaks-only complete lines, regex: or path: rules |

Precedence: explicit CLI policy > selected commit’s policy (working-tree policy with `--worktree`) > bundled default. Each file replaces its default completely; an empty include retains no source files. Blank lines and `#` comments are ignored. Use `/` paths; `**/` can match zero directories. Retained `.list` bytes are preserved but still subject to path filtering and the built-in scan.

Host entries also match subdomains; credentials or URL query parameters are not exempted. `sanitize-skip` bypasses redaction and scanning; `gitleaks-ignore` affects only Gitleaks. Ignore examples:

```text
assertEquals("example", result);
regex:assertEquals\(.*\);
path:tests/fixtures/**
```

## Export and redaction behavior

- Start with tracked paths; remove dependencies, build outputs, caches, local `.env`, key material and binary files. Remove symlinks, omit submodule contents and do not download LFS objects.
- Output is a standalone Git repository with one sanitized commit, no remote and no source history. Archives exclude `.git`. Reports: `.safe-repo-export/EXPORT-REPORT.md` and `MANIFEST.sha256`.
- Identical input/salt reruns preserve output; changes require `--replace`. Failed replacement rolls back, but is not a crash-proof multi-file transaction. Adjacent lock files remain; process exit releases locks.
- Configuration uses sensitive-key and URL/IP/domain rules. YAML numbers, booleans, null, empty values and whitespace-only quoted values remain intact; replacements preserve colon spacing, inline comments and CRLF.
- POM treats only `http://` and `https://` content as URLs and applies sensitive-key rules to other values. Maven groupId, Java class names, coordinates and URL property references remain intact.
- Source uses narrower credential rules: retain business constants, addresses, hashes and ordinary word lists; redact explicit credential assignments, Map/dict values and recognizable tokens/private keys. `"secret", "section"` in a list is not a key/value pair.
- Standalone SQL retains DDL/comments and removes INSERT/REPLACE/UPDATE/DELETE/LOAD DATA/COPY data statements. MyBatis XML is not treated as a SQL dump.
- High-confidence built-in residual findings block export; reports omit matched values. Gitleaks is advisory unless strict mode is enabled. Rules are not complete language parsers; review reports and retained configuration before sharing.
- Private salt defaults to adjacent `OUTPUT.pseudonym-salt`, never exported or archived. Reuse it for stable pseudonyms. Unix requires 0600; Windows uses account/filesystem permissions.

## Local source installation and command locations

```sh
./install.sh                         # macOS/Linux
python install.py                    # Windows / cross-platform
./install.sh --venv ../safe-repo-export-env
```

| Option | Meaning |
|---|---|
| `--venv PATH` | Managed environment path; default project/.venv |
| `--commands-dir PATH` | Launcher directory; default ~/.local/bin |
| `--no-register` | Install environment without registering commands or PATH |
| `--force` | Force environment rebuild |
| `--dry-run` | Only preview destination |
| `-h, --help` | Show help |

The package lives in a dedicated virtual environment. The two `~/.local/bin` launchers do not install it into system Python. The installer configures user PATH when needed for new terminals, reuses unchanged source and restores the prior environment on failed rebuild. `SAFE_REPO_EXPORT_PYTHON` selects the Shell installer’s interpreter.

If pip reports a new version but the CLI is old, inspect `type -a safe-repo-export`. To switch back to a pyenv installation, remove installer launchers and refresh:

```sh
rm -f ~/.local/bin/safe-repo-export ~/.local/bin/safe-repo-export-version
pyenv rehash
rehash
safe-repo-export --version
```

## Version maintenance and releases

Run at this toolkit’s source root or specify `--repo`. This does not upgrade the installed tool; use `python -m pip install --upgrade safe-repo-export` for that.

```sh
safe-repo-export-version patch --dry-run
./bump_version.sh 0.1.4 --push
# Windows / cross-platform:
python scripts/bump_version.py 0.1.4 --push
```

| Option | Meaning |
|---|---|
| `patch / minor / major / X.Y.Z` | Positional change: increment or specify a higher stable version |
| `--repo PATH` | Toolkit source root; default current directory, without root discovery |
| `--commit` | Commit only the version source; requires a clean worktree |
| `--tag` | Imply --commit and create annotated tag vX.Y.Z |
| `--push` | Imply --tag; atomically push branch and tag |
| `--remote NAME` | Push remote; default origin |
| `--message TEXT` | Custom commit/tag message |
| `--dry-run` | Preview without changing files |
| `--check-tag vX.Y.Z` | Only verify tag/package version; cannot combine with a change or release actions |
| `-h, --help` | Show help |

Root wrappers: `bump_version.sh` delegates to `scripts/bump_version.py`; `commit_and_tag.sh vX.Y.Z [MESSAGE] [--push]` accepts an explicit version; `init_lists.sh` (Windows: `python scripts/init_lists.py`) initializes policies while preserving the caller’s directory.

Standalone Tests and package runs only on manual dispatch, not push/PR. Pushing a `v*` tag triggers publishing, retaining release tests/build/install checks on three platforms × Python 3.10/3.14. Manual publishing accepts an existing tag. See [release setup](docs/RELEASING.md) and [changelog](CHANGELOG.md).

## Advanced pipeline subcommands

Normal export orchestrates these steps automatically; direct use is rarely needed. Required arguments are listed below; every command supports `-h/--help`.

| Command | Required arguments | Purpose |
|---|---|---|
| `safe-repo-export generate-salt` | `--output PATH` | Create/validate a private salt file |
| `safe-repo-export sanitize` | `--root PATH, --include PATH, --exclude PATH, --redact-keys PATH, --public-hosts PATH, --salt-file PATH, --state PATH` | Filter/redact in place and write state; modifies --root |
| `safe-repo-export summarize-gitleaks` | `--input PATH` | Summarize a Gitleaks JSON report |
| `safe-repo-export finalize` | `--root PATH, --state PATH, --gitleaks-status TEXT` | Generate export report and checksum manifest |

Optional arguments:

- `sanitize`: `--skip-list PATH`, `--gitleaks-ignore PATH`, `--ignore-state PATH`.
- `summarize-gitleaks`: `--root PATH`, `--skip-list PATH`, `--ignore-state PATH`, `--summary PATH`.
- `finalize`: `--gitleaks-summary PATH`.

`--state` / `--ignore-state` are pipeline JSON state files. `--input` is a Gitleaks JSON report; `--summary` writes a summary, `--gitleaks-summary` reads it, and `--gitleaks-status` supplies report status text.

## Development checks

```sh
python -m unittest discover -s tests -v
python -m pip install build twine
python -m build
python -m twine check dist/*
python scripts/smoke_test.py --dist dist
```

Run smoke tests in a disposable environment: they install the wheel into the current Python. Clear old dist artifacts before building so only one wheel is present. Source changes reach PyPI only after the next release.
