import os, sys

# Force UTF-8 stdout on Windows so redirects don't garble output
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Root to scan (arg 1) or current directory
root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
OUTPUT_FILE = os.path.join(root, "my-structure.txt")

ignore_full = {"target", "dist", "__pycache__"}
collapse = {".git"}                   # show marker only
expand_two_levels = {".venv"}         # expand .venv two levels (+ special case for site-packages)
expand_one_level = {"node_modules"}   # expand node_modules one level
expand_full = {"agent", "aimodel"}    # always expand fully

def listdir_safe(path):
    try:
        return sorted(os.listdir(path))
    except (PermissionError, FileNotFoundError):
        return []

def print_line(lines, depth, name, is_dir):
    indent = "  " * depth
    lines.append(f"{indent}{name}{'/' if is_dir else ''}")

def walk(path, depth=0, lines=None):
    if lines is None:
        lines = []
        print_line(lines, 0, os.path.basename(path.rstrip(os.sep)) or path, True)

    entries = listdir_safe(path)
    dirs, files = [], []

    for entry in entries:
        # 🚫 skip fully ignored names anywhere in the tree
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

        # expand .venv two levels (with special case for site-packages)
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
                    print_line(lines, depth + 3, grand, is_grand_dir)

                    if child.lower() == "lib" and grand == "site-packages" and is_grand_dir:
                        for p in listdir_safe(grand_full):
                            if p in ignore_full:
                                continue
                            print_line(lines, depth + 4, p, os.path.isdir(os.path.join(grand_full, p)))
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
    # Write to file
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"\n[✓] Saved structure to {OUTPUT_FILE}")
