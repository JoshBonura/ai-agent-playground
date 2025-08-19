# treeprint.py
import os
import sys
import argparse
from typing import Iterable, Tuple

def split_entries(path: str) -> Tuple[list, list]:
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return [], []
    files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
    dirs  = [e for e in entries if os.path.isdir(os.path.join(path, e))]
    return files, dirs

def can_encode(stream, sample: str) -> bool:
    try:
        sample.encode(stream.encoding or "utf-8")
        return True
    except Exception:
        return False

def walk_tree(
    root: str,
    out,
    prefix: str,
    depth: int,
    max_depth: int | None,
    dirs_first: bool,
    show_empty: bool,
    glyphs: dict
):
    if max_depth is not None and depth > max_depth:
        return

    files, dirs = split_entries(root)
    if dirs_first:
        seqs: Iterable[Tuple[str, list]] = (("dir", dirs), ("file", files))
    else:
        seqs = (("file", files), ("dir", dirs))

    # If empty
    if not files and not dirs:
        if show_empty:
            print(prefix + glyphs["ell"] + "(empty)", file=out)
        return

    # We print in two passes (files vs dirs) to support dirs_first
    # Determine if there will be *any* entries after this pass to choose connector
    def emit_items(items: list, is_last_group: bool):
        for i, name in enumerate(items):
            is_last_item = (i == len(items) - 1) and is_last_group
            connector = glyphs["ell"] if is_last_item else glyphs["tee"]
            print(prefix + connector + name, file=out)

    # Count total entries to know global “lastness” within the folder
    total = (len(dirs) if dirs_first else len(files)) + (len(files) if dirs_first else len(dirs))

    printed = 0
    for kind, items in seqs:
        if not items:
            continue
        # For files we just print
        if kind == "file":
            is_last_group = (printed + len(items) == total)
            emit_items(items, is_last_group)
            printed += len(items)
        else:
            # dirs: print each + recurse
            for j, d in enumerate(items):
                printed += 1
                is_last_entry = (printed == total)
                connector = glyphs["ell"] if is_last_entry else glyphs["tee"]
                print(prefix + connector + d, file=out)
                # Extend prefix for children
                extension = glyphs["space"] if is_last_entry else glyphs["bar"]
                # Recurse
                walk_tree(
                    os.path.join(root, d), out, prefix + extension,
                    depth + 1, max_depth, dirs_first, show_empty, glyphs
                )

def main():
    ap = argparse.ArgumentParser(description="Print a directory tree.")
    ap.add_argument("root", help="Root directory to print")
    ap.add_argument("--out", "-o", help="Write to a file (UTF-8). If omitted, print to stdout.")
    ap.add_argument("--max-depth", type=int, default=None, help="Limit depth (root is depth=0).")
    ap.add_argument("--dirs-first", action="store_true", help="List folders before files.")
    ap.add_argument("--show-empty", action="store_true", help="Show '(empty)' for empty folders.")
    ap.add_argument("--ascii", action="store_true", help="Force ASCII connectors instead of box-drawing.")
    args = ap.parse_args()

    # Choose glyph set
    unicode_glyphs = {"tee": "├── ", "ell": "└── ", "bar": "│   ", "space": "    "}
    ascii_glyphs   = {"tee": "|-- ", "ell": "`-- ", "bar": "|   ", "space": "    "}

    glyphs = ascii_glyphs if args.ascii else unicode_glyphs

    # Decide output stream
    if args.out:
        out = open(args.out, "w", encoding="utf-8", newline="")
        close_out = True
        # When writing to file, we can safely use Unicode glyphs if not forcing ASCII
        if not args.ascii:
            glyphs = unicode_glyphs
    else:
        out = sys.stdout
        close_out = False
        # If stdout can't encode the Unicode glyphs, fall back to ASCII automatically
        if not args.ascii and not can_encode(out, "├"):
            glyphs = ascii_glyphs

    root = os.path.abspath(args.root)
    print(os.path.basename(root) or root, file=out)
    walk_tree(
        root, out, prefix="", depth=0, max_depth=args.max_depth,
        dirs_first=args.dirs_first, show_empty=args.show_empty, glyphs=glyphs
    )

    if close_out:
        out.close()

if __name__ == "__main__":
    main()
