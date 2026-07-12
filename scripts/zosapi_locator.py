from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from zemax_connection import (  # noqa: E402
    SUPPORTED_VERSIONS,
    ScanStats,
    classify_connection_error,
    discover_candidates,
    locate_zosapi,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Locate OpticStudio ZOS-API DLLs.")
    parser.add_argument("--zemax-root", default=None, help="OpticStudio install directory or Zemax data directory.")
    parser.add_argument("--version", type=int, choices=SUPPORTED_VERSIONS, default=None, help="Preferred OpticStudio release year.")
    parser.add_argument(
        "--deep-search",
        action="store_true",
        help="Force the bounded fixed-disk search. Bounded search already runs automatically when quick sources fail.",
    )
    parser.add_argument("--exhaustive-search", action="store_true", help="Request an unbounded fixed-disk search after bounded search fails.")
    parser.add_argument(
        "--confirm-long-scan",
        action="store_true",
        help="Confirm the user was told the estimate and explicitly approved the long scan.",
    )
    parser.add_argument("--list-candidates", action="store_true", help="Print all candidate roots before selecting one.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    stats = ScanStats()
    try:
        candidates = discover_candidates(
            args.zemax_root,
            args.version,
            args.deep_search,
            exhaustive_search=args.exhaustive_search,
            confirm_long_scan=args.confirm_long_scan,
            scan_stats=stats,
        )
    except Exception as exc:
        result = {
            "status": "FAILED",
            "error": str(exc),
            **classify_connection_error(exc),
            "scan": stats.to_dict(),
            "candidates": [],
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("STATUS=FAILED")
            print(f"ERROR={exc}")
            print(f"SCANNED_DIRECTORIES={stats.scanned_directories}")
            print(f"PERMISSION_DENIED_DIRECTORIES={stats.permission_denied_directories}")
        return 1

    if args.list_candidates and not args.json:
        if not candidates:
            print("CANDIDATES=NONE")
        else:
            for idx, item in enumerate(candidates):
                print(
                    f"CANDIDATE[{idx}]={item.path} SOURCE={item.source} KIND={item.root_kind} "
                    f"VERSION={item.version or 'unknown'} HAS_NET_HELPER={item.has_net_helper}"
                )

    try:
        loc = locate_zosapi(args.zemax_root, args.version, candidates=candidates)
    except Exception as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "status": "FAILED",
                        "error": str(exc),
                        **classify_connection_error(exc),
                        "scan": stats.to_dict(),
                        "candidates": [item.to_dict() for item in candidates] if args.list_candidates else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("STATUS=FAILED")
            print(f"ERROR={exc}")
            print(f"SCANNED_DIRECTORIES={stats.scanned_directories}")
            print(f"PERMISSION_DENIED_DIRECTORIES={stats.permission_denied_directories}")
        return 1

    data = loc.to_dict()
    data["status"] = "OK"
    data["scan"] = stats.to_dict()
    if args.list_candidates:
        data["candidates"] = [item.to_dict() for item in candidates]
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("STATUS=OK")
        print(f"REQUESTED_ROOT={loc.requested_root or ''}")
        print(f"RESOLVED_ROOT={loc.resolved_root}")
        print(f"ROOT_KIND={loc.root_kind}")
        print(f"SOURCE={loc.source}")
        print(f"DETECTED_VERSION={loc.detected_version or ''}")
        print(f"NET_HELPER={loc.net_helper_path}")
        print(f"INITIALIZER_PATH={loc.initializer_path}")
        print(f"SCANNED_DIRECTORIES={stats.scanned_directories}")
        print(f"PERMISSION_DENIED_DIRECTORIES={stats.permission_denied_directories}")
        for note in loc.notes:
            print(f"NOTE={note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
