from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from zemax_connection import ZemaxInteractiveAPI, ZemaxStandaloneAPI, candidate_roots, locate_zosapi  # noqa: E402


def try_locator(zemax_root: str | None) -> dict:
    try:
        loc = locate_zosapi(zemax_root)
        data = loc.to_dict()
        data["status"] = "OK"
        return data
    except Exception as exc:
        return {"status": "FAILED", "error": str(exc)}


def try_standalone(zemax_root: str | None) -> dict:
    try:
        with ZemaxStandaloneAPI(zemax_root=zemax_root, require_valid_license=False) as z:
            info = z.diagnostic_info()
            info["status"] = "OK" if info.get("is_valid_license") and info.get("has_primary_system") else "NOT_AUTHORIZED"
            return info
    except Exception as exc:
        return {"status": "CONNECT_FAILED", "error": str(exc)}


def try_interactive(zemax_root: str | None, instance: int) -> dict:
    try:
        with ZemaxInteractiveAPI(zemax_root=zemax_root, instance=instance, require_valid_license=False) as z:
            info = z.diagnostic_info()
            info["status"] = "OK" if info.get("is_valid_license") and info.get("has_primary_system") else "NOT_AUTHORIZED"
            return info
    except Exception as exc:
        return {"status": "CONNECT_FAILED", "error": str(exc), "instance": instance}


def recommendations(report: dict) -> list[str]:
    recs: list[str] = []
    locator = report.get("locator", {})
    if locator.get("status") != "OK":
        recs.append("Pass --zemax-root pointing to the OpticStudio install directory or Zemax data directory.")
        return recs

    interactive = report.get("interactive")
    if interactive:
        status = interactive.get("status")
        if status == "CONNECT_FAILED":
            recs.append("In OpticStudio, click the independent Programming > Interactive Extension button in the ZOS-API.NET area and keep the waiting dialog open.")
        elif status == "NOT_AUTHORIZED":
            recs.append("If APP_MODE is Server or license is NotAuthorized, restart the independent Interactive Extension dialog; do not use the Python dropdown template generator.")
        elif status == "OK":
            recs.append("Interactive Extension is ready. Use ConnectAsExtension(instance) and do not call CloseApplication().")

    standalone = report.get("standalone")
    if standalone:
        status = standalone.get("status")
        if status == "OK":
            recs.append("Standalone Application is ready. Use CreateNewApplication() and close it with CloseApplication() when finished.")
        elif status == "NOT_AUTHORIZED":
            recs.append("Standalone connected but license/API authorization is invalid. Close hidden OpticStudio processes or restart OpticStudio, then rerun standalone_ping.py; if it persists, check license and ZOS-API support.")
    return recs


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Zemax OpticStudio Python/ZOS-API connection setup.")
    parser.add_argument("--zemax-root", default=None)
    parser.add_argument("--mode", choices=["locator", "standalone", "interactive", "both"], default="locator")
    parser.add_argument("--instance", type=int, default=0)
    parser.add_argument("--list-candidates", action="store_true")
    args = parser.parse_args()

    report: dict = {"mode": args.mode}
    if args.list_candidates:
        report["candidates"] = candidate_roots(args.zemax_root)
    report["locator"] = try_locator(args.zemax_root)

    if args.mode in ("standalone", "both"):
        report["standalone"] = try_standalone(args.zemax_root)
    if args.mode in ("interactive", "both"):
        report["interactive"] = try_interactive(args.zemax_root, args.instance)
    report["recommendations"] = recommendations(report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["locator"].get("status") != "OK":
        return 1
    for key in ("standalone", "interactive"):
        if key in report and report[key].get("status") not in ("OK", None):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
