from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - ZOS-API is Windows-only, but imports should stay safe.
    winreg = None  # type: ignore


class ZemaxConnectionError(RuntimeError):
    """Raised when OpticStudio/ZOS-API cannot be located or connected."""


@dataclass
class ZOSAPILocation:
    requested_root: str | None
    resolved_root: str
    root_kind: str
    net_helper_path: str
    initializer_path: str
    zemax_dir: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(path: str | Path) -> str:
    return os.path.normpath(str(path))


def _exists(path: str | Path) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def _read_registry_value(root: int, subkey: str, value_name: str) -> str | None:
    if winreg is None:
        return None
    try:
        key = winreg.OpenKey(winreg.ConnectRegistry(None, root), subkey, 0, winreg.KEY_READ)
    except OSError:
        return None
    try:
        return str(winreg.QueryValueEx(key, value_name)[0])
    except OSError:
        return None
    finally:
        try:
            winreg.CloseKey(key)
        except OSError:
            pass


def _registry_candidates() -> list[str]:
    if winreg is None:
        return []
    out: list[str] = []
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    subkeys = [
        r"Software\Zemax",
        r"Software\WOW6432Node\Zemax",
    ]
    names = ["ZemaxRoot", "InstallRoot", "Root", "ZemaxDirectory"]
    for root in roots:
        for subkey in subkeys:
            for name in names:
                value = _read_registry_value(root, subkey, name)
                if value:
                    out.append(value)
    return out


def _common_candidates() -> list[str]:
    candidates: list[str] = []
    home = Path.home()
    candidates.append(str(home / "Documents" / "Zemax"))

    program_roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    patterns = [
        "Ansys Zemax OpticStudio*",
        "ANSYS Zemax OpticStudio*",
        "Zemax OpticStudio*",
        "OpticStudio*",
    ]
    for base in program_roots:
        if not base or not _exists(base):
            continue
        for pattern in patterns:
            try:
                candidates.extend(str(path) for path in Path(base).glob(pattern))
            except OSError:
                pass

    ansys_root = Path(r"C:\Program Files\ANSYS Inc")
    if ansys_root.exists():
        try:
            candidates.extend(str(path) for path in ansys_root.glob(r"v*\Zemax OpticStudio*"))
            candidates.extend(str(path) for path in ansys_root.glob(r"v*\OpticStudio*"))
        except OSError:
            pass
    return candidates


def candidate_roots(explicit_root: str | None = None) -> list[str]:
    """Return likely OpticStudio install/data roots without verifying them."""
    raw: list[str] = []
    if explicit_root:
        raw.append(explicit_root)
    for key in ("ZEMAX_ROOT", "OPTICSTUDIO_ROOT", "ZEMAX_DATA_DIR"):
        value = os.environ.get(key)
        if value:
            raw.append(value)
    raw.extend(_registry_candidates())
    raw.extend(_common_candidates())

    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        normalized = _norm(item)
        if normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        out.append(normalized)
    return out


def root_kind(root: str | Path) -> str:
    root = _norm(root)
    if (
        _exists(Path(root) / "ZOSAPI_NetHelper.dll")
        and _exists(Path(root) / "ZOSAPI.dll")
        and _exists(Path(root) / "ZOSAPI_Interfaces.dll")
    ):
        return "install"
    if _exists(Path(root) / "ZOS-API" / "Libraries" / "ZOSAPI_NetHelper.dll"):
        return "data"
    if _exists(Path(root) / "ZOSAPI_NetHelper.dll"):
        return "nethelper-only"
    return "unknown"


def net_helper_candidates(root: str | Path) -> list[str]:
    root = Path(root)
    return [
        str(root / "ZOSAPI_NetHelper.dll"),
        str(root / "ZOS-API" / "Libraries" / "ZOSAPI_NetHelper.dll"),
    ]


def locate_zosapi(explicit_root: str | None = None) -> ZOSAPILocation:
    """Locate ZOSAPI_NetHelper.dll and decide how ZOSAPI_Initializer should be called."""
    errors: list[str] = []
    for root in candidate_roots(explicit_root):
        kind = root_kind(root)
        for net_helper in net_helper_candidates(root):
            if not _exists(net_helper):
                continue
            initializer_path = root if kind == "install" else ""
            notes: list[str] = []
            if kind == "data":
                notes.append("Resolved a Zemax data directory; Initialize() will discover the OpticStudio install path.")
            elif kind == "install":
                notes.append("Resolved an OpticStudio install directory; Initialize(root) will use this explicit path.")
            else:
                notes.append("Resolved ZOSAPI_NetHelper.dll, but root is not a full install/data directory.")
            return ZOSAPILocation(
                requested_root=explicit_root,
                resolved_root=root,
                root_kind=kind,
                net_helper_path=_norm(net_helper),
                initializer_path=initializer_path,
                notes=notes,
            )
        errors.append(f"No ZOSAPI_NetHelper.dll under {root}")

    detail = "\n".join(errors[-8:])
    raise ZemaxConnectionError(
        "Cannot locate ZOSAPI_NetHelper.dll. Pass --zemax-root pointing to the OpticStudio install "
        "directory or the Zemax data directory. Checked candidates:\n" + detail
    )


def initialize_zosapi(explicit_root: str | None = None) -> tuple[Any, ZOSAPILocation]:
    """Load pythonnet CLR references and import ZOSAPI."""
    location = locate_zosapi(explicit_root)

    try:
        import clr  # type: ignore
    except ImportError as exc:
        raise ZemaxConnectionError("pythonnet is required. Install with: pip install pythonnet") from exc

    clr.AddReference(location.net_helper_path)
    import ZOSAPI_NetHelper  # type: ignore

    if location.initializer_path:
        initialized = ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize(location.initializer_path)
    else:
        initialized = ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize()

    if not initialized:
        raise ZemaxConnectionError("ZOSAPI_Initializer.Initialize() failed.")

    zemax_dir = str(ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory())
    location.zemax_dir = zemax_dir
    clr.AddReference(str(Path(zemax_dir) / "ZOSAPI.dll"))
    clr.AddReference(str(Path(zemax_dir) / "ZOSAPI_Interfaces.dll"))

    import ZOSAPI  # type: ignore

    return ZOSAPI, location


def safe_getattr(obj: Any, name: str, default: str = "Unknown") -> Any:
    try:
        return getattr(obj, name)
    except Exception as exc:
        return f"{default}: {exc}"


def has_primary_system(app: Any) -> bool:
    try:
        return app.PrimarySystem is not None
    except Exception:
        return False


class ZemaxStandaloneAPI:
    """Create and control an independent OpticStudio application instance."""

    def __init__(self, zemax_root: str | None = None, close_on_exit: bool = True, require_valid_license: bool = True) -> None:
        self.requested_root = zemax_root
        self.close_on_exit = bool(close_on_exit)
        self.require_valid_license = bool(require_valid_license)
        self.zosapi: Any | None = None
        self.location: ZOSAPILocation | None = None
        self.connection: Any | None = None
        self.app: Any | None = None
        self.system: Any | None = None

    def connect(self) -> "ZemaxStandaloneAPI":
        self.zosapi, self.location = initialize_zosapi(self.requested_root)
        self.connection = self.zosapi.ZOSAPI_Connection()
        self.app = self.connection.CreateNewApplication()
        if self.app is None:
            raise ZemaxConnectionError("CreateNewApplication() returned None.")
        if self.require_valid_license and not bool(safe_getattr(self.app, "IsValidLicenseForAPI", False)):
            raise ZemaxConnectionError(f"License does not support ZOS-API: {safe_getattr(self.app, 'LicenseStatus')}")
        self.system = self.app.PrimarySystem
        if self.require_valid_license and self.system is None:
            raise ZemaxConnectionError("PrimarySystem is None.")
        return self

    def close(self) -> None:
        try:
            if self.app is not None and self.close_on_exit:
                self.app.CloseApplication()
        finally:
            self.system = None
            self.app = None
            self.connection = None
            self.zosapi = None

    def diagnostic_info(self) -> dict[str, Any]:
        app = self.app
        info = self.location.to_dict() if self.location else {}
        info.update({"connected": app is not None})
        if app is not None:
            info.update({
                "is_valid_license": bool(safe_getattr(app, "IsValidLicenseForAPI", False)),
                "license_status": str(safe_getattr(app, "LicenseStatus")),
                "app_mode": str(safe_getattr(app, "Mode")),
                "serial_code": str(safe_getattr(app, "SerialCode")),
                "zemax_data_dir": str(safe_getattr(app, "ZemaxDataDir")),
                "samples_dir": str(safe_getattr(app, "SamplesDir")),
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

    def __init__(self, zemax_root: str | None = None, instance: int = 0, require_valid_license: bool = True) -> None:
        self.requested_root = zemax_root
        self.instance = int(instance)
        self.require_valid_license = bool(require_valid_license)
        self.zosapi: Any | None = None
        self.location: ZOSAPILocation | None = None
        self.connection: Any | None = None
        self.app: Any | None = None
        self.system: Any | None = None

    def connect(self) -> "ZemaxInteractiveAPI":
        self.zosapi, self.location = initialize_zosapi(self.requested_root)
        self.connection = self.zosapi.ZOSAPI_Connection()
        self.app = self.connection.ConnectAsExtension(self.instance)
        if self.app is None:
            raise ZemaxConnectionError(
                "ConnectAsExtension returned None. In OpticStudio, click the independent "
                "Programming > Interactive Extension button in the ZOS-API.NET area and keep the waiting dialog open."
            )
        if self.require_valid_license and not bool(safe_getattr(self.app, "IsValidLicenseForAPI", False)):
            raise ZemaxConnectionError(f"License does not support ZOS-API: {safe_getattr(self.app, 'LicenseStatus')}")
        self.system = self.app.PrimarySystem
        if self.require_valid_license and self.system is None:
            raise ZemaxConnectionError("PrimarySystem is None. Open or create a lens file in the visible OpticStudio session.")
        return self

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
        info.update({"connected": app is not None, "instance": self.instance})
        if app is not None:
            info.update({
                "is_valid_license": bool(safe_getattr(app, "IsValidLicenseForAPI", False)),
                "license_status": str(safe_getattr(app, "LicenseStatus")),
                "app_mode": str(safe_getattr(app, "Mode")),
                "serial_code": str(safe_getattr(app, "SerialCode")),
                "zemax_data_dir": str(safe_getattr(app, "ZemaxDataDir")),
                "samples_dir": str(safe_getattr(app, "SamplesDir")),
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
