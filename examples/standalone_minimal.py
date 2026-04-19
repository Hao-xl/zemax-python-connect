from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from zemax_connection import ZemaxStandaloneAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal standalone ZOS-API usage example.")
    parser.add_argument("--zemax-root", default=None)
    args = parser.parse_args()

    with ZemaxStandaloneAPI(zemax_root=args.zemax_root) as z:
        print("MODE=StandaloneApplication")
        print("STATUS=OK")
        print(f"APP_MODE={z.app.Mode}")
        print(f"LICENSE={z.app.LicenseStatus}")
        print(f"SURFACE_COUNT={int(z.system.LDE.NumberOfSurfaces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
