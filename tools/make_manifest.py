# tools/make_manifest.py
import hashlib, json, os, sys
from pathlib import Path

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def build_manifest(os_tok: str, backend: str, version: str, repo_root: Path) -> dict:
    wheels = []
    # base (optional)
    base_dir = repo_root / "ext" / "wheels" / os_tok / "base" / version
    if base_dir.exists():
        for w in sorted(base_dir.glob("*.whl")):
            key = f"wheels/{os_tok}/base/{version}/{w.name}"
            wheels.append({"path": key, "sha256": sha256_file(w)})

    # backend (required)
    be_dir = repo_root / "ext" / "wheels" / os_tok / backend / version
    if not be_dir.exists():
        raise SystemExit(f"missing backend dir: {be_dir}")
    if not any(be_dir.glob('*.whl')):
        raise SystemExit(f"no wheels found in: {be_dir}")
    for w in sorted(be_dir.glob("*.whl")):
        key = f"wheels/{os_tok}/{backend}/{version}/{w.name}"
        wheels.append({"path": key, "sha256": sha256_file(w)})

    return {
        "schema": 1,
        "os": os_tok,
        "backend": backend,
        "version": version,
        "wheels": wheels,
    }

if __name__ == "__main__":
    # Usage: python tools/make_manifest.py win cpu v1.50.2 > cloudflare/tmp_manifest.json
    os_tok, backend, version = sys.argv[1:4]
    repo_root = Path(__file__).resolve().parents[1]
    m = build_manifest(os_tok, backend, version, repo_root)
    print(json.dumps(m, indent=2))
