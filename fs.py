import os
import sys
from typing import Any, cast

# ---- stdout safety (Windows redirects, etc.) ----
try:
    out = cast(Any, sys.stdout)
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Root to scan (arg 1) or current directory
root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
OUTPUT_FILE = os.path.join(root, "my-structure.txt")

# ---- config ----
ignore_full = {
    "target",
    "dist",
    "__pycache__",
    "node_modules",
    ".venv",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".DS_Store",
    "bin",
    ".pyi_build"
    ".ruff_cache"
    "bind"
}
collapse = {".git"}  # show marker only
expand_two_levels = {".venv"}  # expand .venv two levels (but collapse site-packages)
expand_one_level = {"node_modules"}  # expand node_modules one level
expand_full = {"agent", "aimodel"}  # always expand fully
MAX_DEPTH = None  # set to an int (e.g., 6) to hard-cap recursion depth


def listdir_safe(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except (PermissionError, FileNotFoundError):
        return []


def print_line(lines: list[str], depth: int, name: str, is_dir: bool) -> None:
    indent = "  " * depth
    lines.append(f"{indent}{name}{'/' if is_dir else ''}")


def walk(path: str, depth: int = 0, lines: list[str] | None = None) -> list[str]:
    if lines is None:
        lines = []
        print_line(lines, 0, os.path.basename(path.rstrip(os.sep)) or path, True)

    # depth guard
    if MAX_DEPTH is not None and depth >= MAX_DEPTH:
        return lines

    entries = listdir_safe(path)
    dirs: list[str] = []
    files: list[str] = []

    for entry in entries:
        if entry in ignore_full:
            continue
        full = os.path.join(path, entry)
        (dirs if os.path.isdir(full) else files).append(entry)

    # files first (stable)
    for f in files:
        print_line(lines, depth + 1, f, False)

    # then directories
    for d in dirs:
        full = os.path.join(path, d)

        # collapse heavy dirs completely
        if d in collapse:
            print_line(lines, depth + 1, d, True)
            continue

        # expand .venv two levels (collapse site-packages)
        if d in expand_two_levels:
            print_line(lines, depth + 1, d, True)
            for child in listdir_safe(full):
                if child in ignore_full:
                    continue
                child_full = os.path.join(full, child)
                is_child_dir = os.path.isdir(child_full)
                print_line(lines, depth + 2, child, is_child_dir)

                if not is_child_dir:
                    continue

                for grand in listdir_safe(child_full):
                    if grand in ignore_full:
                        continue
                    grand_full = os.path.join(child_full, grand)
                    is_grand_dir = os.path.isdir(grand_full)

                    # collapse site-packages to a single marker line
                    if grand == "site-packages" and is_grand_dir:
                        print_line(lines, depth + 3, "site-packages/ …", True)
                        continue

                    print_line(lines, depth + 3, grand, is_grand_dir)
            continue

        # expand node_modules just one level
        if d in expand_one_level:
            print_line(lines, depth + 1, d, True)
            for child in listdir_safe(full):
                if child in ignore_full:
                    continue
                child_full = os.path.join(full, child)
                print_line(lines, depth + 2, child, os.path.isdir(child_full))
            continue

        # expand agent and aimodel fully (normal recursion)
        if d in expand_full:
            print_line(lines, depth + 1, d, True)
            walk(full, depth + 1, lines)
            continue

        # default recursion
        print_line(lines, depth + 1, d, True)
        walk(full, depth + 1, lines)

    return lines


if __name__ == "__main__":
    lines = walk(root)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"\n[✓] Saved structure to {OUTPUT_FILE}")
