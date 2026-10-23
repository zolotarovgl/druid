"""Set keys in a project's druid.yaml without losing its comments (TUI Setup screen, species lock).

Line-based on purpose: the file is never round-tripped through a YAML dumper, so every comment
and the key order survive. Only the values being set are rendered with yaml.safe_dump."""
from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

from druid import core, paths


def _render(key: str, value) -> list:
    """`key: value` (scalars, [] and {} inline) or `key:` plus its block, as lines with newlines."""
    return yaml.safe_dump({key: value}, default_flow_style=False, sort_keys=False,
                          width=10 ** 9).splitlines(True)


def _split_comment(line: str):
    """(code, comment) of a line; a '#' starts a comment only outside quotes and after whitespace."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i], line[i:]
    return line, ""


def _is_key_line(line: str, key: str, indent: bool) -> bool:
    pat = (r"[ \t]+" if indent else r"") + re.escape(key) + r":(\s|$)"
    return re.match(pat, line) is not None


def _top_block(lines: list, key: str):
    """(start, end) of a top-level key's block: its line plus the indented / '- ' lines after it."""
    for i, l in enumerate(lines):
        if _is_key_line(l, key, indent=False):
            end = i + 1
            for j in range(i + 1, len(lines)):
                l2 = lines[j]
                if not l2.strip():
                    continue
                if l2[0] in " \t" or l2.startswith("- ") or l2.rstrip() == "-":
                    end = j + 1
                else:
                    break
            return i, end
    return None


def set_key(text: str, key: tuple, value) -> str:
    """text with `key` set to `value`. ("species",): top-level, any YAML value, the whole block is
    replaced. ("params", "run_generax"): one level under a top-level mapping, scalar only; the line's
    trailing comment is kept. A missing key is appended (nested: at the end of its parent block)."""
    if len(key) not in (1, 2) or not all(isinstance(k, str) for k in key):
        raise core.ConfigError(f"unsupported config key {key!r}")
    lines = text.splitlines(True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if len(key) == 1:
        new = _render(key[0], value)
        blk = _top_block(lines, key[0])
        if blk is None:
            lines += new
        else:
            s, e = blk
            _, comment = _split_comment(lines[s])
            if comment and len(new) == 1:       # an inline value keeps the key line's comment
                new[0] = new[0].rstrip("\n") + "   " + comment
            lines[s:e] = new
        return "".join(lines)
    if isinstance(value, (dict, list, tuple)):
        raise core.ConfigError(f"nested key {key!r} takes a scalar, not {type(value).__name__}")
    parent, child = key
    blk = _top_block(lines, parent)
    if blk is None:
        return "".join(lines + [f"{parent}:\n", "  " + _render(child, value)[0]])
    s, e = blk
    if _split_comment(lines[s])[0].split(":", 1)[1].strip():   # `params: {}` and other inline values
        raise core.ConfigError(f"{parent} is not a block mapping; cannot set {child} in it")
    body = [i for i in range(s + 1, e) if lines[i].strip()]
    indent = re.match(r"[ \t]*", lines[body[0]]).group(0) if body else "  "
    for i in range(s + 1, e):
        if _is_key_line(lines[i], child, indent=True) and \
                re.match(r"[ \t]*", lines[i]).group(0) == indent:
            code, comment = _split_comment(lines[i])
            rendered = indent + _render(child, value)[0].rstrip("\n")
            lines[i] = rendered + (code[len(code.rstrip()):] + comment if comment else "") + "\n"
            return "".join(lines)
    last = body[-1] if body else s
    lines.insert(last + 1, indent + _render(child, value)[0])
    return "".join(lines)


def update_config(changes: dict) -> Path:
    """Apply `changes` ({key tuple: value}) to the project's druid.yaml. The result must load as the old
    mapping with only those keys changed and must pass core.config_from_raw; otherwise ConfigError and
    nothing is written."""
    f = paths.config_file()
    old = paths.read_raw(f)
    text = f.read_text()
    expected = copy.deepcopy(old)
    for key, value in changes.items():
        text = set_key(text, key, value)
        if len(key) == 1:
            expected[key[0]] = value
        else:
            if not isinstance(expected.setdefault(key[0], {}), dict):
                raise core.ConfigError(f"{key[0]} is not a mapping; cannot set {key[1]}")
            expected[key[0]][key[1]] = value
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise core.ConfigError(f"the edited config is not valid YAML ({str(e).splitlines()[0]})")
    if loaded != expected:
        raise core.ConfigError("the edited config differs from the intended change; nothing written")
    core.config_from_raw(loaded)
    return paths.write_text(f, text)
