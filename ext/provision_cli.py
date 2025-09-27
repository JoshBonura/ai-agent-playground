# ext/provision_cli.py
from __future__ import annotations
import os, sys
from pathlib import Path

def main() -> int:
    os.environ.setdefault("LOG_RUNTIME_DEBUG", "1")

    # Ensure the app-data root exists
    data_dir = os.getenv("LOCALMIND_DATA_DIR")
    if data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)

    # Make wheels/requirements discoverable (already set by Electron)
    wheels_root = os.getenv("LM_WHEELS_ROOT") or ""
    req_root = os.getenv("LM_REQUIREMENTS_ROOT") or ""
    if not Path(wheels_root).exists():
        print(f"[provisioner] LM_WHEELS_ROOT not found: {wheels_root}", flush=True)

    from ext.common import current_os, VALID
    from ext.provision import provision_runtime, warm_provision_all_possible

    try:
        wanted = (os.getenv("LM_PROVISION_BACKENDS") or "").strip()
        if wanted:
            os_name = current_os()
            backends = [b.strip() for b in wanted.split(",") if b.strip()]
            for b in backends:
                if b not in VALID.get(os_name, []):
                    print(f"[provisioner] skip invalid backend for {os_name}: {b}", flush=True)
                    continue
                print(f"[provisioner] provisioning {os_name}/{b}", flush=True)
                provision_runtime(os_name, b)
        else:
            warm_provision_all_possible()
        print("[provisioner] OK", flush=True)
        return 0
    except Exception as e:
        print(f"[provisioner] ERROR: {e}", flush=True)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
