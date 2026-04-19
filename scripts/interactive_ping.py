from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from zemax_connection import ZemaxInteractiveAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ZOS-API Interactive Extension connection.")
    parser.add_argument("--zemax-root", default=None, help="OpticStudio install directory or Zemax data directory.")
    parser.add_argument("--instance", type=int, default=0, help="Interactive Extension instance number shown in OpticStudio.")
    parser.add_argument("--json", action="store_true", help="Print full diagnostic JSON.")
    args = parser.parse_args()

    try:
        with ZemaxInteractiveAPI(zemax_root=args.zemax_root, instance=args.instance, require_valid_license=False) as z:
            info = z.diagnostic_info()
            ok = bool(info.get("is_valid_license")) and bool(info.get("has_primary_system"))
            status = "OK" if ok else "NOT_AUTHORIZED"
            if args.json:
                info["status"] = status
                print(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                print("MODE=InteractiveExtension")
                print(f"INSTANCE={args.instance}")
                print(f"STATUS={status}")
                print(f"ZEMAX_ROOT={info.get('resolved_root', '')}")
                print(f"NET_HELPER={info.get('net_helper_path', '')}")
                print(f"ZEMAX_DIR={info.get('zemax_dir', '')}")
                print(f"IS_VALID_LICENSE={info.get('is_valid_license', False)}")
                print(f"LICENSE={info.get('license_status', '')}")
                print(f"APP_MODE={info.get('app_mode', '')}")
                print(f"SERIAL_CODE={info.get('serial_code', '')}")
                print(f"HAS_PRIMARY_SYSTEM={info.get('has_primary_system', False)}")
        return 0 if status == "OK" else 2
    except Exception as exc:
        if args.json:
            print(json.dumps({"mode": "InteractiveExtension", "instance": args.instance, "status": "CONNECT_FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print("MODE=InteractiveExtension")
            print(f"INSTANCE={args.instance}")
            print("STATUS=CONNECT_FAILED")
            print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
