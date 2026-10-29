# 默认规则说明 / Default rules

[中文 README](../README.zh-CN.md) · [English README](../README.md) · [更新记录 / Changelog](../CHANGELOG.md)

本文说明**随包提供的默认规则及代码内置判定**。自定义规则、文件类型、字段名都会改变结果；“地址不脱敏”“Redis key 不脱敏”不是全局豁免。
This guide describes bundled policies and built-in decisions. File type, field names and custom policies matter: addresses and Redis keys are not globally exempt.

## 1. 规则来源与执行顺序 / Selection and order

1. 选择输入：默认导出 `--ref`（默认 `HEAD`）；`--worktree` 使用已跟踪文件的当前磁盘内容，新文件先 `git add`。
2. 选择六份规则：显式 CLI 文件 > 仓库 `.safe-repo-export/` 对应文件 > 内置默认文件。默认模式读取所选 commit；`--worktree` 读取工作区规则。
3. 路径包含/排除 → 跳过规则 → 按文件类型脱敏 → 内置残留扫描 → 可选 Gitleaks → 报告/清单。

Input selection → policy selection → path filtering → skip rules → file-specific redaction → built-in scan → optional Gitleaks → reports.

每份自定义文件**完整替换**同类默认文件，不是追加。空行及 `#` 开头行忽略；路径区分大小写，统一使用 `/`，`**/` 也能匹配零层目录。`init` 保留已有文件，因此升级工具后，已有仓库规则**不会自动合并新版默认项**。
Overrides replace a policy completely. Blank/comment lines are ignored. Paths are case-sensitive and use `/`; `**/` also matches zero directories. `init` never overwrites existing files, so upgrading does not merge new defaults into existing repository policies.

## 2. 六份默认 list / Six bundled policies

实际文件均位于 [safe_repo_export/policies](../safe_repo_export/policies/)，下表链接到对应文件；以这些文件内容为准。
The linked files are the source of truth.

| 默认文件 / Policy | 默认行为 / Default behavior | 对应参数 / CLI override |
|---|---|---|
| [include](../safe_repo_export/policies/safe-repo-export-include.list) | `**`：所有输入路径均有资格参与导出 / All input paths eligible | `--include-list` |
| [exclude](../safe_repo_export/policies/safe-repo-export-exclude.list) | 移除依赖、产物、本地状态、密钥文件等 / Remove dependencies, outputs, local state and key files | `--exclude-list` |
| [redact-keys](../safe_repo_export/policies/safe-repo-export-redact-keys.list) | 配置敏感键正则 / Configuration sensitive-key regexes | `--redact-keys` |
| [public-hosts](../safe_repo_export/policies/safe-repo-export-public-hosts.list) | 公共主机白名单 / Public-host allowlist | `--public-hosts` |
| [sanitize-skip](../safe_repo_export/policies/safe-repo-export-sanitize-skip.list) | 默认无生效项 / Empty by default | `--skip-list` |
| [gitleaks-ignore](../safe_repo_export/policies/safe-repo-export-gitleaks-ignore.list) | 默认无生效项 / Empty by default | `--gitleaks-ignore` |

### include / exclude

- include 只表示“候选”，exclude 仍优先移除；空 include 不保留源文件。Include does not override exclude; an empty include retains no source files.
- 默认排除目录：`.git`、`target`、`build`、`dist`、`out`、`node_modules`、`vendor`、`__pycache__`、`.pytest_cache`、`.mypy_cache`、`.ruff_cache`、`.tox`、`.venv`、`venv`、`.next`、`.nuxt`、`coverage`、`*.egg-info`。
- 默认排除本地文件：`.DS_Store`、`Thumbs.db`、`*.pyc`、`*.pyo`、`*.log`、`*.log.*`、`.env`、`.env.local`、`.env.*.local`。**不是所有 `.env.*` 都默认排除**，模板仍可参与过滤与脱敏。
- 默认排除密钥/证书：`certs/**`、`*.p12`、`*.pfx`、`*.jks`、`*.keystore`、`*.pem`、`*.key`、`*.der`、`*.crt`、`*.cer`、`*.csr`。
- 默认排除产物：`*.tvc`、`*.boc`、`*.bin`、`*.class`、`*.jar`、`*.war`、`*.zip`、`*.tar`、`*.tar.gz`、`*.tgz`、`*.whl`、`*.exe`、`*.dll`、`*.so`、`*.dylib`、`*.min.js`、`*.min.css`、`*.map`。
- 未命中排除规则的文件仍需通过文本判定；不符合文本判定的文件移除。正常导出移除软链接，不复制子模块内容。`.github`、`.idea`、`.vscode` 并非整体排除。

The lists above summarize default exclusions. Remaining files still undergo text detection. Normal export omits symlinks and submodule contents; IDE/automation directories are not excluded as a whole.

### redact-keys：配置字段 / Configuration keys

键名先把 camelCase 转为下划线，再转小写，然后用正则搜索；多数规则要求词边界是开头/结尾或 `. _ -`。
Keys are normalized from camelCase to snake_case and lowercased before regex matching; most rules use start/end or `. _ -` boundaries.

| 类别 / Category | 默认敏感键示例 / Examples |
|---|---|
| 密码、凭据 / Credentials | `password`, `passwd`, `pwd`, `secret`, `credential`, `credentials` |
| 密钥 / Keys | `apiKey`, `accessKey`, `secretKey`, `authKey`, `privateKey`, `keystore`, `signingKey`, `aesKey`, `desKey`, `rsaKey`, `encryptKey`, `spendKey`, `viewKey`, `key`, `key1` |
| 助记词 / Mnemonics | `mnemonic`, `seed`, `seedPhrase` |
| 令牌、鉴权 / Tokens/auth | `token`, `accessToken`, `refreshToken`, `authToken`, `jobAccessToken`, `authorization`, `basicAuth`, `bearer` |
| 机器人 / Bots | `webhook`, `hookUrl`, `botToken`, `chatId`, `verificationToken` |
| 网络连接 / Connections | `rpcUser`, `rpcPassword`, `nodeRpc`, `walletRpc`, `rpcUrl`, `rpcUri`, `rpcEndpoint`, `rpcHost`, `serverAddr`, `serverAddress`, `url`, `uri`, `endpoint`, `host`, `hostname`, `jdbcUrl` |
| 身份、拓扑 / Identity/topology | `username`, `userName`, `namespace`, `dataId`, `group`, `accountId`, `userId`, `tenantId`, `clientId`, `clientSecret`, `appId`, `appSecret` |
| 地址 / Addresses | `address`, `walletAddress`, `hotAddress`, `coldAddress`, `riskAddress`, `feeAddress`, `collectionAddress`, `recipient`, `sender`, `owner` |
| 子键 / Subkeys | `subKey` 等；以 `redis.`、`redis_`、`redis-` 开头的名称不命中最后那条 subkey 规则 / Redis-prefixed names are excluded from the final subkey rule |

替换不一定都是 `REDACTED_SECRET`：网络字段可生成安全 URL，身份/地址可生成稳定假名，拓扑字段可变为 `REDACTED_TOPOLOGY`。匹配敏感键会先于普通值格式处理。
Replacement depends on the key: safe URLs, stable identifier pseudonyms or topology placeholders may be used. Sensitive-key handling precedes generic value-format handling.

**源码例外：** Java/Python/JS 等源码走内置 `SOURCE_CREDENTIAL_RE`，**不直接套用自定义 `redact-keys.list`**。仅修改该 list 不会把普通源码 `key1`、`sender` 自动变成敏感字段。
**Source exception:** source files use built-in credential rules rather than directly applying the configurable key list. Changing that list alone does not make ordinary source `key1` or `sender` assignments sensitive.

### public-hosts

默认包含 GitHub、Maven Central、阿里云 Maven、Spring、Gradle、PyPI、npm、NuGet、Go 包代理及常见文档服务，例如 `repo.maven.apache.org`、`maven.aliyun.com`、`pypi.org`、`registry.npmjs.org`、`mybatis.org`。完整清单见 [public-hosts.list](../safe_repo_export/policies/safe-repo-export-public-hosts.list)。
The default list includes common package repositories and documentation services; see the linked file for all entries.

- 填**主机名**，不填协议、端口、路径或 `*`。匹配该主机及其子域名，忽略大小写和末尾点。Entries are hostnames, not URLs/globs; matching includes subdomains.
- 配置/POM 中 HTTP(S) URL 只有在主机命中、无 userinfo、无 query 时才可原样保留。带 `?token=...` 或 `user:password@` 仍替换；`password`、`webhook` 等敏感字段不会因为值是公共 URL 而豁免。
- 白名单不是文件免扫描，也不让私钥/token 免脱敏。源码普通 URL 本身可能保留，见下文；不能用这里的配置规则推断源码行为。

Allowlisting is not a scan exemption. Configuration/POM URLs with userinfo/query strings, or URLs in credential/webhook fields, are still redacted. Source URL handling differs below.

### sanitize-skip / gitleaks-ignore

| 规则 / Policy | 写法 / Syntax | 影响 / Effect |
|---|---|---|
| sanitize-skip | `tests/fixtures/**` | 匹配文件跳过脱敏、内置扫描、Gitleaks；仍受 include/exclude 限制 / Skip redaction and both scans, but not path filtering |
| gitleaks-ignore | 完整原始行 / Full original line | 仅忽略匹配行的 Gitleaks 发现 / Gitleaks-only line ignore |
| gitleaks-ignore | `regex:assertEquals\(.*\);` | Python 正则匹配整行；不是子串搜索 / Python regex full-line match |
| gitleaks-ignore | `path:tests/fixtures/**` | 仅忽略匹配路径的 Gitleaks 发现 / Gitleaks-only path ignore |

两份文件默认只有注释，无默认豁免。多行 Gitleaks 发现需覆盖的每一行都匹配。直接运行 Gitleaks 不读取本工具 list。
Both are empty by default. Every covered line must match for multiline Gitleaks findings. Direct Gitleaks commands do not read these policies.

## 3. 源码 vs 配置：哪些保留？ / Source vs configuration

下表描述普通字段/字面量；明确的敏感字段或可识别真实凭据优先处理。
These examples concern ordinary fields/literals; credential fields and recognizable secrets take precedence.

| 内容 / Content | Java/Python/JS 等源码 / Source | YAML/JSON/普通 XML/文本等 / Configuration and generic text |
|---|---|---|
| 普通 Redis 缓存 key，如 `REDIS_SUBKEY = "cache:balance"` | 保留 / Preserve | `redis.subkey=cache:balance` 不命中默认 subkey 规则；但其他值格式规则仍适用 / Subkey rule excluded, other rules still apply |
| `redis.key`、`redis.password` | 普通 key 名可保留；password 仍敏感 / Ordinary key may remain; password is sensitive | `redis.key` 命中通用 key，`redis.password` 命中 password，均无 Redis 全局豁免 / Both match sensitive-key rules |
| `0x` + **40 个十六进制字符**（20 字节 EVM 地址） | 普通地址常量保留 / Preserve ordinary address constants | 通用格式规则生成另一个相同长度的 `0x…`；敏感键还可能改为 identifier / Pseudonymize; sensitive keys may produce identifiers instead |
| `0x` + **64 个十六进制字符**（32 字节哈希/topic） | 普通 hash/topic 保留 / Preserve ordinary hashes/topics | 通用格式规则生成稳定的同长度 `0x…` / Stable same-length pseudonym |
| 普通 Base58 字符串 | 保留 / Preserve | 引号内 26–64 字符，且同一行出现 address/wallet/tx 等上下文时替换 / Quoted 26–64 chars plus address/wallet/tx context triggers replacement |
| 普通 HTTP(S) URL / URL without credentials | 普通字段保留；字段为凭据时仍可能替换 / Preserve ordinary values, not credential fields | 非白名单 URL 替换；白名单按前述条件保留 / Redact unless allowed under public-host rules |
| URL 中的 `user:password@` | 替换 / Redact | 替换 / Redact |
| 普通源码 URL 的查询参数 / Source URL query | 普通 URL **不会仅因 query 自动替换** / Query alone does not trigger source redaction | query 导致不能使用 URL 白名单豁免 / Query disqualifies allowlist exemption |
| 私网 IPv4、email、带引号的多段域名 / Private IPv4, email, quoted dotted domain | 不做宽泛网络脱敏 / No broad network redaction | 按通用规则处理；公网 IPv4 需网络上下文，白名单主机/IP有例外 / Generic rules; public IPv4 requires network context, with allowlist exceptions |
| `jdbc:`、`redis://`、`mongodb://`、`amqp://` 等 DSN | 普通源码字面量不做通用 DSN 替换 / No generic DSN rule | 命中的 DSN 替换为 `REDACTED_CONNECTION_URI` / Matching DSNs replaced |
| `"secret", "section"` 普通词表 | 保留；与 `.put("secret", value)`、`{"secret": value}` 区分 / Preserve lists, distinguish actual key/value syntax | 不作为配置免脱敏保证 / No general config exemption |
| `PASSWORD_PATTERN`、`SECRET_KEYWORDS` 等定义 | 保留定义，若包含可识别 token 仍替换 / Preserve definitions unless recognizable secrets occur | 没有通用“定义变量”豁免 / No general metadata-name exemption |

“0x40hex”在这里指 `0x` 后接 **40 个字符**，不是 `0x40` 个字符。
Here “40 hex” means 40 hexadecimal characters after `0x`, not hexadecimal 0x40 characters.

源码识别是词法规则，不是每种语言的完整 AST；源码文件名单见 [engine.py](../safe_repo_export/engine.py) 的 `SOURCE_EXTENSIONS` / `SOURCE_NAMES`。
Source recognition is lexical, not a full AST parser. See the built-in extension/name lists in `engine.py`.

## 4. YAML、JSON 与 POM 的专门行为 / Format-specific handling

### YAML

以下内容按当前 YAML 行处理规则原样保留 / These scalar forms are preserved:

```yaml
seed-index: 1
seed-index-negative: -2
seed-ratio: 1.25
seed-enabled: true
seed-empty: null
create-address:
password: " "
secret: ' '
```

未加引号的数字保持原值和类型；引号内 `"123"` 是字符串，敏感键仍会替换。空值、纯空格、空引号、仅含空格的引号值不替换。非空敏感值替换时保留冒号后空格、行尾注释及 CRLF。
Unquoted numbers retain value/type. Quoted `"123"` is a string and can be redacted under sensitive keys. Empty/whitespace-only values are preserved; scalar replacements retain colon spacing, comments and CRLF.

这不是“所有数字在整个后续流水线均免脱敏”：值若满足地址/IP等通用格式，仍可能被后续格式规则替换。YAML 处理是行级规则，不保证完整支持任意多行、anchor、flow 等语法。
This is not a global numeric exemption: later address/IP format rules can still apply. YAML handling is line-based, not full support for arbitrary multiline, anchor or flow syntax.

### JSON

JSON 递归按键处理。命中敏感键的整数/浮点数替换为 `0` / `0.0`，布尔替换为 `false`，`null` 保持 `null`；字符串使用键对应占位符。**不等同于 YAML 的数字原值保留策略**。发生修改时可能重新缩进序列化。
JSON is processed recursively. Sensitive integer/float values become `0`/`0.0`, booleans become `false`, null stays null. This differs from YAML’s numeric preservation. Modified JSON may be reserialized with indentation.

### pom.xml

- 不走通用裸域名/IP/EVM 格式替换；只有明确的 `http://`、`https://` 内容作为 URL。
- 叶子元素和属性按敏感键处理；普通 URL/host 等网络键不因值是 Maven 引用而替换，敏感凭据键仍处理。
- `groupId` 元素单独保护，即使自定义 groupId 敏感键也保留。普通 `artifactId`、`version`、Java 类名本身不脱敏；自定义敏感键可以改变其他字段行为。
- 保留示例：`implementation="org.apache.maven.plugins.shade.resource.ManifestResourceTransformer"`、`<mainClass>com.example.Main</mainClass>`、`<url>${repository.url}</url>`。

POM avoids generic bare-domain/IP/EVM rules. Explicit HTTP(S) URLs and sensitive leaf-element/attribute values are handled. `groupId` is protected explicitly; ordinary coordinates, class names and URL property references remain intact. Custom key rules may affect other fields.

## 5. 其他内置规则与扫描 / Other built-in rules and scanning

- 私钥块、JWT、AWS access key、GitHub/Slack/Telegram token 等可识别格式有独立规则，不能只靠删除 `redact-keys` 某一行来关闭。
- 保留的 `.list` 文件字节不修改，含正则转义和 CRLF；它们仍可能被内置残留扫描发现问题并阻止导出。
- 独立 `.sql` 保留 DDL/注释，移除行首匹配的数据语句 `INSERT`、`REPLACE`、`UPDATE`、`DELETE`、`LOAD DATA`、`COPY`；不是完整 SQL 解析器。MyBatis XML 不按 SQL dump 删除数据语句。
- 内置扫描阻止高可信残留；Gitleaks 默认提示，`--require-gitleaks` 要求安装，`--gitleaks-strict` 还阻止发现或扫描/报告错误。
- 假名由私有盐稳定生成。同一输入/盐得到稳定结果，但不同字段或规则可能使用不同假名格式。示例输出不是有效钱包或真实服务。

Recognizable-secret rules are independent of configurable key regexes. Retained list files remain byte-identical but are scanned. SQL handling is lexical. Built-in findings block export; Gitleaks is advisory unless strict. Pseudonyms are stable for the same salt/input, not real service/wallet credentials.

## 6. 如何调整 / Customization

```sh
safe-repo-export init
# 编辑目标仓库 .safe-repo-export/ 中的相应文件 / Edit repository policies
safe-repo-export --worktree --output ../sanitized --replace
# 或提交规则后按 HEAD 导出 / Or commit policies and export HEAD
```

- 只想排除文件：改 exclude。只想保留更小范围：改 include。
- 需要新增配置敏感键：改 redact-keys；源码内置识别需改代码。
- 只想保留公共 HTTP(S) 服务：改 public-hosts；已有白名单还需检查子域名范围。
- 某测试被 Gitleaks 误报：优先考虑 gitleaks-ignore，避免把整个文件加入 sanitize-skip。
- 查看输出 `.safe-repo-export/EXPORT-REPORT.md`，结合原始差异复核；普通词表、类型等例外不是业务数据全局安全的保证。

Use exclude/include for paths, redact-keys for config fields, public-hosts for public services and Gitleaks-only ignores for scanner false positives. Source credential recognition requires code changes. Review the export report and diff before sharing.
