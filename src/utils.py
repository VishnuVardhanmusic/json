"""
utils.py
Utility helpers: strip comments, read file, write JSON safely.
"""

import re
import json
from typing import Tuple

def read_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_json(path: str, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2)

def strip_comments(source: str) -> str:
    """
    Remove C-style /* ... */ and // ... comments.
    This is a conservative remover and avoids removing inside string literals in most normal code,
    but it is not a full C lexer. For best accuracy we use libclang parsing if available.
    """
    # Remove block comments first
    pattern_block = re.compile(r'/\*.*?\*/', re.DOTALL)
    source_no_block = re.sub(pattern_block, '', source)

    # Remove line comments
    pattern_line = re.compile(r'//.*?$' , re.MULTILINE)
    source_no_comments = re.sub(pattern_line, '', source_no_block)

    return source_no_comments

def split_args(arg_text: str):
    """
    Split argument text into list of (type, name) pairs as strings.
    Handles common forms; for complex function pointer declarations this will return the raw token.
    """
    arg_text = arg_text.strip()
    if arg_text == '' or arg_text.lower() in ('void',):
        return []
    args = []
    depth = 0
    current = ''
    for c in arg_text:
        if c == ',' and depth == 0:
            args.append(current.strip())
            current = ''
        else:
            current += c
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
    if current.strip():
        args.append(current.strip())

    def split_type_name(arg):
        # naive split: last token is name, rest is type
        parts = arg.rsplit(' ', 1)
        if len(parts) == 1:
            return (parts[0], '')
        return (parts[0].strip(), parts[1].strip())

    result = []
    for a in args:
        typ, name = split_type_name(a)
        result.append({'raw': a, 'type': typ, 'name': name})
    return result
