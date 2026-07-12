from __future__ import annotations

import json
from pathlib import Path
from typing import Any


from zemax_discovery import (  # noqa: E402
    EXHAUSTIVE_SEARCH_ESTIMATE,
    ExhaustiveSearchConfirmationRequired,
    MultipleZemaxInstallationsError,
    ScanStats,
    SUPPORTED_VERSIONS,
    ZOSAPILocation,
    ZemaxDiscoveryError,
    candidate_roots,
    detect_version,
    discover_candidates,
    locate_zosapi,
    norm_path,
    root_kind,
)

# Preserve the public exception name while making discovery and connection failures catchable together.
ZemaxConnectionError = ZemaxDiscoveryError


def initialize_zosapi(
    explicit_root: str | None = None,
    preferred_version: int | None = None,
    deep_search: bool = False,
    *,
    exhaustive_search: bool = False,
    confirm_long_scan: bool = False,
    scan_stats: ScanStats | None = None,
    candidates: list[Any] | None = None,
) -> tuple[Any, ZOSAPILocation]:
    """Locate NetHelper first, then initialize and validate the actual install directory."""
    location = locate_zosapi(
        explicit_root,
        preferred_version,
        deep_search,
        exhaustive_search=exhaustive_search,
        confirm_long_scan=confirm_long_scan,
        scan_stats=scan_stats,
        candidates=candidates,
    )

    try:
        import clr  # type: ignore
    except ImportError as exc:
        raise ZemaxConnectionError("pythonnet is required. Install with: python -m pip install pythonnet") from exc

    try:
        clr.AddReference(location.net_helper_path)
        import ZOSAPI_NetHelper  # type: ignore

        if location.initializer_path:
            initialized = ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize(location.initializer_path)
        else:
            initialized = ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize()
    except Exception as exc:
        raise ZemaxConnectionError(f"Failed to load or initialize {location.net_helper_path}: {exc}") from exc

    if not initialized:
        raise ZemaxConnectionError("ZOSAPI_Initializer.Initialize() failed.")

    zemax_dir_value = ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory()
    if not zemax_dir_value:
        raise ZemaxConnectionError("ZOSAPI initialized, but GetZemaxDirectory() returned an empty path.")
    zemax_dir = Path(norm_path(str(zemax_dir_value)))
    zosapi_path = zemax_dir / "ZOSAPI.dll"
    interfaces_path = zemax_dir / "ZOSAPI_Interfaces.dll"
    missing = [str(path) for path in (zosapi_path, interfaces_path) if not path.exists()]
    if missing:
        raise ZemaxConnectionError(
            "Resolved the OpticStudio install directory, but required DLLs are missing: " + ", ".join(missing)
        )

    location.zemax_dir = str(zemax_dir)
    location.zosapi_path = str(zosapi_path)
    location.interfaces_path = str(interfaces_path)
    opticstudio_exe = zemax_dir / "OpticStudio.exe"
    location.opticstudio_exe = str(opticstudio_exe) if opticstudio_exe.exists() else None
    actual_version = detect_version(zemax_dir)
    if actual_version is not None:
        location.detected_version = actual_version
    if preferred_version is not None and actual_version is not None and actual_version != preferred_version:
        raise ZemaxConnectionError(
            f"Requested OpticStudio {preferred_version}, but initializer resolved {actual_version}: {zemax_dir}"
        )

    clr.AddReference(str(zosapi_path))
    clr.AddReference(str(interfaces_path))

    import ZOSAPI  # type: ignore

    return ZOSAPI, location


def safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """Return the caller's default on getter failure; never return a truthy error string."""
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _license_is_valid(app: Any) -> bool:
    return bool(safe_getattr(app, "IsValidLicenseForAPI", False))


def _app_mode(app: Any) -> str:
    return str(safe_getattr(app, "Mode", "Unknown"))


def classify_connection_error(exc: BaseException) -> dict[str, str]:
    message = str(exc)
    lowered = message.casefold()
    if isinstance(exc, ExhaustiveSearchConfirmationRequired) or "exhaustive_scan_confirmation_required" in lowered:
        return {
            "error_code": "EXHAUSTIVE_SCAN_CONFIRMATION_REQUIRED",
            "action": (
                f"Tell the user the scan estimate ({EXHAUSTIVE_SEARCH_ESTIMATE}) and ask permission. "
                "Only after explicit approval, pass --exhaustive-search --confirm-long-scan."
            ),
        }
    if ("ipc" in lowered or "remotingexception" in lowered) and (
        "拒绝访问" in message or "access denied" in lowered or "access is denied" in lowered
    ):
        return {
            "error_code": "IPC_ACCESS_DENIED",
            "action": "Rerun the same Zemax Python command outside the agent sandbox with user approval.",
        }
    if isinstance(exc, MultipleZemaxInstallationsError):
        return {"error_code": "MULTIPLE_INSTALLATIONS", "action": "Pass --version or --zemax-root."}
    if "zosapi_nethelper.dll" in lowered:
        return {
            "error_code": "NETHELPER_NOT_FOUND",
            "action": (
                f"The bounded scan has already run. Tell the user an exhaustive scan is estimated at "
                f"{EXHAUSTIVE_SEARCH_ESTIMATE}, ask permission, then rerun with "
                "--exhaustive-search --confirm-long-scan."
            ),
        }
    if "expected app_mode=plugin" in lowered:
        return {
            "error_code": "INTERACTIVE_MODE_MISMATCH",
            "action": (
                "In an agent environment, first rerun outside the sandbox. If it still returns Server, "
                "reopen the independent Interactive Extension dialog and verify its instance number."
            ),
        }
    if "connectasextension" in lowered:
        return {
            "error_code": "INTERACTIVE_SESSION_NOT_READY",
            "action": "Open the independent Interactive Extension waiting dialog and use its instance number.",
        }
    return {"error_code": "CONNECTION_FAILED", "action": "Run doctor.py and inspect the diagnostic report."}


def has_primary_system(app: Any) -> bool:
    try:
        return app.PrimarySystem is not None
    except Exception:
        return False


class ZemaxStandaloneAPI:
    """Create and control an independent OpticStudio application instance."""

    def __init__(
        self,
        zemax_root: str | None = None,
        close_on_exit: bool = True,
        require_valid_license: bool = True,
        preferred_version: int | None = None,
        deep_search: bool = False,
    ) -> None:
        self.requested_root = zemax_root
        self.close_on_exit = bool(close_on_exit)
        self.require_valid_license = bool(require_valid_license)
        self.preferred_version = preferred_version
        self.deep_search = bool(deep_search)
        self.zosapi: Any | None = None
        self.location: ZOSAPILocation | None = None
        self.connection: Any | None = None
        self.app: Any | None = None
        self.system: Any | None = None

    def connect(self) -> "ZemaxStandaloneAPI":
        try:
            self.zosapi, self.location = initialize_zosapi(
                self.requested_root, self.preferred_version, self.deep_search
            )
            self.connection = self.zosapi.ZOSAPI_Connection()
            self.app = self.connection.CreateNewApplication()
            if self.app is None:
                raise ZemaxConnectionError("CreateNewApplication() returned None.")
            if _app_mode(self.app).casefold() != "server":
                raise ZemaxConnectionError(f"Standalone expected APP_MODE=Server, got {_app_mode(self.app)}.")
            if self.require_valid_license and not _license_is_valid(self.app):
                raise ZemaxConnectionError(
                    f"License does not support ZOS-API: {safe_getattr(self.app, 'LicenseStatus', 'Unknown')}"
                )
            self.system = safe_getattr(self.app, "PrimarySystem")
            if self.require_valid_license and self.system is None:
                raise ZemaxConnectionError("PrimarySystem is None.")
            return self
        except Exception:
            # __exit__ is not called when __enter__/connect fails, so clean up here.
            self._close_created_application()
            self._clear_references()
            raise

    def _close_created_application(self) -> None:
        if self.app is not None:
            try:
                self.app.CloseApplication()
            except Exception:
                pass

    def _clear_references(self) -> None:
        self.system = None
        self.app = None
        self.connection = None
        self.zosapi = None

    def close(self) -> None:
        try:
            if self.app is not None and self.close_on_exit:
                self._close_created_application()
        finally:
            self._clear_references()

    def diagnostic_info(self) -> dict[str, Any]:
        app = self.app
        info = self.location.to_dict() if self.location else {}
        mode = _app_mode(app) if app is not None else "Unknown"
        mode_valid = mode.casefold() == "server"
        info.update({"connected": app is not None and mode_valid, "mode_valid": mode_valid})
        if app is not None:
            info.update({
                "is_valid_license": _license_is_valid(app),
                "license_status": str(safe_getattr(app, "LicenseStatus", "Unknown")),
                "app_mode": mode,
                "serial_code": str(safe_getattr(app, "SerialCode", "")),
                "zemax_data_dir": str(safe_getattr(app, "ZemaxDataDir", "Unknown")),
                "samples_dir": str(safe_getattr(app, "SamplesDir", "Unknown")),
                "has_primary_system": self.system is not None,
            })
        return info

    def __enter__(self) -> "ZemaxStandaloneAPI":
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False


class ZemaxInteractiveAPI:
    """Connect to the visible OpticStudio GUI session opened by Interactive Extension."""

    def __init__(
        self,
        zemax_root: str | None = None,
        instance: int = 0,
        require_valid_license: bool = True,
        preferred_version: int | None = None,
        deep_search: bool = False,
    ) -> None:
        self.requested_root = zemax_root
        self.instance = int(instance)
        self.require_valid_license = bool(require_valid_license)
        self.preferred_version = preferred_version
        self.deep_search = bool(deep_search)
        self.zosapi: Any | None = None
        self.location: ZOSAPILocation | None = None
        self.connection: Any | None = None
        self.app: Any | None = None
        self.system: Any | None = None

    def connect(self) -> "ZemaxInteractiveAPI":
        try:
            self.zosapi, self.location = initialize_zosapi(
                self.requested_root, self.preferred_version, self.deep_search
            )
            self.connection = self.zosapi.ZOSAPI_Connection()
            self.app = self.connection.ConnectAsExtension(self.instance)
            if self.app is None:
                raise ZemaxConnectionError(
                    "ConnectAsExtension returned None. In OpticStudio, click the independent "
                    "Programming > Interactive Extension button in the ZOS-API.NET area and keep the waiting dialog open."
                )
            if _app_mode(self.app).casefold() != "plugin":
                license_status = safe_getattr(self.app, "LicenseStatus", "Unknown")
                raise ZemaxConnectionError(
                    f"Interactive Extension expected APP_MODE=Plugin, got {_app_mode(self.app)} "
                    f"with LICENSE={license_status}. "
                    "Reopen the independent waiting dialog and verify its instance number."
                )
            if self.require_valid_license and not _license_is_valid(self.app):
                raise ZemaxConnectionError(
                    f"License does not support ZOS-API: {safe_getattr(self.app, 'LicenseStatus', 'Unknown')}"
                )
            self.system = safe_getattr(self.app, "PrimarySystem")
            if self.require_valid_license and self.system is None:
                raise ZemaxConnectionError(
                    "PrimarySystem is None. Open or create a lens file in the visible OpticStudio session."
                )
            return self
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        # Do not call CloseApplication() in Interactive Extension mode; OpticStudio owns the GUI session.
        try:
            if self.app is not None:
                try:
                    self.app.ProgressPercent = 100
                    self.app.ProgressMessage = "Python interactive extension finished"
                except Exception:
                    pass
        finally:
            self.system = None
            self.app = None
            self.connection = None
            self.zosapi = None

    def diagnostic_info(self) -> dict[str, Any]:
        app = self.app
        info = self.location.to_dict() if self.location else {}
        mode = _app_mode(app) if app is not None else "Unknown"
        mode_valid = mode.casefold() == "plugin"
        info.update({"connected": app is not None and mode_valid, "mode_valid": mode_valid, "instance": self.instance})
        if app is not None:
            info.update({
                "is_valid_license": _license_is_valid(app),
                "license_status": str(safe_getattr(app, "LicenseStatus", "Unknown")),
                "app_mode": mode,
                "serial_code": str(safe_getattr(app, "SerialCode", "")),
                "zemax_data_dir": str(safe_getattr(app, "ZemaxDataDir", "Unknown")),
                "samples_dir": str(safe_getattr(app, "SamplesDir", "Unknown")),
                "has_primary_system": self.system is not None,
            })
        return info

    def __enter__(self) -> "ZemaxInteractiveAPI":
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False


def diagnostic_json(info: dict[str, Any]) -> str:
    return json.dumps(info, ensure_ascii=False, indent=2)
