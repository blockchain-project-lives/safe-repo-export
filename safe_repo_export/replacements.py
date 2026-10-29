"""Fail-closed Java body replacement using a restricted YAML schema and stdlib lexer."""
from __future__ import annotations

import json
import re
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

CONFIG = '.safe-repo-export/replacements.yaml'
STUBS = '.safe-repo-export/stubs'
IDENTIFIER = re.compile(r'^[A-Za-z_$][\w$]*$')
JAVA_IDENTIFIER = re.compile(r'[A-Za-z_$\u0080-\uffff][\w$]*')


class ReplacementError(ValueError):
    """A replacement cannot be applied unambiguously."""


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or any(part in {'', '.', '..', '.git'} for part in value.split('/'))
            or any(char in value for char in '\\:\r\n\0')):
        raise ReplacementError('Replacement paths must be portable relative paths without traversal')
    return path.as_posix()


def read_worktree(repo: Path, name: str) -> bytes | None:
    name = safe_relative(name)
    path = repo
    for part in PurePosixPath(name).parts:
        path /= part
        if path.is_symlink():
            raise ReplacementError('Replacement inputs must not be symlinks')
    if not path.exists():
        return None
    if not path.is_file():
        raise ReplacementError('Replacement inputs must be regular files')
    return path.read_bytes()


def strip_comment(line: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote == '"' and char == '\\':
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == '#' and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
    if quote:
        raise ReplacementError('Unterminated quoted YAML scalar')
    return line.rstrip()


def scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        try:
            result = json.loads(value)
        except ValueError:
            raise ReplacementError('Invalid double-quoted replacement scalar') from None
        if not isinstance(result, str):
            raise ReplacementError('Replacement fields must be strings')
        return result
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'") or re.search(r"(?<!')'(?!')", value[1:-1]):
            raise ReplacementError('Invalid single-quoted replacement scalar')
        return value[1:-1].replace("''", "'")
    if not value or value[0] in '[]{}&*!|>@`' or ': ' in value or value in {'null', '~'}:
        raise ReplacementError('Unsupported replacement YAML scalar; quote string values')
    return value


def parse_config(text: str) -> list[dict]:
    """Only replacements: [], or a two-space indented list of five named fields."""
    lines = []
    for raw in text.splitlines():
        if '\t' in raw[:len(raw) - len(raw.lstrip())]:
            raise ReplacementError('Use spaces for replacement YAML indentation')
        clean = strip_comment(raw)
        if clean.strip():
            lines.append(clean)
    if lines == ['replacements: []']:
        return []
    if not lines or lines[0] != 'replacements:':
        raise ReplacementError('Replacement YAML must start with replacements: or replacements: []')
    rules: list[dict] = []
    current = None
    in_parameters = False
    allowed = {'file', 'class', 'method', 'parameter-types', 'body-file'}
    for line in lines[1:]:
        if line.startswith('  - ') and not line.startswith('    '):
            current = {}
            rules.append(current)
            field = line[4:]
        elif line.startswith('      - ') and in_parameters and current is not None:
            current['parameter-types'].append(scalar(line[8:]))
            continue
        elif line.startswith('    ') and not line.startswith('     ') and current is not None:
            field = line[4:]
        else:
            raise ReplacementError('Unsupported replacement YAML layout; use the generated example')
        match = re.fullmatch(r'([a-z-]+):(?: +(.*))?', field)
        if not match or match[1] not in allowed or match[1] in current:
            raise ReplacementError('Unknown or duplicate replacement field')
        key, value = match[1], match[2] or ''
        in_parameters = key == 'parameter-types'
        if in_parameters:
            if value not in {'', '[]'}:
                raise ReplacementError('parameter-types must be [] or a block list of strings')
            current[key] = []
        else:
            current[key] = scalar(value)
    if not rules or any(set(rule) != allowed for rule in rules):
        raise ReplacementError('Every replacement requires file, class, method, parameter-types and body-file')
    return rules


@dataclass(frozen=True)
class Rule:
    file: str
    class_name: str
    method: str
    parameters: tuple[str, ...]
    body: str


def normalized_type(value: str) -> str:
    return re.sub(r'\s+', '', value).replace('...', '[]')


def load_rules(read: Callable[[str], bytes | None]) -> list[Rule]:
    payload = read(CONFIG)
    if payload is None:
        return []
    rules = []
    seen = set()
    for item in parse_config(payload.decode('utf-8-sig')):
        filename = safe_relative(item['file'])
        template = safe_relative(item['body-file'])
        if not filename.endswith('.java') or filename.startswith('.safe-repo-export/'):
            raise ReplacementError('Replacement targets must be Java files outside policy metadata')
        if not template.startswith('stubs/'):
            raise ReplacementError('body-file must be inside .safe-repo-export/stubs/')
        if not all(IDENTIFIER.fullmatch(part) for part in item['class'].split('.')) or not IDENTIFIER.fullmatch(item['method']):
            raise ReplacementError('Invalid replacement class or method name')
        parameters = tuple(normalized_type(value) for value in item['parameter-types'])
        if any(not parameter for parameter in parameters):
            raise ReplacementError('Parameter types must not be empty')
        identity = filename, item['class'], item['method'], parameters
        if identity in seen:
            raise ReplacementError('Duplicate replacement target')
        seen.add(identity)
        body = read('.safe-repo-export/' + template)
        if body is None:
            raise ReplacementError('Replacement body-file is missing')
        body_text = body.decode('utf-8-sig')
        tokenize(body_text)  # Reject unbalanced/unterminated template syntax early.
        rules.append(Rule(filename, item['class'], item['method'], parameters, body_text))
    return rules


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int


def tokenize(text: str) -> tuple[list[Token], dict[int, int], list[int]]:
    # Java performs Unicode-escape translation before lexical analysis. Do not guess.
    if re.search(r'\\u+[0-9a-fA-F]{4}', text):
        raise ReplacementError('Java Unicode escape translation is unsupported in replacement inputs')
    tokens = []
    pairs = {}
    stack = []
    depths = []
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace() or (index == 0 and char == '\ufeff'):
            index += 1
            continue
        if text.startswith('//', index):
            end = text.find('\n', index)
            index = len(text) if end < 0 else end
            continue
        if text.startswith('/*', index):
            end = text.find('*/', index + 2)
            if end < 0:
                raise ReplacementError('Unterminated Java comment')
            index = end + 2
            continue
        start = index
        if char in "\"'":
            quote = '"""' if text.startswith('"""', index) else char
            index += len(quote)
            while index < len(text):
                if text[index] == '\\':
                    index += 2
                elif text.startswith(quote, index):
                    index += len(quote)
                    break
                elif quote != '"""' and text[index] in '\r\n':
                    raise ReplacementError('Unterminated Java string or character literal')
                else:
                    index += 1
            else:
                raise ReplacementError('Unterminated Java string or text block')
            value = '<literal>'
        else:
            match = JAVA_IDENTIFIER.match(text, index)
            if match:
                value = match[0]
                index += len(value)
            else:
                value = char
                index += 1
        number = len(tokens)
        depths.append(depth)
        tokens.append(Token(value, start, index))
        if value in {'{', '(', '['}:
            stack.append((value, number))
            if value == '{':
                depth += 1
        elif value in {'}', ')', ']'}:
            if not stack or stack[-1][0] != {'}': '{', ')': '(', ']': '['}[value]:
                raise ReplacementError('Unbalanced Java delimiters')
            _, opening = stack.pop()
            pairs[opening] = number
            pairs[number] = opening
            if value == '}':
                depth -= 1
    if stack:
        raise ReplacementError('Unbalanced Java delimiters')
    return tokens, pairs, depths


def remove_annotations(values: list[str]) -> list[str]:
    result = []
    index = 0
    while index < len(values):
        if values[index] != '@':
            result.append(values[index])
            index += 1
            continue
        index += 1
        if index >= len(values) or not IDENTIFIER.fullmatch(values[index]):
            raise ReplacementError('Unsupported Java annotation syntax')
        index += 1
        while index + 1 < len(values) and values[index] == '.':
            index += 2
        if index < len(values) and values[index] == '(':
            depth = 1
            index += 1
            while index < len(values) and depth:
                depth += (values[index] == '(') - (values[index] == ')')
                index += 1
            if depth:
                raise ReplacementError('Unsupported Java annotation arguments')
    return result


def parameter_types(values: list[str]) -> tuple[str, ...]:
    values = remove_annotations(values)
    if not values:
        return ()
    groups = [[]]
    angle = 0
    for value in values:
        if value == '<':
            angle += 1
        elif value == '>':
            angle -= 1
        if angle < 0:
            raise ReplacementError('Unsupported Java generic parameter syntax')
        if value == ',' and angle == 0:
            groups.append([])
        else:
            groups[-1].append(value)
    if angle:
        raise ReplacementError('Unsupported Java generic parameter syntax')
    result = []
    for group in groups:
        group = [value for value in group if value != 'final']
        trailing = ''
        while len(group) >= 2 and group[-2:] == ['[', ']']:
            trailing += '[]'
            group = group[:-2]
        if len(group) < 2 or not IDENTIFIER.fullmatch(group[-1]) or group[-1] == 'this':
            raise ReplacementError('Unsupported Java parameter declaration')
        result.append(normalized_type(''.join(group[:-1]) + trailing))
    return tuple(result)


def replace_body(text: str, rule: Rule) -> str:
    tokens, pairs, depths = tokenize(text)
    values = [token.value for token in tokens]
    package = ''
    if 'package' in values:
        start = values.index('package') + 1
        try:
            end = values.index(';', start)
        except ValueError:
            raise ReplacementError('Unsupported Java package declaration') from None
        package = ''.join(values[start:end])
    classes = []
    for index, value in enumerate(values[:-1]):
        if value not in {'class', 'interface', 'enum', 'record'} or (index and values[index - 1] == '.'):
            continue
        if not IDENTIFIER.fullmatch(values[index + 1]):
            continue
        cursor = index + 2
        while cursor < len(tokens) and values[cursor] not in {'{', ';', '}'}:
            if values[cursor] in {'(', '['}:
                cursor = pairs[cursor] + 1
            else:
                cursor += 1
        if cursor >= len(tokens) or values[cursor] != '{':
            continue
        ancestors = [item for item in classes if item[0] < index < item[1]]
        prefix = ancestors[-1][2] if ancestors else package
        qualified = (prefix + '.' if prefix else '') + values[index + 1]
        classes.append((cursor, pairs[cursor], qualified))
    owners = [item for item in classes if item[2] == rule.class_name]
    if len(owners) != 1:
        raise ReplacementError('Replacement class must match exactly once')
    opening, closing, _ = owners[0]
    if rule.method == rule.class_name.split('.')[-1]:
        raise ReplacementError('Constructor replacement is not supported')
    level = depths[opening] + 1
    matches = []
    for index in range(opening + 1, closing - 1):
        if values[index] != rule.method or values[index + 1] != '(' or depths[index] != level:
            continue
        if values[index - 1] in {'.', '@', ':'}:
            continue
        start = index - 1
        while start > opening:
            if values[start] in {')', ']'}:
                start = pairs[start] - 1
                continue
            if (values[start] == ';' and depths[start] == level) or (values[start] == '}' and depths[start] == level + 1):
                break
            start -= 1
        prefix = remove_annotations(values[start + 1:index])
        if not prefix or any(value in {'=', '(', ')', '->'} for value in prefix):
            continue
        finish = pairs[index + 1]
        if parameter_types(values[index + 2:finish]) != rule.parameters:
            continue
        cursor = finish + 1
        if cursor < closing and values[cursor] == 'throws':
            cursor += 1
            while cursor < closing and values[cursor] not in {'{', ';', '}'}:
                cursor += 1
        if cursor >= closing or values[cursor] not in {'{', ';'}:
            continue
        matches.append(cursor)
    if len(matches) != 1 or values[matches[0]] != '{':
        raise ReplacementError('Replacement method must match exactly one method with a body')
    body_start = matches[0]
    body_end = pairs[body_start]
    newline = '\r\n' if '\r\n' in text else '\n'
    line_start = text.rfind('\n', 0, tokens[body_start].start) + 1
    indent = re.match(r'[ \t]*', text[line_start:])[0]
    body = textwrap.dedent(rule.body).strip('\r\n')
    lines = body.splitlines()
    replacement = newline + newline.join(indent + '    ' + line if line else '' for line in lines) + newline + indent
    return text[:tokens[body_start].end] + replacement + text[tokens[body_end].start:]


def remove_private_inputs(root: Path) -> None:
    config = root / CONFIG
    if config.exists() or config.is_symlink():
        config.unlink()
    stubs = root / STUBS
    if stubs.is_symlink():
        stubs.unlink()
    elif stubs.exists():
        shutil.rmtree(stubs)


def apply_rules(root: Path, rules: list[Rule]) -> list[dict]:
    outputs = {}
    records = []
    for number, rule in enumerate(rules, 1):
        path = root / rule.file
        if not path.is_file() or path.is_symlink():
            raise ReplacementError(f'Replacement {number}: target is missing or excluded')
        try:
            text = outputs.get(rule.file)
            if text is None:
                text = path.read_bytes().decode('utf-8')
            outputs[rule.file] = replace_body(text, rule)
        except ReplacementError as exc:
            raise ReplacementError(f'Replacement {number}: {exc}') from None
        records.append({'rule': number, 'file': rule.file, 'count': 1})
    for filename, text in outputs.items():
        (root / filename).write_bytes(text.encode('utf-8'))
    return records
