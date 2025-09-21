"""
parser_lib.py
Parsing engine: tries to use clang.cindex for high-accuracy parsing. If not available,
falls back to regex-based parsing.

Exposes: parse_all(path) -> (macros_list, types_list, apis_list, counts_dict)
"""

import os
import re
from typing import List, Dict
from .utils import strip_comments, split_args, read_file

# Try to import clang
try:
    import clang.cindex as clang
    CLANG_AVAILABLE = True
except Exception:
    CLANG_AVAILABLE = False

# -----------------------------------------------------
# libclang-based parser (preferred)
# -----------------------------------------------------
def _parse_with_clang(path: str):
    """
    Returns (macros, types, apis, counts)
    macros: [{'name','value','comment'}]
    types : [{'typedef_name','kind','num_members','members','comment'}] # kind: 'struct' or 'enum'
    apis  : [{'name','return_type','num_args','args':[{'raw','type','name'}],'body','comment'}]
    """
    index = clang.Index.create()
    # Parse: disable including system headers to speed up
    tu = index.parse(path, args=['-std=c99'])
    macros = []
    types = []
    apis = []

    # Helper to get token text from extent
    def tokens_to_text(extent):
        tokens = list(tu.get_tokens(extent=extent))
        if not tokens:
            return ''
        pieces = [t.spelling for t in tokens]
        return ' '.join(pieces)

    # Walk AST
    for cursor in tu.cursor.get_children():
        kind = cursor.kind
        # Macros
        if kind == clang.CursorKind.MACRO_DEFINITION:
            name = cursor.spelling
            # get tokens for this extent
            txt = tokens_to_text(cursor.extent)
            # strip '#define' and name
            m = re.sub(r'^\s*#\s*define\s+' + re.escape(name), '', txt, flags=re.IGNORECASE).strip()
            value = m.strip()
            macros.append({
                'name': name,
                'value': value,
                'comment': f"MACROS = macro defined with name {name} and value {value}"
            })
        # Enums
        elif kind == clang.CursorKind.ENUM_DECL:
            typedef_name = cursor.spelling  # may be empty if anonymous
            members = []
            for c2 in cursor.get_children():
                if c2.kind == clang.CursorKind.ENUM_CONSTANT_DECL:
                    members.append(c2.spelling)
            types.append({
                'typedef_name': typedef_name or None,
                'kind': 'enum',
                'num_members': len(members),
                'members': members,
                'comment': f"STRUCT & ENUM = defined with name {typedef_name or '<anon>'} and have {len(members)} members"
            })
        # Structs / Typedef structs
        elif kind in (clang.CursorKind.STRUCT_DECL, clang.CursorKind.TYPEDEF_DECL):
            # TYPEDEF_DECL may wrap a struct
            if kind == clang.CursorKind.TYPEDEF_DECL:
                # check underlying type
                under = cursor.underlying_typedef_type
                # get underlying decl
                # try to get the declaration children to find struct
                typedef_name = cursor.spelling
                # attempt to find struct children
                members = []
                # iterate children to find fields
                for c2 in cursor.get_children():
                    if c2.kind == clang.CursorKind.STRUCT_DECL:
                        for field in c2.get_children():
                            if field.kind == clang.CursorKind.FIELD_DECL:
                                members.append(field.spelling)
                if members:
                    types.append({
                        'typedef_name': typedef_name,
                        'kind': 'struct',
                        'num_members': len(members),
                        'members': members,
                        'comment': f"STRUCT & ENUM = defined with name {typedef_name} and have {len(members)} members"
                    })
            else:
                # Anonymous struct (STRUCT_DECL)
                struct_name = cursor.spelling
                members = []
                for field in cursor.get_children():
                    if field.kind == clang.CursorKind.FIELD_DECL:
                        members.append(field.spelling)
                if members:
                    types.append({
                        'typedef_name': struct_name or None,
                        'kind': 'struct',
                        'num_members': len(members),
                        'members': members,
                        'comment': f"STRUCT & ENUM = defined with name {struct_name or '<anon>'} and have {len(members)} members"
                    })
        # Functions
        elif kind == clang.CursorKind.FUNCTION_DECL:
            name = cursor.spelling
            ret_type = cursor.result_type.spelling
            args = []
            for a in cursor.get_arguments():
                args.append({'raw': a.type.spelling + (' ' + a.spelling if a.spelling else ''), 'type': a.type.spelling, 'name': a.spelling})
            num_args = len(args)
            # Determine if definition has body
            body_text = ''
            if cursor.is_definition():
                # extract tokens of extent and try to find body from '{'..'}'
                snippet = tokens_to_text(cursor.extent)
                # find first '{' and last '}' in snippet
                if '{' in snippet:
                    start = snippet.find('{')
                    end = snippet.rfind('}')
                    if end >= 0:
                        body_text = snippet[start:end+1].strip()
                    else:
                        body_text = snippet[start:].strip()
                else:
                    body_text = snippet.strip()
            else:
                body_text = "no body"
            apis.append({
                'name': name,
                'return_type': ret_type,
                'num_args': num_args,
                'args': args,
                'body': body_text,
                'comment': f"API = Function with name {name} having {num_args} arguments with return type {ret_type}"
            })

    counts = {
        'macros': len(macros),
        'structs': sum(1 for t in types if t['kind'] == 'struct'),
        'enums': sum(1 for t in types if t['kind'] == 'enum'),
        'functions': len(apis)
    }
    return macros, types, apis, counts

# -----------------------------------------------------
# Regex-based fallback parser (conservative)
# -----------------------------------------------------
def _parse_with_regex(path: str):
    src = read_file(path)
    src_nocom = strip_comments(src)

    macros = []
    types = []
    apis = []

    # Macros: #define NAME value (single-line)
    for m in re.finditer(r'^\s*#\s*define\s+([A-Za-z_]\w*)\s+(.*?)\s*$', src_nocom, re.MULTILINE):
        name = m.group(1)
        value = m.group(2).strip()
        macros.append({'name': name, 'value': value, 'comment': f"MACROS = macro defined with name {name} and value {value}"})

    # Enums: typedef enum { ... } NAME;
    for m in re.finditer(r'typedef\s+enum\s*(?:\w*\s*)?\{(.*?)\}\s*([A-Za-z_]\w*)\s*;', src_nocom, re.S):
        body = m.group(1)
        name = m.group(2)
        members = [line.split('=')[0].strip().strip(',') for line in body.splitlines() if line.strip()]
        members = [x for x in members if x]
        types.append({'typedef_name': name, 'kind': 'enum', 'num_members': len(members), 'members': members, 'comment': f"STRUCT & ENUM = defined with name {name} and have {len(members)} members"})

    # Struct typedefs: typedef struct NAME? { ... } TYPENAME;
    for m in re.finditer(r'typedef\s+struct\s*(?:[A-Za-z_]\w*\s*)?\{(.*?)\}\s*([A-Za-z_]\w*)\s*;', src_nocom, re.S):
        body = m.group(1)
        name = m.group(2)
        # naive member capture: lines with semicolon
        members = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            if ';' in line:
                # member name is last token before semicolon
                member = line.split(';')[0].strip()
                # remove type portion
                parts = member.rsplit(' ', 1)
                mem_name = parts[-1].strip()
                members.append(mem_name)
        types.append({'typedef_name': name, 'kind': 'struct', 'num_members': len(members), 'members': members, 'comment': f"STRUCT & ENUM = defined with name {name} and have {len(members)} members"})

    # Functions: definitions and prototypes
    # Count function definitions by pattern ') {'
    func_def_pattern = re.compile(r'([A-Za-z_][\w \*\(\)]+?)\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*\{', re.S)
    for m in func_def_pattern.finditer(src_nocom):
        ret = ' '.join(m.group(1).split())
        name = m.group(2)
        args_text = m.group(3)
        args = split_args(args_text)
        # attempt to extract the body: naive brace matching from the match end
        start_pos = m.end()-1
        # naive brace matching on original src_nocom
        i = start_pos
        depth = 0
        body = ''
        while i < len(src_nocom):
            ch = src_nocom[i]
            body += ch
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = body.strip()
        apis.append({
            'name': name,
            'return_type': ret,
            'num_args': len(args),
            'args': args,
            'body': body if body else "no body",
            'comment': f"API = Function with name {name} having {len(args)} arguments with return type {ret}"
        })

    # Prototypes (no body) - pattern ends with );
    proto_pattern = re.compile(r'([A-Za-z_][\w \*\(\)]+?)\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;', re.S)
    # ensure not to duplicate ones already found
    existing_names = set([f['name'] for f in apis])
    for m in proto_pattern.finditer(src_nocom):
        name = m.group(2)
        if name in existing_names:
            continue
        ret = ' '.join(m.group(1).split())
        args_text = m.group(3)
        args = split_args(args_text)
        apis.append({
            'name': name,
            'return_type': ret,
            'num_args': len(args),
            'args': args,
            'body': "no body",
            'comment': f"API = Function with name {name} having {len(args)} arguments with return type {ret}"
        })

    counts = {
        'macros': len(macros),
        'structs': sum(1 for t in types if t['kind']=='struct'),
        'enums': sum(1 for t in types if t['kind']=='enum'),
        'functions': len(apis)
    }
    return macros, types, apis, counts

# -----------------------------------------------------
# Public API
# -----------------------------------------------------
def parse_all(path: str):
    """
    Attempt to parse the C file using clang; fall back to regex parser.
    Returns: macros, types, apis, counts, method_used
    """
    if CLANG_AVAILABLE:
        try:
            macros, types, apis, counts = _parse_with_clang(path)
            return macros, types, apis, counts, 'libclang'
        except Exception as e:
            # fallback
            print("libclang parsing failed, falling back to regex parser. Error:", e)
    macros, types, apis, counts = _parse_with_regex(path)
    return macros, types, apis, counts, 'regex'
