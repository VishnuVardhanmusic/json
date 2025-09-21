"""
main.py
CLI entry. Usage:
    python -m src.main sample_input/sample.c

It writes outputs/macros.json, outputs/types.json, outputs/apis.json
and prints numeric verification comparing the counts between file & generated JSONs.
"""

import sys
import os
import json
from pathlib import Path
from .parser_lib import parse_all
from .utils import read_file, write_json, strip_comments

OUTPUT_DIR = Path.cwd() / 'outputs'
OUTPUT_DIR.mkdir(exist_ok=True)

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.main path/to/file.c")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print("Input file does not exist:", path)
        sys.exit(1)

    print("Parsing file:", path)
    macros, types, apis, counts, method = parse_all(str(path))
    print("Parser method used:", method)

    # Write JSON files
    macros_out = [m for m in macros]
    types_out = [t for t in types]
    apis_out = [a for a in apis]

    write_json(str(OUTPUT_DIR / 'macros.json'), macros_out)
    write_json(str(OUTPUT_DIR / 'types.json'), types_out)
    write_json(str(OUTPUT_DIR / 'apis.json'), apis_out)

    # Numeric double-check:
    # For more robust counting of constructs in the input file, use fallback counting.
    src_raw = read_file(str(path))
    src_noc = strip_comments(src_raw)

    # Count macros in file (simple)
    macro_count_file = sum(1 for _ in [m for m in src_noc.splitlines() if m.strip().startswith('#define')])

    # Count enums (typdefs + plain)
    enum_count_file = len([_ for _ in re_findall(r'\benum\b', src_noc)])
    # But enum_count_file could be noisy; prefer counting 'typedef enum' and standalone 'enum NAME {'
    enum_count_file = 0
    enum_count_file += len(re_findall(r'typedef\s+enum\s*\{', src_noc))
    enum_count_file += len(re_findall(r'enum\s+[A-Za-z_]\w*\s*\{', src_noc))

    # Count typedef struct occurrences
    struct_count_file = len(re_findall(r'typedef\s+struct\s*\{', src_noc)) + len(re_findall(r'typedef\s+struct\s+[A-Za-z_]\w*\s*\{', src_noc))

    # Count function defs: occurrences of ')' followed by '{' ignoring for/if/while patterns
    func_defs = len(re_findall(r'\)\s*\{', src_noc))
    # Count prototypes: ')' followed by ';' (but exclude function pointer declarations by simple heuristic)
    func_protos = len(re_findall(r'\)\s*;', src_noc))
    # Conservative function count = defs + prototypes
    func_count_file = func_defs + func_protos

    # Now counts from parser
    macro_count_json = counts.get('macros', 0)
    struct_count_json = counts.get('structs', 0)
    enum_count_json = counts.get('enums', 0)
    func_count_json = counts.get('functions', 0)

    # Print clean verification
    print("=== Verification ===")
    print(f"Macros   : file={macro_count_file}  json={macro_count_json}")
    print(f"Structs  : file~={struct_count_file}  json={struct_count_json}")
    print(f"Enums    : file~={enum_count_file}  json={enum_count_json}")
    print(f"Functions: file~={func_count_file}  json={func_count_json}")
    print()
    print("Note: file-side counts are heuristic approximations (regex) to help detect mismatches.")
    print("If you need byte-perfect verification, run with libclang installed (recommended).")

# helper using local import to avoid circular imports
def re_findall(pattern, s):
    import re
    return re.findall(pattern, s, flags=re.M)

if __name__ == '__main__':
    main()
