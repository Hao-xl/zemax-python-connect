from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from zemax_connection import SUPPORTED_VERSIONS, ZemaxInteractiveAPI, classify_connection_error  # noqa: E402


def ensure_two_editable_surfaces(system) -> None:
    lde = system.LDE
    while int(lde.NumberOfSurfaces) < 3:
        lde.InsertNewSurfaceAt(int(lde.NumberOfSurfaces) - 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Make a safe visible comment edit through Interactive Extension.")
    parser.add_argument("--zemax-root", default=None, help="OpticStudio install directory or Zemax data directory.")
    parser.add_argument("--version", type=int, choices=SUPPORTED_VERSIONS, default=None)
    parser.add_argument("--deep-search", action="store_true")
    parser.add_argument("--instance", type=int, default=0, help="Interactive Extension instance number shown in OpticStudio.")
    parser.add_argument("--comment", default="Touched by Python Interactive Extension")
    args = parser.parse_args()

    try:
        with ZemaxInteractiveAPI(
            zemax_root=args.zemax_root,
            preferred_version=args.version,
            deep_search=args.deep_search,
            instance=args.instance,
        ) as z:
            system = z.system
            ensure_two_editable_surfaces(system)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            s1 = system.LDE.GetSurfaceAt(1)
            s2 = system.LDE.GetSurfaceAt(2)
            s1.Comment = args.comment
            s2.Comment = f"Visible API edit {stamp}"
            try:
                z.app.ProgressPercent = 100
                z.app.ProgressMessage = "Interactive comment test complete"
            except Exception:
                pass
            print("MODE=InteractiveExtension")
            print(f"INSTANCE={args.instance}")
            print("STATUS=OK")
            print("ACTION=comment_stamp")
            print(f"SURFACE_COUNT={int(system.LDE.NumberOfSurfaces)}")
            print(f"SURFACE_1_COMMENT={s1.Comment}")
            print(f"SURFACE_2_COMMENT={s2.Comment}")
            return 0
    except Exception as exc:
        classification = classify_connection_error(exc)
        print("MODE=InteractiveExtension")
        print(f"INSTANCE={args.instance}")
        print("STATUS=FAILED")
        print(f"ERROR={exc}")
        print(f"ERROR_CODE={classification['error_code']}")
        print(f"ACTION={classification['action']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
