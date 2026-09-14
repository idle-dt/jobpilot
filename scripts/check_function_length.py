"""Enforce the CLAUDE.md limits: max 30 lines per function, max 300 lines per file.

Ruff's PLR0915 counts statements, not lines, and enabling it repo-wide would flag 20
pre-existing functions. This checks the literal rule against the files given on the command
line, so new and changed code is held to it without demanding a cleanup of everything else.

Usage: python scripts/check_function_length.py <file.py> [<file.py> ...]
"""

import ast
import sys
from pathlib import Path

MAX_FUNCTION_LINES = 30
MAX_FILE_LINES = 300


def violations(path: Path) -> list[str]:
    """Return one message per limit the file breaches."""
    source = path.read_text(encoding="utf-8")
    found = []

    file_lines = len(source.splitlines())
    if file_lines > MAX_FILE_LINES:
        found.append(f"{path}: file is {file_lines} lines (max {MAX_FILE_LINES})")

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        length = node.end_lineno - node.lineno + 1
        if length > MAX_FUNCTION_LINES:
            found.append(
                f"{path}:{node.lineno}: {node.name}() is {length} lines "
                f"(max {MAX_FUNCTION_LINES})"
            )
    return found


def main(argv: list[str]) -> int:
    """Check every path given. Returns 1 if any limit is breached."""
    found = []
    for arg in argv:
        path = Path(arg)
        if path.suffix == ".py" and path.is_file():
            found.extend(violations(path))

    for message in found:
        print(message)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
