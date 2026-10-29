# Safe Repo Export

[English](README.md) | [简体中文](README.zh-CN.md)

Export a filtered, sanitized snapshot of any Git project for sharing or code analysis. The implementation uses Python's standard library, works on Windows, macOS and Linux, and has no runtime Python package dependencies. Git must be installed and available on PATH. Gitleaks is optional.

The repository and PyPI package are named `safe-repo-export`; the Python module is `safe_repo_export`. See [release instructions](docs/RELEASING.md) before the first PyPI release.

## Install and run

Requires Python 3.10 or newer. After publication:

```console
python -m pip install safe-repo-export
safe-repo-export --repo /path/to/project --output /path/to/exports/project --archive zip
```

From a source checkout, without installation:

```console
python -m safe_repo_export --repo /path/to/project --output /path/to/exports/project --archive tar.gz
```

Windows example (PowerShell or Command Prompt):

```console
python -m safe_repo_export --repo "C:\Projects\my project" --output "C:\Exports\my project" --archive zip
```

Use `python3` on Unix or `py` on Windows if that is your Python command. The core needs no Bash, GNU utilities, Homebrew packages or external archive tool. `python safe_repo_export.py ...` is also available as a source entry point. Optional root Shell scripts are convenience wrappers around the Python implementation.

## One-command local installation

On macOS/Linux, run from the repository root:

```console
./install.sh
# Open a new terminal after installation
safe-repo-export --version
```

On Windows, run the same installer through Python:

```console
python install.py
safe-repo-export --version
```

PowerShell activation: `& .venv\Scripts\Activate.ps1`. You can also run the command directly from `.venv/bin/` or `.venv\Scripts\`.

The installer owns a dedicated `.venv` inside this project, verifies the package/CLI and all bundled policies, and skips reinstalling unchanged source. It preserves unmanaged environments; use `--venv PATH` to choose another destination. A failed rebuild restores the previous managed environment. Build dependencies may be downloaded from the configured pip index. Useful options:

```console
./install.sh --dry-run
./install.sh --force
./install.sh --venv /path/to/dedicated/environment
```

Set `SAFE_REPO_EXPORT_PYTHON` to an interpreter path to select Python explicitly. The Shell entries support macOS/Linux Bash; Windows has equivalent Python entries.

Installation registers `safe-repo-export` and `safe-repo-export-version` in `~/.local/bin` and configures the current shell startup PATH when needed. New terminals can run the commands without activating the environment; use the printed PATH command for the current terminal. Windows updates the user PATH for new terminals. Unmanaged commands are preserved and reported as conflicts. Use `--commands-dir PATH` to select a launcher directory or `--no-register` for an environment-only install.

## Usage

```console
safe-repo-export --help
safe-repo-export init --help
safe-repo-export --output ../sanitized --archive zip
```

For local debugging without committing source changes:

```sh
safe-repo-export --worktree --output ../sanitized --replace
```

To export a committed branch, tag or commit:

```sh
safe-repo-export --ref v1.0.0 --output ../sanitized
```

Running `safe-repo-export` with no arguments also prints usage. Export defaults to the current Git repository and `HEAD`, with no archive; `--output` is required and must be outside the source repository.

## Export behavior

- Export the selected committed `--ref` (default `HEAD`), including its committed policies. `--allow-dirty` permits tracked edits without exporting them.
- Use `--worktree` to export current tracked files, including staged/unstaged edits and deletions, with current working-tree policies. Stage new files with `git add` to include them; untracked files remain excluded. This mode requires `HEAD`, does not change the source index or create a source commit, and runs the same filtering and redaction pipeline. Avoid editing files while a worktree export is running.
- Output must be outside the source repository and must not contain it. The source tree is unchanged.
- Include all tracked paths by default, then exclude dependencies, build artifacts, caches, local `.env` files, key material, archives and binaries. These defaults work across project languages; use a narrower include policy when needed.
- Retain automation and IDE configuration, including `.github/`, `.idea/`, `.vscode/` and `.safe-repo-export/`, subject to filtering and sanitization.
- Remove all symlinks and omit submodule contents. This avoids link traversal and Windows symlink privilege requirements. A Git archive does not download submodules or Git LFS objects.
- Produce an output directory with a new, clean Git repository containing one sanitized commit and no remotes. ZIP/TAR archives contain the sanitized files and reports without `.git` internals.
- Verify `.safe-repo-export/MANIFEST.sha256`, create an optional deterministic archive and an adjacent `.sha256` file.
- Identical reruns leave the output and archive unchanged. Differing destinations require `--replace`. All destination conflicts are checked before installation; failures during replacement restore previous destinations.
- Use OS file locks implemented through Python's standard library. Hidden `.safe-repo-export.*.lock` files remain beside destinations so concurrent processes keep locking the same file. Locks release when a process exits.

Replacement uses atomic moves for each destination, with rollback on an ordinary failure or interrupt; it is not a crash-proof transaction across multiple files.

## Policies

In the target repository, write all six default list templates with one command:

```console
safe-repo-export init
```

The destination is `.safe-repo-export/` at the current Git repository root, even when called from a subdirectory. Before `git init`, it uses the current directory. Existing policy files are preserved. `init-policies` remains an alias. Override the destination with `safe-repo-export init --directory /path/to/project/.safe-repo-export`.

Without installation, `./init_lists.sh` is available at this toolkit's root; Windows can use `python scripts/init_lists.py`. To prepare another repository, call the script by its absolute path from that repository:

```console
/path/to/safe-repo-export/init_lists.sh
```

The script preserves the caller's directory. Commit the generated or edited policies before exporting them.

| File | Purpose |
|---|---|
| `safe-repo-export-include.list` | Case-sensitive paths/wildcards eligible for export |
| `safe-repo-export-exclude.list` | Paths/wildcards always removed |
| `safe-repo-export-redact-keys.list` | Case-insensitive regexes for sensitive configuration keys |
| `safe-repo-export-public-hosts.list` | Literal public hosts allowed to remain |
| `safe-repo-export-sanitize-skip.list` | Files exempt from redaction and built-in/Gitleaks scans |
| `safe-repo-export-gitleaks-ignore.list` | Gitleaks-only exact lines, full-line regexes or paths |

Precedence: explicit CLI file > `.safe-repo-export/` policy from the selected commit > bundled default. Each file replaces the corresponding default completely. Empty files mean empty lists; an empty include list retains no source files. Blank lines and `#` comments are ignored. Paths use `/` on every OS; `**/` also matches zero directories. No scan/redaction exemptions or Gitleaks ignores are enabled by default.

```console
safe-repo-export --repo /path/to/project --output /path/to/exports/project --include-list /path/to/include.list --exclude-list /path/to/exclude.list --redact-keys /path/to/keys.list
```

Example include list:

```text
src/**
tests/**
docs/**
pyproject.toml
package.json
.safe-repo-export/**
```

Bundled defaults live in `safe_repo_export/policies/` and are included in the wheel. Retained `.list` files are preserved byte-for-byte, including regex escapes and CRLF endings. They remain subject to path filtering and the built-in residual scan. Generated reports replace source files of the same names under `.safe-repo-export/`.

## Redaction and scanning

Configuration (YAML, JSON, XML, properties, INI, TOML and related formats) uses strict key redaction and deterministic pseudonyms for URLs, IPs, domains and contextual identifiers. Public-host exceptions apply to configuration URL keys as well as ordinary URLs. Credentials, URL userinfo/query strings and webhook fields remain redacted. Maven `pom.xml` uses a narrower policy: only explicit `http://` and `https://` URLs are treated as URLs; other element and attribute values are redacted when their keys match sensitive-key rules. Maven group IDs, Java class names, dependency coordinates and URL property references retain their original values. Public-host exceptions still apply to HTTP(S) URLs.

Source code uses narrower credential-literal rules for Java, JS/TS, Python, Go, Kotlin, Rust, C/C++, Shell and other supported extensions. Business constants, addresses, hashes and protocol topics are retained. Explicit credential literals and recognizable private-key blocks, JWTs, Telegram tokens, AWS access keys, GitHub tokens, Slack tokens and URLs containing user credentials are redacted. Keyword and regex definitions are preserved unless they contain a recognized actual secret format.

Standalone `.sql` files keep DDL/comments while removing data-mutating statements (`INSERT`, `REPLACE`, `UPDATE`, `DELETE`, `LOAD DATA`, `COPY`). MyBatis XML is not treated as a SQL dump. Source handling is lexical rather than a complete parser for every language.

A high-confidence built-in residual scan blocks export. Reports include rule names and locations, never matched values. Review `.safe-repo-export/EXPORT-REPORT.md`, retained configuration and policies before sharing; automatic rules cannot identify every business-specific secret.

Gitleaks, when available, adds a directory scan using `gitleaks dir`. Findings and scanner/report errors are advisory by default. `--require-gitleaks` requires installation; `--gitleaks-strict` also blocks on findings and scan/report errors. See the [official Gitleaks documentation](https://github.com/gitleaks/gitleaks#usage) for installation and supported commands.

Gitleaks ignore examples:

```text
# Exact complete line (outer whitespace is ignored)
assertEquals("example", result);
# Full-line Python regex
regex:assertEquals\(\s*"example"\s*,\s*result\s*\);
# Repository-relative path/wildcard
path:tests/fixtures/**
```

Ignore rules affect Gitleaks only; skip-list rules exempt matching files from both sanitization and scanning. Multiline findings are ignored only when every covered line matches. Direct Gitleaks commands do not read these toolkit policies.

## Private salt

The persistent salt defaults to `OUTPUT.pseudonym-salt`, beside the output. Reusing it produces stable pseudonyms and reproducible reruns. Set another location with `--salt-file`. It must be outside the source repository, output and archive destinations. It is never copied into the output or archive. New salt files are removed if the export fails; existing salts remain.

Unix permissions must be `0600`. Windows uses account/filesystem access controls rather than Unix mode-bit validation. Keep the salt private.

## Development and releases

```console
python -m unittest discover -s tests -v
python -m pip install build twine
python -m build
python -m twine check dist/*
python scripts/smoke_test.py --dist dist
```

The smoke check installs the wheel into the current Python environment and exercises it outside the source tree; use a virtual environment. The Tests and package workflow runs only when manually dispatched; ordinary pushes and pull requests do not trigger it. Release tags still trigger the publishing workflow, including tests and wheel installation on Windows/macOS/Linux with Python 3.10 and 3.14.

One-command version updates:

```console
python scripts/bump_version.py patch --dry-run
python scripts/bump_version.py patch
python scripts/bump_version.py minor --tag
python scripts/bump_version.py patch --push
```

Root Shell entries for version updates and releases:

```console
./bump_version.sh patch --dry-run
./bump_version.sh patch
./bump_version.sh patch --push
./commit_and_tag.sh v0.1.1 "Release v0.1.1"
```

`commit_and_tag.sh` accepts an explicit version (with or without `v`) and an optional message, then commits the version and creates the annotated tag. Add `--push` to push. Both Shell entries work when called from another directory and delegate to `scripts/bump_version.py`; they do not require local installation.

`--tag` implies a version commit. `--push` implies commit/tag and pushes the branch plus its `vX.Y.Z` tag atomically. `major`, `minor`, `patch` and explicit `X.Y.Z` versions are supported. Without Git flags, only the version source is updated. Publishing supports manual dispatch with an existing tag, or a push of a `v*` tag. Authentication and first-release setup are documented in [RELEASING.md](docs/RELEASING.md).
