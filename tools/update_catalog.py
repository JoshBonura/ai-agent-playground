#!/usr/bin/env python3
r"""
Update R2 catalog.json with a new runtime build.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from datetime import datetime, timezone

def resolve_wrangler_bin(cwd: Path) -> str:
    bin_dir = cwd / "node_modules" / ".bin"
    if os.name == "nt":
        for name in ("wrangler.cmd", "wrangler.exe", "wrangler"):
            p = bin_dir / name
            if p.exists():
                return str(p.resolve())
    else:
        p = bin_dir / "wrangler"
        if p.exists():
            return str(p.resolve())
    return "wrangler"

def run(cmd, cwd=None, check=True):
    print(">", " ".join(map(str, cmd)))
    return subprocess.run(cmd, cwd=cwd, check=check)

def load_json_any_encoding(p: Path) -> dict:
    raw = p.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            pass
    raise RuntimeError("catalog.json: unable to decode (not UTF-8/UTF-16)")

def main():
    ap = argparse.ArgumentParser(description="Update runtimes/catalog.json in R2")
    ap.add_argument("--cwd", default="cloudflare")
    ap.add_argument("os", choices=["win","linux","mac"])
    ap.add_argument("backend")
    ap.add_argument("version")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--set-latest", action="store_true")
    ap.add_argument("--notes", default=None)
    ap.add_argument("--channel", default=None)
    args = ap.parse_args()

    cwd = Path(args.cwd).resolve()
    if not (cwd / "wrangler.toml").exists():
        print(f"ERROR: wrangler.toml not found under {cwd}", file=sys.stderr)
        sys.exit(2)

    WRANGLER = resolve_wrangler_bin(cwd)
    tmpdir = Path(tempfile.mkdtemp(prefix="catalog_update_"))
    local_catalog = tmpdir / "catalog.json"

    # 1) fetch or init
    try:
        run([WRANGLER, "r2", "object", "get", "--remote",
             "runtimes/catalog.json", "--file", str(local_catalog)],
            cwd=str(cwd), check=True)
        catalog = load_json_any_encoding(local_catalog)
    except subprocess.CalledProcessError:
        print("No existing catalog.json; creating a new one.")
        catalog = {"schema": 1, "latest": {}, "builds": []}

    # 2) upsert build
    manifest_key = args.manifest or f"manifests/{args.os}/{args.backend}/{args.version}.json"
    ts = datetime.now(timezone.utc).isoformat()
    builds = catalog.setdefault("builds", [])
    found = None
    for b in builds:
        if b.get("os")==args.os and b.get("backend")==args.backend and b.get("version")==args.version:
            found = b; break
    if found:
        found["manifest"] = manifest_key
        found["updatedAt"] = ts
        if args.notes is not None: found["notes"] = args.notes
        if args.channel is not None: found["channel"] = args.channel
    else:
        entry = {"os": args.os, "backend": args.backend, "version": args.version,
                 "manifest": manifest_key, "publishedAt": ts}
        if args.notes is not None: entry["notes"] = args.notes
        if args.channel is not None: entry["channel"] = args.channel
        builds.append(entry)

    if args.set_latest:
        latest = catalog.setdefault("latest", {})
        latest.setdefault(args.os, {})
        latest[args.os][args.backend] = args.version

    # 3) write UTF-8 (normalized) and upload with content-type
    local_catalog.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    run([WRANGLER, "r2", "object", "put", "--remote",
         "runtimes/catalog.json", "--file", str(local_catalog),
         "--content-type", "application/json"],
        cwd=str(cwd), check=True)

    print("\n✅ catalog.json updated.")
    print("   View: https://lic-server.localmind.workers.dev/runtime/catalog")

    try: shutil.rmtree(tmpdir)
    except Exception: pass

if __name__ == "__main__":
    main()
