#!/usr/bin/env python3
"""Compare JavaScript segments using offset-independent structural tokens."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


TOKEN = re.compile(
    r"(?P<comment>//[^\n]*|/\*.*?\*/)|"
    r"(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`)|"
    r"(?P<number>\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b)|"
    r"(?P<identifier>\b[A-Za-z_$][A-Za-z0-9_$]*\b)|"
    r"(?P<operator>===|!==|=>|\?\?|&&|\|\||\?\.|\+\+|--|==|!=|<=|>=|\*\*|.)",
    re.DOTALL,
)
KEYWORDS = {
    "async", "await", "break", "case", "catch", "class", "const", "continue",
    "default", "delete", "do", "else", "export", "extends", "false", "finally",
    "for", "function", "if", "import", "in", "instanceof", "let", "new", "null",
    "of", "return", "static", "super", "switch", "this", "throw", "true", "try",
    "typeof", "undefined", "var", "void", "while", "yield",
}


def normalized(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="strict")
    tokens: list[str] = []
    for match in TOKEN.finditer(text):
        kind = match.lastgroup
        value = match.group()
        if kind == "comment" or value.isspace():
            continue
        if kind == "identifier":
            tokens.append(value if value in KEYWORDS else "ID")
        elif kind == "string":
            tokens.append("STRING")
        elif kind == "number":
            tokens.append("NUMBER")
        else:
            tokens.append(value)
    return tokens


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    left_tokens = normalized(args.left)
    right_tokens = normalized(args.right)
    left_hash = hashlib.sha256("\n".join(left_tokens).encode()).hexdigest()
    right_hash = hashlib.sha256("\n".join(right_tokens).encode()).hexdigest()
    common_prefix = 0
    for left, right in zip(left_tokens, right_tokens):
        if left != right:
            break
        common_prefix += 1
    result = {
        "schema_version": 1,
        "left": {"path": str(args.left.resolve()), "tokens": len(left_tokens), "structural_sha256": left_hash},
        "right": {"path": str(args.right.resolve()), "tokens": len(right_tokens), "structural_sha256": right_hash},
        "structurally_identical": left_tokens == right_tokens,
        "common_prefix_tokens": common_prefix,
        "first_difference": {
            "left": left_tokens[common_prefix] if common_prefix < len(left_tokens) else None,
            "right": right_tokens[common_prefix] if common_prefix < len(right_tokens) else None,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    if args.output.exists():
        if not args.output.is_file() or args.output.is_symlink() or args.output.read_bytes() != data:
            parser.error(f"refusing to overwrite different comparison: {args.output}")
    else:
        args.output.write_bytes(data)
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
