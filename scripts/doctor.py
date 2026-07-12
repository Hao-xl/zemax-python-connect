from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import struct
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from zemax_connection import (  # noqa: E402
    ScanStats,
    SUPPORTED_VERSIONS,
    ZemaxInteractiveAPI,
    ZemaxStandaloneAPI,
    classify_connection_error,
    discover_candidates,
    initialize_zosapi,
    locate_zosapi,
)


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def environment_report() -> dict:
    return {
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "python_bitness": struct.calcsize("P") * 8,
        "pythonnet_version": package_version("pythonnet"),
        "clr_loader_version": package_version("clr-loader"),
    }


def failure(exc: BaseException, status: str = "FAILED") -> dict:
    return {"status": status, "error": str(exc), **classify_connection_error(exc)}


def try_locator(zemax_root: str | None, version: int | None, candidates: list) -> dict:
    try:
        location = locate_zosapi(zemax_root, version, candidates=candidates)
        return {"status": "OK", **location.to_dict()}
    except Exception as exc:
        return failure(exc)


def try_initializer(zemax_root: str, version: int | None) -> dict:
    try:
        _, location = initialize_zosapi(zemax_root, version)
        return {"status": "OK", **location.to_dict()}
    except Exception as exc:
        return failure(exc)


def connection_status(info: dict) -> str:
    ok = (
        bool(info.get("connected"))
        and bool(info.get("mode_valid"))
        and bool(info.get("is_valid_license"))
        and bool(info.get("has_primary_system"))
    )
    return "OK" if ok else "NOT_READY"


def try_standalone(zemax_root: str, version: int | None) -> dict:
    try:
        with ZemaxStandaloneAPI(
            zemax_root=zemax_root,
            preferred_version=version,
            require_valid_license=False,
        ) as connection:
            info = connection.diagnostic_info()
            info["status"] = connection_status(info)
            return info
    except Exception as exc:
        return failure(exc, "CONNECT_FAILED")


def try_interactive(
    zemax_root: str,
    version: int | None,
    instance: int,
) -> dict:
    try:
        with ZemaxInteractiveAPI(
            zemax_root=zemax_root,
            preferred_version=version,
            instance=instance,
            require_valid_license=False,
        ) as connection:
            info = connection.diagnostic_info()
            info["status"] = connection_status(info)
            return info
    except Exception as exc:
        result = failure(exc, "CONNECT_FAILED")
        result["instance"] = instance
        return result


def recommendations(report: dict) -> list[str]:
    items: list[str] = []
    if not report["environment"].get("pythonnet_version"):
        items.append("Install pythonnet with: python -m pip install pythonnet")
    locator = report.get("locator", {})
    if locator.get("error_code") == "MULTIPLE_INSTALLATIONS":
        items.append("Ask the user to choose 2021/2022/2023/2024/2025, a directory, or 'I don't know'.")
    elif locator.get("status") != "OK":
        items.append("Ask where OpticStudio or the Zemax Documents folder is located; include 'I don't know'.")
        scan = report.get("scan", {})
        items.append(
            "The default bounded scan inspected "
            f"{scan.get('scanned_directories', 0)} directories and encountered "
            f"{scan.get('permission_denied_directories', 0)} permission-denied directories."
        )
        items.append(
            "Before exhaustive search, tell the user the estimated duration and ask permission; after approval use "
            "--exhaustive-search --confirm-long-scan."
        )
    for key in ("initializer", "standalone", "interactive"):
        section = report.get(key, {})
        if section.get("error_code") == "IPC_ACCESS_DENIED":
            items.append("Request approval and rerun the same command outside the agent sandbox.")
    if report.get("standalone", {}).get("status") == "OK":
        items.append("Standalone is ready: use CreateNewApplication() and close only the instance Python created.")
    if report.get("interactive", {}).get("status") == "OK":
        items.append("Interactive Extension is ready: APP_MODE=Plugin; never call CloseApplication().")
    return list(dict.fromkeys(items))


def main() -> int:
    parser = argparse.ArgumentParser(description="One-command OpticStudio ZOS-API discovery and connection doctor.")
    parser.add_argument("--mode", choices=("locator", "standalone", "interactive", "both"), default="locator")
    parser.add_argument("--zemax-root", default=None)
    parser.add_argument("--version", type=int, choices=SUPPORTED_VERSIONS, default=None)
    parser.add_argument("--instance", type=int, default=0)
    parser.add_argument("--deep-search", action="store_true")
    parser.add_argument(
        "--exhaustive-search",
        action="store_true",
        help="Run an unbounded fixed-disk search only if quick and bounded discovery fail.",
    )
    parser.add_argument(
        "--confirm-long-scan",
        action="store_true",
        help="Confirm that the user was told the time estimate and explicitly approved exhaustive search.",
    )
    args = parser.parse_args()

    report: dict = {
        "schema_version": 2,
        "requested_mode": args.mode,
        "requested_version": args.version,
        "deep_search": args.deep_search,
        "exhaustive_search": args.exhaustive_search,
        "confirm_long_scan": args.confirm_long_scan,
        "environment": environment_report(),
    }
    scan_stats = ScanStats()
    candidates: list = []
    discovery_error: BaseException | None = None
    try:
        candidates = discover_candidates(
            args.zemax_root,
            args.version,
            args.deep_search,
            exhaustive_search=args.exhaustive_search,
            confirm_long_scan=args.confirm_long_scan,
            scan_stats=scan_stats,
        )
        report["candidates"] = [item.to_dict() for item in candidates]
    except Exception as exc:
        discovery_error = exc
        report["candidates"] = []
        report["candidate_error"] = failure(exc)
    report["scan"] = scan_stats.to_dict()

    report["locator"] = failure(discovery_error) if discovery_error else try_locator(args.zemax_root, args.version, candidates)
    if report["locator"].get("status") == "OK":
        resolved_root = report["locator"]["resolved_root"]
        report["initializer"] = try_initializer(resolved_root, args.version)
    if args.mode in ("standalone", "both"):
        if report["locator"].get("status") == "OK":
            report["standalone"] = try_standalone(report["locator"]["resolved_root"], args.version)
    if args.mode in ("interactive", "both"):
        if report["locator"].get("status") == "OK":
            report["interactive"] = try_interactive(
                report["locator"]["resolved_root"], args.version, args.instance
            )
    report["recommendations"] = recommendations(report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    required = ["locator", "initializer"]
    if args.mode in ("standalone", "both"):
        required.append("standalone")
    if args.mode in ("interactive", "both"):
        required.append("interactive")
    return 0 if all(report.get(key, {}).get("status") == "OK" for key in required) else 2


if __name__ == "__main__":
    raise SystemExit(main())
