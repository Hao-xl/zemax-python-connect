from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from zemax_connection import SUPPORTED_VERSIONS, ZemaxInteractiveAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal Interactive Extension ZOS-API usage example.")
    parser.add_argument("--zemax-root", default=None)
    parser.add_argument("--version", type=int, choices=SUPPORTED_VERSIONS, default=None)
    parser.add_argument("--deep-search", action="store_true")
    parser.add_argument("--instance", type=int, default=0)
    args = parser.parse_args()

    with ZemaxInteractiveAPI(
        zemax_root=args.zemax_root,
        preferred_version=args.version,
        deep_search=args.deep_search,
        instance=args.instance,
    ) as z:
        print("MODE=InteractiveExtension")
        print("STATUS=OK")
        print(f"INSTANCE={args.instance}")
        print(f"APP_MODE={z.app.Mode}")
        print(f"LICENSE={z.app.LicenseStatus}")
        print(f"SURFACE_COUNT={int(z.system.LDE.NumberOfSurfaces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
