from __future__ import annotations
from pathlib import Path
from typing import Iterable
import sys, os, argparse

# Force UTF-8 stdout on Windows so redirects don't garble output
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# Folders (relative to this script's directory) to search completely.
# Add/remove as you like.
# ──────────────────────────────────────────────────────────────────────────────
SEARCH_FOLDERS = [
    "aimodel/file_read",
    "frontend/src/file_read",
]

# ──────────────────────────────────────────────────────────────────────────────
# Optional: filename/path substring matches (case-insensitive).
# If used, any text-like file whose RELATIVE PATH contains one of these strings
# will be printed (helpful to pull in Dockerfiles, envs, etc. anywhere).
# (Note: fixed the missing comma before ".java".)
# ──────────────────────────────────────────────────────────────────────────────
NAME_MATCHES: list[str] = [
    "env.development",
    "application.properties",
    "requirements.txt"
]

# ──────────────────────────────────────────────────────────────────────────────
# Discovery rules & filters
# ──────────────────────────────────────────────────────────────────────────────
IGNORE_DIRS = {
    ".git", ".venv", "node_modules", "target", "build", "dist", ".mvn",
    ".idea", ".vscode", "__pycache__", ".cache", ".vite", ".vite-temp"
}

IGNORE_BASENAMES = {
    "package-lock.json",
    "package.json",
    "postcss.config.js"   # skip npm lockfile
    # add more if you want:
    # "yarn.lock", "pnpm-lock.yaml", "bun.lockb"
}

ALLOWED_EXTS = {
    ".java", ".kt", ".kts",
    ".py",
    ".xml", ".properties", ".yml", ".yaml", ".conf", ".ini",
    ".json", ".md", ".txt", ".env",
    ".js", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".css", ".scss", ".sass",
    ".html",
    ".sh", ".bat", ".cmd", ".ps1",
    ".gradle", ".pom",".development"
}

MAX_SIZE_BYTES = 1_000_000  # skip files > 1MB


def is_texty(p: Path) -> bool:
    if not p.is_file():
        return False
    if p.name in IGNORE_BASENAMES:   # ⬅️ skip specific files by name
        return False
    if p.suffix.lower() in ALLOWED_EXTS:
        try:
            if p.stat().st_size > MAX_SIZE_BYTES:
                return False
        except OSError:
            return False
        return True
    return False


def norm_rel(project_root: Path, p: Path) -> str:
    """Always show posix-ish relative path in headers."""
    try:
        rel = p.relative_to(project_root)
    except ValueError:
        rel = p
    return rel.as_posix()


def _normalize_output(s: str) -> str:
    # common cp1252/utf-8 mojibake seen in prior dumps
    repl = {
        "ΓÇÖ": "’", "ΓÇ£": "“", "ΓÇ¥": "”", "ΓÇô": "–", "ΓÇö": "—", "ΓÇª": "…",
        "â€™": "’", "â€œ": "“", "â€�": "”", "â€“": "–", "â€”": "—", "â€¦": "…",
        # occasional double-encoded forms
        "Ã¢â‚¬â„¢": "’", "Ã¢â‚¬Å“": "“", "Ã¢â‚¬Â�": "”",
        "Ã¢â‚¬â€œ": "–", "Ã¢â‚¬â€�": "—", "Ã¢â‚¬Â¦": "…",
        # stray NBSP marker that sometimes sneaks in
        "Â ": " ",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def dump_one(project_root: Path, p: Path, printed: set[str]) -> None:
    rel = norm_rel(project_root, p)
    if rel in printed:
        return
    printed.add(rel)
    print(f"\n# ===== {rel} =====\n")
    try:
        # try UTF-8 first
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # fallback to Windows cp1252 if it's not UTF-8
        try:
            text = p.read_text(encoding="cp1252")
        except Exception as e:
            print(f"⚠️ Could not read {rel}: {e}")
            return
    except Exception as e:
        print(f"⚠️ Could not read {rel}: {e}")
        return

    # only print once, after decoding succeeded via either path
    print(_normalize_output(text))


def walk_selected_folders(project_root: Path) -> Iterable[Path]:
    """Yield text-like files from every folder listed in SEARCH_FOLDERS."""
    for folder in SEARCH_FOLDERS:
        base = (project_root / folder).resolve()
        if not base.exists() or not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if any(seg in IGNORE_DIRS for seg in p.parts):
                continue
            if is_texty(p):
                yield p


def walk_name_matches(project_root: Path) -> Iterable[Path]:
    """Yield text-like files anywhere whose RELATIVE PATH contains a NAME_MATCHES item."""
    if not NAME_MATCHES:
        return []
    lowers = [m.lower() for m in NAME_MATCHES]
    for p in sorted(project_root.rglob("*")):
        if any(seg in IGNORE_DIRS for seg in p.parts):
            continue
        if not is_texty(p):
            continue
        rel_lower = norm_rel(project_root, p).lower()
        if any(m in rel_lower for m in lowers):
            yield p


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Dump project files under selected folders (and/or name matches) to stdout."
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--matches", action="store_true",
                   help="Only dump files whose path contains any NAME_MATCHES.")
    g.add_argument("--both", action="store_true",
                   help="Dump both selected folders and NAME_MATCHES.")
    # default behavior: selected folders only
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    printed: set[str] = set()

    if args.matches:
        for p in walk_name_matches(project_root):
            dump_one(project_root, p, printed)
        return

    if args.both:
        for p in walk_selected_folders(project_root):
            dump_one(project_root, p, printed)
        for p in walk_name_matches(project_root):
            dump_one(project_root, p, printed)
        return

    # default: selected folders only
    for p in walk_selected_folders(project_root):
        dump_one(project_root, p, printed)


if __name__ == "__main__":
    main()
