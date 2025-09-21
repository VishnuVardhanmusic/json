# C Parser Project
Usage
python -m src.main sample_input/sample.c

Generates three JSONs from a C source file:
- `outputs/macros.json`
- `outputs/types.json` (structs + enums)
- `outputs/apis.json`

Usage:
1. Install system `libclang` (recommended).
2. Create venv and install requirements: `pip install -r requirements.txt`
3. Run: `python -m src.main sample_input/sample.c`

Notes:
- Parser will use libclang when available (most accurate).
- If libclang not available, a regex fallback is used (conservative).
- Output JSON entries include a `comment` field obeying your template:
  - MACROS = macro defined with name {name} and value {value}
  - STRUCT & ENUM = defined with name {name} and have {num_of_mem} members
  - API = Function with name {name} having {num_of_params} arguments with return type {r_type}
- At the end the program prints a numeric verification comparing heuristic counts from the file vs produced JSON counts.
