from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from zemax_connection import candidate_roots, locate_zosapi  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Locate OpticStudio ZOS-API DLLs.")
    parser.add_argument("--zemax-root", default=None, help="OpticStudio install directory or Zemax data directory.")
    parser.add_argument("--list-candidates", action="store_true", help="Print all candidate roots before selecting one.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    if args.list_candidates:
        candidates = candidate_roots(args.zemax_root)
        if args.json:
            print(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2))
        else:
            for idx, item in enumerate(candidates):
                print(f"CANDIDATE[{idx}]={item}")

    try:
        loc = locate_zosapi(args.zemax_root)
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print("STATUS=FAILED")
            print(f"ERROR={exc}")
        return 1

    data = loc.to_dict()
    data["status"] = "OK"
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("STATUS=OK")
        print(f"REQUESTED_ROOT={loc.requested_root or ''}")
        print(f"RESOLVED_ROOT={loc.resolved_root}")
        print(f"ROOT_KIND={loc.root_kind}")
        print(f"NET_HELPER={loc.net_helper_path}")
        print(f"INITIALIZER_PATH={loc.initializer_path}")
        for note in loc.notes:
            print(f"NOTE={note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
