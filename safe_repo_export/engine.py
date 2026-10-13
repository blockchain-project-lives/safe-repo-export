#!/usr/bin/env python3
"""Filter, redact and validate a Git-exported source tree for code analysis.

Only Python's standard library is required. Reports never include matched values.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import stat
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, NoReturn
from urllib.parse import urlsplit


TEXT_EXTENSIONS = {
    ".java", ".kt", ".kts", ".xml", ".yml", ".yaml", ".properties",
    ".json", ".sql", ".md", ".txt", ".html", ".css", ".js", ".py",
    ".sh", ".proto", ".conf", ".cfg", ".ini", ".gradle", ".toml",
}

TEXT_NAMES = {"Dockerfile", "Jenkinsfile", "Makefile", "pom.xml"}

URL_RE = re.compile(r"\bhttps?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", re.I)
DSN_RE = re.compile(
    r"\b(?:jdbc:[a-z0-9]+|redis|rediss|mongodb(?:\+srv)?|amqp|amqps)://[^\s\"'<>]+",
    re.I,
)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
EVM_HASH_RE = re.compile(r"(?<![0-9A-Fa-f])0x[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
EVM_ADDRESS_RE = re.compile(r"(?<![0-9A-Fa-f])0x[0-9A-Fa-f]{40}(?![0-9A-Fa-f])")
JWT_RE = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])")
PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.S,
)
QUOTED_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>\b(?P<key>[A-Za-z_][A-Za-z0-9_.-]{0,100})\s*=\s*)"
    r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)"
)
BASE58_LITERAL_RE = re.compile(r"(?P<quote>[\"'])(?P<value>[1-9A-HJ-NP-Za-km-z]{26,64})(?P=quote)")
DOMAIN_LITERAL_RE = re.compile(
    r"(?P<quote>[\"'])(?P<value>(?:[A-Za-z0-9-]+\.){2,}[A-Za-z]{2,})(?P=quote)"
)

CONTEXTUAL_IDENTIFIER_RE = re.compile(
    r"address|wallet|recipient|sender|owner|mint|account|tx[_-]?id|transaction[_-]?hash|tx[_-]?hash",
    re.I,
)
NETWORK_CONTEXT_RE = re.compile(r"url|uri|host|rpc|node|server|endpoint|address|jdbc|redis|mysql|http|grpc", re.I)

RESIDUAL_RULES = {
    "private-key-block": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "telegram-bot-token": re.compile(r"(?<!\d)\d{8,12}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])"),
    "jwt": JWT_RE,
    "url-userinfo": re.compile(r"\bhttps?://[^\s/:]+:[^\s/@]+@", re.I),
    "unredacted-secret-literal": re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|mnemonic|webhook)\b"
        r"\s*[:=]\s*[\"'](?!REDACTED|\$\{|<)[^\"']{4,}[\"']"
    ),
}

# Source files use credential-only rules, never broad identifier/network rules.
SOURCE_EXTENSIONS = {
    ".java", ".kt", ".kts", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
    ".scala", ".rb", ".php", ".sh", ".bash", ".groovy", ".gradle", ".proto",
}
SOURCE_NAMES = {"Dockerfile", "Jenkinsfile", "Makefile"}
SOURCE_CREDENTIAL_RE = re.compile(
    r"(?:^|[._-])(?:password|passwd|pwd|secret|credential|credentials|"
    r"api[._-]?key|access[._-]?key|secret[._-]?key|auth[._-]?key|"
    r"private[._-]?key|signing[._-]?key|spend[._-]?key|view[._-]?key|"
    r"access[._-]?token|refresh[._-]?token|auth[._-]?token|bot[._-]?token|"
    r"client[._-]?secret|app[._-]?secret|mnemonic|seed[._-]?phrase)(?:$|[._-])", re.I,
)
# Consume whole literals before looking for assignments, so text embedded
# inside another string is never mistaken for an actual source assignment.
SOURCE_TOKEN_RE = re.compile(
    r'(?P<comment>//[^\n]*|/\*.*?\*/|\#[^\n]*)|'
    r'(?P<literal>"""(?:\\.|(?!""").)*"""|'
    + "'''(?:\\\\.|(?!''').)*'''|"
    + r'"(?:\\.|[^"\\])*"|'
    + r"'(?:\\.|[^'\\])*'|`[^`]*`)", re.S,
)


def is_source_file(path: Path) -> bool:
    return path.suffix.lower() in SOURCE_EXTENSIONS or path.name in SOURCE_NAMES


def is_source_credential_key(key: str) -> bool:
    normalized = normalize_key(key)
    # Keyword/regex definitions describe secrets; their values are not credentials.
    if re.search(
        r"(?:^|[._-])(?:keywords?|patterns?|regex(?:es)?|field[._-]?names?|key[._-]?names?)$",
        normalized,
    ):
        return False
    return bool(SOURCE_CREDENTIAL_RE.search(normalized))


def redact_source_text(text: str, pseudonymizer: "Pseudonymizer") -> str:
    def known_secrets(value: str) -> str:
        for name, pattern, replacement in (
            ("private_key_block", PRIVATE_KEY_BLOCK_RE, "REDACTED_PRIVATE_KEY_BLOCK"),
            ("jwt", JWT_RE, "REDACTED_JWT"),
            ("telegram_bot_token", RESIDUAL_RULES["telegram-bot-token"], "REDACTED_TELEGRAM_BOT_TOKEN"),
            ("aws_access_key", RESIDUAL_RULES["aws-access-key"], "REDACTED_AWS_ACCESS_KEY"),
            ("github_token", RESIDUAL_RULES["github-token"], "REDACTED_GITHUB_TOKEN"),
            ("slack_token", RESIDUAL_RULES["slack-token"], "REDACTED_SLACK_TOKEN"),
        ):
            value, count = pattern.subn(replacement, value)
            pseudonymizer.counts[name] += count
        def credential_url_sub(match: re.Match[str]) -> str:
            url = match.group(0)
            try:
                parsed = urlsplit(url)
            except ValueError:
                return url
            if parsed.username is not None or parsed.password is not None:
                return pseudonymizer.url(url)
            return url
        return URL_RE.sub(credential_url_sub, value)

    def token_sub(match: re.Match[str]) -> str:
        token = match.group(0)
        if match.group("comment") is not None:
            return known_secrets(token)
        quote = token[:3] if token.startswith(('"""', "'''")) else token[0]
        value = token[len(quote):-len(quote)]
        # A bounded statement prefix avoids quadratic scans on large files.
        prefix = text[max(0, match.start() - 512):match.start()]
        key = None
        assignment = re.search(
            r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*(?::\s*[A-Za-z_][A-Za-z0-9_.\[\] |]*)?\s*(?::=|=(?!=))\s*$", prefix
        )
        go_declaration = re.search(r"\b(?:var|const)\s+([A-Za-z_]\w*)\s+string\s*=\s*$", prefix)
        # Commas pair keys with values only in explicit .put calls.
        # Object/dict entries require a colon; list items are independent values.
        put_value = re.search(
            r'\.put\(\s*["\']([A-Za-z_][A-Za-z0-9_.-]*)["\']\s*,\s*$', prefix
        )
        keyed_value = re.search(
            r'[,{]\s*["\']([A-Za-z_][A-Za-z0-9_.-]*)["\']\s*:\s*$', prefix
        )
        if go_declaration:
            key = go_declaration.group(1)
        elif assignment:
            key = assignment.group(1)
        elif put_value:
            key = put_value.group(1)
        elif keyed_value:
            key = keyed_value.group(1)
        if key and is_source_credential_key(key) and value.strip():
            # Preserve environment references, placeholders and dynamic templates.
            if not re.match(r"^(?:REDACTED_|\$\{|<[^>]+>$)", value):
                if "${" not in value and "\n" not in value:
                    pseudonymizer.counts["source_credential_literal"] += 1
                    return quote + "REDACTED_SECRET" + quote
        return quote + known_secrets(value) + quote

    return SOURCE_TOKEN_RE.sub(token_sub, text)


DML_START_RE = re.compile(r"^\s*(INSERT|REPLACE|UPDATE|DELETE|LOAD\s+DATA|COPY)\b", re.I)


def fail(message: str, code: int = 2) -> "NoReturn":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def read_list(path: Path) -> list[str]:
    result: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        result.append(line)
    return result


def match_pattern(relative: str, pattern: str) -> bool:
    # Preserve leading dots: .github and github are different directories.
    while relative.startswith("./"):
        relative = relative[2:]
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if fnmatch.fnmatchcase(relative, pattern) or PurePosixPath(relative).match(pattern):
        return True
    # **/ also matches zero directories, including a root .env or build/.
    return pattern.startswith("**/") and match_pattern(relative, pattern[3:])


def matches_any(relative: str, patterns: Iterable[str]) -> bool:
    return any(match_pattern(relative, pattern) for pattern in patterns)


def normalize_key(key: str) -> str:
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return re.sub(r"\s+", "_", key).lower()


def is_sensitive_key(key: str, patterns: list[re.Pattern[str]]) -> bool:
    normalized = normalize_key(key)
    return any(pattern.search(normalized) for pattern in patterns)


def is_text_file(path: Path) -> bool:
    if path.name in TEXT_NAMES or path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        data = path.read_bytes()[:8192]
    except OSError:
        return False
    return b"\x00" not in data


def clean_empty_directories(root: Path) -> None:
    for directory, dirnames, filenames in os.walk(root, topdown=False):
        path = Path(directory)
        if path == root:
            continue
        try:
            if not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass


def filter_tree(root: Path, includes: list[str], excludes: list[str], counts: Counter[str]) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            if os.path.isabs(target) or ".." in PurePosixPath(target).parts:
                path.unlink()
                counts["unsafe_symlink_removed"] += 1
                continue
            if not matches_any(relative, includes) or matches_any(relative, excludes):
                path.unlink()
                counts["path_removed"] += 1
            continue
        if not path.is_file():
            continue
        if not matches_any(relative, includes) or matches_any(relative, excludes):
            path.unlink()
            counts["path_removed"] += 1
            continue
        if not is_text_file(path):
            path.unlink()
            counts["binary_removed"] += 1
            continue
        counts["files_retained"] += 1
    clean_empty_directories(root)


class Pseudonymizer:
    def __init__(self, salt: bytes, public_hosts: set[str]):
        self.salt = salt
        self.public_hosts = {host.lower().rstrip(".") for host in public_hosts}
        self.counts: Counter[str] = Counter()

    def digest(self, label: str, value: str, length: int = 16) -> str:
        payload = f"{label}\0{value}".encode("utf-8", errors="replace")
        return hmac.new(self.salt, payload, hashlib.sha256).hexdigest()[:length]

    def host_is_public(self, host: str) -> bool:
        candidate = host.lower().rstrip(".")
        return any(candidate == item or candidate.endswith("." + item) for item in self.public_hosts)

    def is_public_url(self, value: str) -> bool:
        try:
            parsed = urlsplit(value)
            host = parsed.hostname or ""
        except ValueError:
            return False
        return bool(
            parsed.scheme.lower() in {"http", "https"}
            and host and self.host_is_public(host)
            and parsed.username is None and parsed.password is None
            and not parsed.query
        )

    def url(self, value: str) -> str:
        if self.is_public_url(value):
            return value
        self.counts["url"] += 1
        return f"https://service-{self.digest('url', value, 10)}.example.invalid/REDACTED"

    def ip(self, value: str) -> str:
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            return value
        if str(parsed) in self.public_hosts:
            return value
        number = int(self.digest("ip", value, 4), 16) % 254 + 1
        self.counts["ip"] += 1
        return f"192.0.2.{number}"

    def evm_address(self, value: str) -> str:
        self.counts["evm_address"] += 1
        return "0x" + self.digest("evm-address", value.lower(), 40)

    def evm_hash(self, value: str) -> str:
        self.counts["evm_hash"] += 1
        return "0x" + self.digest("evm-hash", value.lower(), 64)

    def identifier(self, value: str, label: str = "identifier") -> str:
        self.counts[label] += 1
        return f"REDACTED_{label.upper()}_{self.digest(label, value, 12)}"

    def email(self, value: str) -> str:
        if value.lower().endswith("@example.invalid"):
            return value
        self.counts["email"] += 1
        return f"user-{self.digest('email', value, 10)}@example.invalid"

    def domain(self, value: str) -> str:
        if self.host_is_public(value):
            return value
        self.counts["domain"] += 1
        return f"service-{self.digest('domain', value, 10)}.example.invalid"


def replacement_for_key(key: str, original: Any, pseudonymizer: Pseudonymizer) -> Any:
    normalized = normalize_key(key)
    if isinstance(original, bool):
        return False
    if isinstance(original, int):
        return 0
    if isinstance(original, float):
        return 0.0
    if original is None:
        return None
    if isinstance(original, list):
        return [replacement_for_key(key, item, pseudonymizer) for item in original]
    if isinstance(original, dict):
        return {nested_key: replacement_for_key(key, value, pseudonymizer) for nested_key, value in original.items()}
    value = str(original)
    if re.search(r"url|uri|endpoint|host|jdbc", normalized):
        candidate = value.strip()
        if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"\"", "'"}:
            candidate = candidate[1:-1]
        # Public endpoints are not credentials. Never whitelist credential/webhook
        # fields just because their value happens to be a public URL.
        credential_field = SOURCE_CREDENTIAL_RE.search(normalized) or re.search(
            r"(?:^|[._-])(?:token|webhook|authorization|bearer)(?:$|[._-])", normalized
        )
        if not credential_field and pseudonymizer.is_public_url(candidate):
            return candidate
        if not credential_field and re.search(r"(?:^|[._-])(?:host|hostname)$", normalized):
            if pseudonymizer.host_is_public(candidate):
                return candidate
        return "https://service.example.invalid/REDACTED"
    if re.search(r"address|wallet|recipient|sender|owner|account|user_id|tenant_id", normalized):
        return pseudonymizer.identifier(value, "identifier")
    if re.search(r"username|user_name", normalized):
        return "REDACTED_USERNAME"
    if re.search(r"namespace|data_id|group", normalized):
        return "REDACTED_TOPOLOGY"
    return "REDACTED_SECRET"


def redact_json(value: Any, key_patterns: list[re.Pattern[str]], pseudonymizer: Pseudonymizer) -> tuple[Any, bool]:
    changed = False
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if is_sensitive_key(str(key), key_patterns):
                output[key] = replacement_for_key(str(key), item, pseudonymizer)
                pseudonymizer.counts["sensitive_key"] += 1
                changed = True
            else:
                output[key], nested_changed = redact_json(item, key_patterns, pseudonymizer)
                changed = changed or nested_changed
        return output, changed
    if isinstance(value, list):
        output_list = []
        for item in value:
            sanitized, nested_changed = redact_json(item, key_patterns, pseudonymizer)
            output_list.append(sanitized)
            changed = changed or nested_changed
        return output_list, changed
    if isinstance(value, str):
        sanitized = redact_generic_text(value, key_patterns, pseudonymizer)
        return sanitized, sanitized != value
    return value, False


def replace_config_lines(text: str, key_patterns: list[re.Pattern[str]], pseudonymizer: Pseudonymizer) -> str:
    output: list[str] = []
    config_re = re.compile(r"^(?P<indent>\s*(?:#\s*)?)(?P<key>[A-Za-z0-9_.-]{1,160})(?P<sep>\s*[:=]\s*)(?P<value>.*)$")
    xml_re = re.compile(r"<(?P<key>[A-Za-z0-9_.:-]+)>(?P<value>.*?)</(?P=key)>", re.I)
    for line in text.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        match = config_re.match(body)
        if match and is_sensitive_key(match.group("key"), key_patterns):
            replacement = replacement_for_key(match.group("key"), match.group("value"), pseudonymizer)
            body = f"{match.group('indent')}{match.group('key')}{match.group('sep')}\"{replacement}\""
            pseudonymizer.counts["sensitive_key"] += 1
        else:
            def xml_sub(xml_match: re.Match[str]) -> str:
                key = xml_match.group("key")
                if not is_sensitive_key(key, key_patterns):
                    return xml_match.group(0)
                pseudonymizer.counts["sensitive_key"] += 1
                replacement = replacement_for_key(key, xml_match.group("value"), pseudonymizer)
                return f"<{key}>{replacement}</{key}>"
            body = xml_re.sub(xml_sub, body)
        output.append(body + ending)
    return "".join(output)


def strip_sql_dml(text: str) -> tuple[str, int]:
    output: list[str] = []
    removed = 0
    dropping = False
    copy_data = False
    quote: str | None = None

    def statement_ends(line: str) -> bool:
        nonlocal quote
        escaped = False
        for char in line:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == ";":
                return True
        return False

    for line in text.splitlines(keepends=True):
        if copy_data:
            if line.strip() == r"\.":
                copy_data = False
            continue
        if not dropping and DML_START_RE.match(line):
            keyword = DML_START_RE.match(line).group(1).upper()
            removed += 1
            output.append(f"-- REDACTED: {keyword} data statement removed by project export\n")
            if keyword == "COPY" and re.search(r"\bFROM\s+STDIN\b", line, re.I):
                copy_data = True
                dropping = False
                quote = None
            else:
                dropping = not statement_ends(line)
            continue
        if dropping:
            if statement_ends(line):
                dropping = False
                quote = None
            continue
        output.append(line)
    return "".join(output), removed


def redact_generic_text(text: str, key_patterns: list[re.Pattern[str]], pseudonymizer: Pseudonymizer) -> str:
    if PRIVATE_KEY_BLOCK_RE.search(text):
        text, count = PRIVATE_KEY_BLOCK_RE.subn("REDACTED_PRIVATE_KEY_BLOCK", text)
        pseudonymizer.counts["private_key_block"] += count
    text, count = JWT_RE.subn("REDACTED_JWT", text)
    pseudonymizer.counts["jwt"] += count

    # Match the residual scanner regardless of configuration key naming.
    text, count = RESIDUAL_RULES["telegram-bot-token"].subn(
        "REDACTED_TELEGRAM_BOT_TOKEN", text
    )
    pseudonymizer.counts["telegram_bot_token"] += count

    def assignment_sub(match: re.Match[str]) -> str:
        key = match.group("key")
        if not is_sensitive_key(key, key_patterns):
            return match.group(0)
        replacement = replacement_for_key(key, match.group("value"), pseudonymizer)
        pseudonymizer.counts["sensitive_assignment"] += 1
        return f"{match.group('prefix')}{match.group('quote')}{replacement}{match.group('quote')}"

    text = QUOTED_ASSIGNMENT_RE.sub(assignment_sub, text)

    # Literal map/header values can contain secrets without an assignment.
    put_re = re.compile(
        r'(?P<prefix>\.put\(\s*"(?P<key>[A-Za-z0-9_.-]{1,100})"\s*,\s*)'
        r'"(?P<value>(?:\\.|[^"\\])*)"'
    )

    def put_sub(match: re.Match[str]) -> str:
        key = match.group("key")
        if not is_sensitive_key(key, key_patterns):
            return match.group(0)
        replacement = replacement_for_key(key, match.group("value"), pseudonymizer)
        pseudonymizer.counts["sensitive_map_value"] += 1
        return f'{match.group("prefix")}"{replacement}"'

    text = put_re.sub(put_sub, text)

    text, count = DSN_RE.subn("REDACTED_CONNECTION_URI", text)
    pseudonymizer.counts["connection_uri"] += count
    def url_sub(match: re.Match[str]) -> str:
        value = match.group(0)
        trailing = ""
        while value and value[-1] in ".,;:)]}":
            trailing = value[-1] + trailing
            value = value[:-1]
        return pseudonymizer.url(value) + trailing

    text = URL_RE.sub(url_sub, text)
    text = EMAIL_RE.sub(lambda match: pseudonymizer.email(match.group(0)), text)
    text = EVM_HASH_RE.sub(lambda match: pseudonymizer.evm_hash(match.group(0)), text)
    text = EVM_ADDRESS_RE.sub(lambda match: pseudonymizer.evm_address(match.group(0)), text)

    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        def contextual_ip_sub(match: re.Match[str]) -> str:
            value = match.group(0)
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                return value
            if parsed.is_private or NETWORK_CONTEXT_RE.search(line):
                return pseudonymizer.ip(value)
            return value

        line = IPV4_RE.sub(contextual_ip_sub, line)
        if CONTEXTUAL_IDENTIFIER_RE.search(line):
            line = BASE58_LITERAL_RE.sub(
                lambda match: f"{match.group('quote')}{pseudonymizer.identifier(match.group('value'))}{match.group('quote')}",
                line,
            )
        line = DOMAIN_LITERAL_RE.sub(
            lambda match: f"{match.group('quote')}{pseudonymizer.domain(match.group('value'))}{match.group('quote')}",
            line,
        )
        lines.append(line)
    return "".join(lines)


def redact_file(path: Path, key_patterns: list[re.Pattern[str]], pseudonymizer: Pseudonymizer, counts: Counter[str]) -> None:
    # Policy/list text is executable matching configuration, not application data.
    # Preserve bytes exactly, including regex escapes and original source lines.
    if path.suffix.lower() == ".list":
        counts["list_files_preserved"] += 1
        return

    try:
        with path.open(encoding="utf-8", newline="") as source:
            original = source.read()
    except UnicodeDecodeError:
        with path.open(encoding="utf-8", errors="replace", newline="") as source:
            original = source.read()

    if is_source_file(path):
        text = redact_source_text(original, pseudonymizer)
        if text != original:
            with path.open("w", encoding="utf-8", newline="") as output:
                output.write(text)
            counts["files_redacted"] += 1
        counts["files_processed"] += 1
        return

    text = original
    protected_group_ids: dict[str, str] = {}
    if path.name == "pom.xml":
        # Maven coordinates are build identifiers, not hostnames or topology.
        prefix = "SAFE_REPO_EXPORT_POM_GROUPID_"
        while prefix in original:
            prefix += "X"
        def protect_group_id(match: re.Match[str]) -> str:
            placeholder = f"{prefix}{len(protected_group_ids)}_END"
            protected_group_ids[placeholder] = match.group(0)
            return placeholder
        text = re.sub(
            r"<(?P<tag>(?:[A-Za-z_][\w.-]*:)?groupId)(?:\s[^>]*)?>.*?</(?P=tag)\s*>",
            protect_group_id, text, flags=re.S,
        )
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
            sanitized, changed = redact_json(parsed, key_patterns, pseudonymizer)
            if changed:
                text = json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n"
        except json.JSONDecodeError:
            pass

    if path.suffix.lower() == ".sql":
        text, removed = strip_sql_dml(text)
        counts["sql_data_statements_removed"] += removed

    if path.suffix.lower() in {".yml", ".yaml", ".properties", ".xml", ".conf", ".cfg", ".ini", ".toml"}:
        text = replace_config_lines(text, key_patterns, pseudonymizer)

    text = redact_generic_text(text, key_patterns, pseudonymizer)
    for placeholder, element in protected_group_ids.items():
        text = text.replace(placeholder, element)
    if text != original:
        with path.open("w", encoding="utf-8", newline="") as output:
            output.write(text)
        counts["files_redacted"] += 1
    counts["files_processed"] += 1


def scan_residuals(root: Path, skip_patterns: Iterable[str] = ()) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or ".git" in path.parts:
            continue
        if not is_text_file(path):
            continue
        relative = path.relative_to(root).as_posix()
        if matches_any(relative, skip_patterns):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for rule_name, pattern in RESIDUAL_RULES.items():
                if is_source_file(path) and rule_name == "unredacted-secret-literal":
                    continue
                if pattern.search(line):
                    findings.append({"rule": rule_name, "file": relative, "line": line_number})
    return findings


def write_state(path: Path, counts: Counter[str], redactions: Counter[str], findings: list[dict[str, Any]]) -> None:
    payload = {
        "counts": dict(sorted(counts.items())),
        "redactions": dict(sorted(redactions.items())),
        "findings": findings,
    }
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def command_generate_salt(args: argparse.Namespace) -> int:
    path = Path(args.output).expanduser()
    if path.is_symlink():
        fail("salt file must not be a symlink")
    path = path.resolve()
    if path.exists():
        if not path.is_file():
            fail("salt must be a regular file")
        mode = stat.S_IMODE(path.stat().st_mode)
        if os.name != "nt" and mode & 0o077:
            fail(f"existing salt file permissions are too broad: {path} (expected 0600)")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write((secrets.token_hex(32) + "\n").encode("ascii"))
    except BaseException:
        path.unlink()
        raise
    return 0


def command_sanitize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        fail(f"root is not a directory: {root}")
    skip_patterns = read_list(Path(args.skip_list)) if args.skip_list else []
    includes = read_list(Path(args.include))
    excludes = read_list(Path(args.exclude))
    key_patterns = [re.compile(item, re.I) for item in read_list(Path(args.redact_keys))]
    public_hosts = set(read_list(Path(args.public_hosts)))
    salt = bytes.fromhex(Path(args.salt_file).read_text(encoding="ascii").strip())
    if len(salt) < 32:
        fail("pseudonymization salt must contain at least 32 bytes")

    counts: Counter[str] = Counter()
    filter_tree(root, includes, excludes, counts)
    pseudonymizer = Pseudonymizer(salt, public_hosts)
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            if matches_any(path.relative_to(root).as_posix(), skip_patterns):
                counts["files_exempt_from_sanitization_and_scan"] += 1
                continue
            redact_file(path, key_patterns, pseudonymizer, counts)

    # Match original ignore lines against their sanitized form, never export raw lines.
    if getattr(args, "ignore_state", None):
        ignore_pseudo = Pseudonymizer(salt, public_hosts)
        signatures = set()
        regexes = []
        paths = []
        for number, line in enumerate(read_list(Path(args.gitleaks_ignore)), start=1):
            if line.startswith("path:"):
                pattern = line[len("path:"):].strip()
                if not pattern or pattern.startswith("/") or ".." in PurePosixPath(pattern).parts:
                    fail(f"invalid Gitleaks ignore path at entry {number}")
                paths.append(pattern)
                continue
            if line.startswith("regex:"):
                expression = line[len("regex:"):].strip()
                if not expression:
                    fail(f"empty Gitleaks ignore regex at entry {number}")
                try:
                    re.compile(expression)
                except re.error:
                    fail(f"invalid Gitleaks ignore regex at entry {number}")
                regexes.append(expression)
                continue
            for value in (line, redact_source_text(line, ignore_pseudo), redact_generic_text(line, key_patterns, ignore_pseudo),
                          redact_generic_text(replace_config_lines(line, key_patterns, ignore_pseudo), key_patterns, ignore_pseudo)):
                signatures.add(hashlib.sha256(value.strip().encode()).hexdigest())
        Path(args.ignore_state).write_text(json.dumps({"line_hashes": sorted(signatures), "regexes": regexes, "paths": paths}), encoding="utf-8")

    findings = scan_residuals(root, skip_patterns)
    write_state(Path(args.state), counts, pseudonymizer.counts, findings)
    if findings:
        for finding in findings:
            print(f"residual finding: {finding['rule']} at {finding['file']}:{finding['line']}", file=sys.stderr)
        return 4
    return 0


def command_summarize_gitleaks(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fail("cannot parse gitleaks report")
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        fail("unexpected gitleaks report shape")
    skip_patterns = read_list(Path(args.skip_list)) if args.skip_list else []
    scan_root = Path(args.root).resolve() if args.root else None
    ignore_state = getattr(args, "ignore_state", None)
    policy = json.loads(Path(ignore_state).read_text()) if ignore_state else {}
    # Accept the earlier exact-line-only state format.
    signatures = set(policy if isinstance(policy, list) else policy.get("line_hashes", []))
    regexes = [re.compile(value) for value in policy.get("regexes", [])] if isinstance(policy, dict) else []
    ignored_paths = policy.get("paths", []) if isinstance(policy, dict) else []
    remaining = []
    ignored = 0
    for item in payload:
        file_path = Path(str(item.get("File") or "UNKNOWN"))
        relative = None
        if scan_root is not None:
            if not file_path.is_absolute():
                file_path = scan_root / file_path
            try:
                relative = file_path.resolve().relative_to(scan_root).as_posix()
            except ValueError:
                pass
        if relative is not None and matches_any(relative, [*skip_patterns, *ignored_paths]):
            ignored += 1
            continue
        start = int(item.get("StartLine") or 0)
        end = int(item.get("EndLine") or start)
        if relative is not None and (signatures or regexes) and start > 0:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            # Require the complete finding range to consist of approved lines.
            selected = lines[start - 1:end]
            if selected and len(selected) == end - start + 1 and all(
                (hashlib.sha256(line.strip().encode()).hexdigest() in signatures
                 or any(pattern.fullmatch(line.strip()) for pattern in regexes)) for line in selected
            ):
                ignored += 1
                continue
        rule = str(item.get("RuleID") or "gitleaks-finding")
        remaining.append({"rule": rule, "file": relative or "UNKNOWN", "start_line": start, "end_line": end})
        print(f"gitleaks finding: {rule} at {relative or 'UNKNOWN'}:{start}", file=sys.stderr)
    summary = {"total": len(payload), "ignored": ignored, "remaining": len(remaining), "findings": remaining}
    if getattr(args, "summary", None):
        Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if remaining else 0


def manifest_lines(root: Path) -> list[str]:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if relative == ".safe-repo-export/MANIFEST.sha256":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    return lines


def command_finalize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    metadata = root / ".safe-repo-export"
    metadata.mkdir(mode=0o750, exist_ok=True)

    counts = state.get("counts", {})
    redactions = state.get("redactions", {})
    lines = [
        "# Safe Repo Export Report",
        "",
        "The snapshot was created from one Git commit, filtered and sanitized before a new one-commit Git repository was initialized. Original Git history and remotes are absent.",
        "",
        "## Result",
        "",
        "- Built-in residual-secret scan: passed",
        f"- Gitleaks scan: {args.gitleaks_status}",
        f"- Exempt files: {counts.get('files_exempt_from_sanitization_and_scan', 0)}",
        f"- Retained files: {counts.get('files_retained', 0)}",
        f"- Processed text files: {counts.get('files_processed', 0)}",
        f"- List files preserved unchanged: {counts.get('list_files_preserved', 0)}",
        f"- Redacted files: {counts.get('files_redacted', 0)}",
        f"- Removed paths: {counts.get('path_removed', 0)}",
        f"- Removed binary files: {counts.get('binary_removed', 0)}",
        f"- Removed unsafe symlinks: {counts.get('unsafe_symlink_removed', 0)}",
        f"- Removed SQL data statements: {counts.get('sql_data_statements_removed', 0)}",
        "",
        "## Redaction counts",
        "",
        "| Type | Count |",
        "|---|---:|",
    ]
    if redactions:
        lines.extend(f"| {key} | {value} |" for key, value in sorted(redactions.items()))
    else:
        lines.append("| none | 0 |")
    lines.extend([
        "",
        "## Limitations",
        "",
        "Automated redaction cannot prove that arbitrary business data or custom secret formats are absent. Review application configuration, config.json, SQL, retained tests, and signing/RPC/robot/risk integrations before sharing.",
        "",
        "The pseudonymization salt is intentionally not included. Address and identifier equality is stable only for exports made with the same local salt file.",
        "",
    ])
    if getattr(args, "gitleaks_summary", None) and Path(args.gitleaks_summary).exists():
        summary = json.loads(Path(args.gitleaks_summary).read_text())
        (metadata / "GITLEAKS-REPORT.json").write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        lines.extend(["## Gitleaks review", "", f"- Total: {summary['total']}",
                      f"- Ignored: {summary['ignored']}", f"- Remaining: {summary['remaining']}",
                      "- Locations only: GITLEAKS-REPORT.json (no matched values)", ""])
    report = metadata / "EXPORT-REPORT.md"
    report.write_bytes("\n".join(lines).encode("utf-8"))

    manifest = metadata / "MANIFEST.sha256"
    manifest.write_bytes(("\n".join(manifest_lines(root)) + "\n").encode("utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    salt = subparsers.add_parser("generate-salt")
    salt.add_argument("--output", required=True)
    salt.set_defaults(func=command_generate_salt)

    sanitize = subparsers.add_parser("sanitize")
    sanitize.add_argument("--root", required=True)
    sanitize.add_argument("--skip-list")
    sanitize.add_argument("--include", required=True)
    sanitize.add_argument("--exclude", required=True)
    sanitize.add_argument("--redact-keys", required=True)
    sanitize.add_argument("--public-hosts", required=True)
    sanitize.add_argument("--salt-file", required=True)
    sanitize.add_argument("--state", required=True)
    sanitize.add_argument("--gitleaks-ignore")
    sanitize.add_argument("--ignore-state")
    sanitize.set_defaults(func=command_sanitize)

    gitleaks = subparsers.add_parser("summarize-gitleaks")
    gitleaks.add_argument("--input", required=True)
    gitleaks.add_argument("--root")
    gitleaks.add_argument("--skip-list")
    gitleaks.add_argument("--ignore-state")
    gitleaks.add_argument("--summary")
    gitleaks.set_defaults(func=command_summarize_gitleaks)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--root", required=True)
    finalize.add_argument("--state", required=True)
    finalize.add_argument("--gitleaks-status", required=True)
    finalize.add_argument("--gitleaks-summary")
    finalize.set_defaults(func=command_finalize)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
