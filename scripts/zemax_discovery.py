from __future__ import annotations

import ctypes
import errno
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - Windows-only discovery.
    winreg = None  # type: ignore


SUPPORTED_VERSIONS = (2021, 2022, 2023, 2024, 2025)
_VERSION_RE = re.compile(r"(?<!\d)(20(?:21|22|23|24|25))(?!\d)")
_ANSYS_VERSION_RE = re.compile(r"(?i)(?:^|[\\/])v(21|22|23|24|25)\d(?:[\\/]|$)")
_DLL_NAMES = ("ZOSAPI_NetHelper.dll", "ZOSAPI.dll", "ZOSAPI_Interfaces.dll")
BOUNDED_SEARCH_MAX_DEPTH = 5
EXHAUSTIVE_SEARCH_ESTIMATE = "通常约 2–15 分钟；文件很多或磁盘较慢时可能超过 30 分钟"


class ZemaxDiscoveryError(RuntimeError):
    pass


class MultipleZemaxInstallationsError(ZemaxDiscoveryError):
    pass


class ExhaustiveSearchConfirmationRequired(ZemaxDiscoveryError):
    pass


@dataclass
class DiscoveryCandidate:
    path: str
    source: str
    root_kind: str
    version: int | None = None
    has_net_helper: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanStats:
    bounded_scan_performed: bool = False
    exhaustive_scan_performed: bool = False
    scanned_directories: int = 0
    permission_denied_directories: int = 0
    other_scan_errors: int = 0
    elapsed_seconds: float = 0.0
    bounded_max_depth: int = BOUNDED_SEARCH_MAX_DEPTH
    exhaustive_time_estimate: str = EXHAUSTIVE_SEARCH_ESTIMATE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["elapsed_seconds"] = round(self.elapsed_seconds, 3)
        return data


@dataclass
class ZOSAPILocation:
    requested_root: str | None
    resolved_root: str
    root_kind: str
    net_helper_path: str
    initializer_path: str
    source: str = "unknown"
    requested_version: int | None = None
    detected_version: int | None = None
    zemax_dir: str | None = None
    zosapi_path: str | None = None
    interfaces_path: str | None = None
    opticstudio_exe: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def norm_path(path: str | Path) -> str:
    return os.path.normpath(os.path.expandvars(os.path.expanduser(str(path))))


def path_exists(path: str | Path) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def detect_version(path: str | Path) -> int | None:
    text = str(path)
    matches = _VERSION_RE.findall(text)
    if matches:
        return int(matches[-1])
    ansys_match = _ANSYS_VERSION_RE.search(text)
    return 2000 + int(ansys_match.group(1)) if ansys_match else None


def _dedupe(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path, source in items:
        normalized = norm_path(path)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        output.append((normalized, source))
    return output


def _read_registry_value(root: int, subkey: str, value_name: str, access: int | None = None) -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(root, subkey, 0, access or winreg.KEY_READ) as key:
            value = winreg.QueryValueEx(key, value_name)[0]
    except OSError:
        return None
    return str(value) if value else None


def _registry_views() -> tuple[int, ...]:
    if winreg is None:
        return ()
    views = [winreg.KEY_READ]
    for name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        value = getattr(winreg, name, 0)
        if value:
            views.append(winreg.KEY_READ | value)
    return tuple(dict.fromkeys(views))


def _enum_registry_subkeys(root: int, subkey: str, access: int) -> list[str]:
    if winreg is None:
        return []
    try:
        with winreg.OpenKey(root, subkey, 0, access) as parent:
            count = winreg.QueryInfoKey(parent)[0]
            return [winreg.EnumKey(parent, index) for index in range(count)]
    except OSError:
        return []


def _path_from_executable_value(value: str) -> str:
    cleaned = os.path.expandvars(value).strip()
    if cleaned.startswith('"'):
        end = cleaned.find('"', 1)
        executable = cleaned[1:end] if end > 1 else cleaned.strip('"')
    else:
        executable = cleaned.split(",", 1)[0].strip()
    path = Path(executable)
    return str(path.parent) if path.suffix.casefold() == ".exe" else str(path)


def _running_opticstudio_candidates() -> list[tuple[str, str]]:
    """Read the executable path of running OpticStudio processes without third-party packages."""
    if os.name != "nt":
        return []
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot_fn = kernel32.CreateToolhelp32Snapshot
    snapshot_fn.argtypes = (wintypes.DWORD, wintypes.DWORD)
    snapshot_fn.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    process_next.restype = wintypes.BOOL
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    query_path = kernel32.QueryFullProcessImageNameW
    query_path.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    query_path.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    snapshot = snapshot_fn(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    output: list[tuple[str, str]] = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        has_entry = bool(process_first(snapshot, ctypes.byref(entry)))
        while has_entry:
            if entry.szExeFile.casefold() == "opticstudio.exe":
                handle = open_process(0x1000, False, entry.th32ProcessID)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if query_path(handle, 0, buffer, ctypes.byref(size)):
                            output.append((str(Path(buffer.value).parent), f"running-process:{entry.th32ProcessID}"))
                    finally:
                        close_handle(handle)
            has_entry = bool(process_next(snapshot, ctypes.byref(entry)))
    finally:
        close_handle(snapshot)
    return output


def _zemax_registry_candidates() -> list[tuple[str, str]]:
    if winreg is None:
        return []
    output: list[tuple[str, str]] = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    subkeys = (r"Software\Zemax", r"Software\WOW6432Node\Zemax")
    names = ("ZemaxRoot", "InstallRoot", "Root", "ZemaxDirectory")
    for root in roots:
        for subkey in subkeys:
            for name in names:
                value = _read_registry_value(root, subkey, name)
                if value:
                    output.append((value, f"registry:{subkey}:{name}"))
    return output


def _uninstall_registry_candidates() -> list[tuple[str, str]]:
    if winreg is None:
        return []
    output: list[tuple[str, str]] = []
    roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    subkeys = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for root in roots:
        for subkey in subkeys:
            for access in _registry_views():
                for name in _enum_registry_subkeys(root, subkey, access):
                    child = f"{subkey}\\{name}"
                    display_name = _read_registry_value(root, child, "DisplayName", access) or ""
                    if "opticstudio" not in display_name.casefold() and "zemax" not in display_name.casefold():
                        continue
                    install_location = _read_registry_value(root, child, "InstallLocation", access)
                    if install_location:
                        output.append((install_location, f"uninstall:{display_name}"))
                        continue
                    display_icon = _read_registry_value(root, child, "DisplayIcon", access)
                    if display_icon:
                        output.append((_path_from_executable_value(display_icon), f"uninstall-icon:{display_name}"))
    return output


def _app_paths_registry_candidates() -> list[tuple[str, str]]:
    if winreg is None:
        return []
    output: list[tuple[str, str]] = []
    subkey = r"Software\Microsoft\Windows\CurrentVersion\App Paths\OpticStudio.exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in _registry_views():
            executable = _read_registry_value(root, subkey, "", access)
            if executable:
                output.append((_path_from_executable_value(executable), "registry-app-paths:OpticStudio.exe"))
            search_path = _read_registry_value(root, subkey, "Path", access)
            if search_path:
                output.append((search_path, "registry-app-paths:Path"))
    return output


def _windows_installer_candidates() -> list[tuple[str, str]]:
    """Inspect Windows Installer product metadata not always mirrored in Uninstall."""
    if winreg is None:
        return []
    output: list[tuple[str, str]] = []
    classes_key = r"Software\Classes\Installer\Products"
    for access in _registry_views():
        for product in _enum_registry_subkeys(winreg.HKEY_LOCAL_MACHINE, classes_key, access):
            child = f"{classes_key}\\{product}"
            product_name = _read_registry_value(winreg.HKEY_LOCAL_MACHINE, child, "ProductName", access) or ""
            if "opticstudio" not in product_name.casefold() and "zemax" not in product_name.casefold():
                continue
            location = _read_registry_value(winreg.HKEY_LOCAL_MACHINE, child, "InstallLocation", access)
            icon = _read_registry_value(winreg.HKEY_LOCAL_MACHINE, child, "ProductIcon", access)
            if location:
                output.append((location, f"windows-installer:{product_name}"))
            elif icon:
                output.append((_path_from_executable_value(icon), f"windows-installer-icon:{product_name}"))

    userdata = r"Software\Microsoft\Windows\CurrentVersion\Installer\UserData"
    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    for sid in _enum_registry_subkeys(winreg.HKEY_LOCAL_MACHINE, userdata, access):
        products_key = f"{userdata}\\{sid}\\Products"
        for product in _enum_registry_subkeys(winreg.HKEY_LOCAL_MACHINE, products_key, access):
            properties = f"{products_key}\\{product}\\InstallProperties"
            display_name = _read_registry_value(winreg.HKEY_LOCAL_MACHINE, properties, "DisplayName", access) or ""
            if "opticstudio" not in display_name.casefold() and "zemax" not in display_name.casefold():
                continue
            location = _read_registry_value(winreg.HKEY_LOCAL_MACHINE, properties, "InstallLocation", access)
            icon = _read_registry_value(winreg.HKEY_LOCAL_MACHINE, properties, "DisplayIcon", access)
            if location:
                output.append((location, f"installer-userdata:{display_name}"))
            elif icon:
                output.append((_path_from_executable_value(icon), f"installer-userdata-icon:{display_name}"))
    return output


def _path_environment_candidates() -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for item in os.environ.get("PATH", "").split(os.pathsep):
        if item and path_exists(Path(item) / "OpticStudio.exe"):
            output.append((item, "environment:PATH"))
    return output


def _documents_candidates() -> list[tuple[str, str]]:
    output = [(str(Path.home() / "Documents" / "Zemax"), "home-documents")]
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(key)
        if value:
            output.append((str(Path(value) / "Documents" / "Zemax"), f"environment:{key}"))
    if winreg is not None:
        personal = _read_registry_value(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            "Personal",
        )
        if personal:
            output.append((str(Path(norm_path(personal)) / "Zemax"), "known-folder:Documents"))
    return output


def fixed_drives() -> list[str]:
    if os.name != "nt":
        return []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        return ["C:\\"]
    drives: list[str] = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        drive = f"{chr(65 + index)}:\\"
        try:
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
        except Exception:
            drive_type = 0
        if drive_type == 3:  # DRIVE_FIXED
            drives.append(drive)
    return drives


def _glob_candidates(base: Path, patterns: Iterable[str]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    if not path_exists(base):
        return output
    for pattern in patterns:
        try:
            output.extend((str(path), "common-install-directory") for path in base.glob(pattern))
        except OSError:
            continue
    return output


def _common_install_candidates() -> list[tuple[str, str]]:
    bases = [
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    for drive in fixed_drives():
        bases.extend(
            (
                str(Path(drive) / "Program Files"),
                str(Path(drive) / "Program Files (x86)"),
                str(Path(drive) / "ANSYS Inc"),
            )
        )
    patterns = (
        "Ansys Zemax OpticStudio*",
        "ANSYS Zemax OpticStudio*",
        "Zemax OpticStudio*",
        "OpticStudio*",
        "v*/Ansys Zemax OpticStudio*",
        "v*/Zemax OpticStudio*",
        "v*/OpticStudio*",
    )
    output: list[tuple[str, str]] = []
    for base in {norm_path(item) for item in bases if item}:
        output.extend(_glob_candidates(Path(base), patterns))
    return output


def _root_from_net_helper(path: Path) -> Path:
    parts = [part.casefold() for part in path.parts]
    if len(parts) >= 3 and parts[-3:] == ["zos-api", "libraries", "zosapi_nethelper.dll"]:
        return path.parents[2]
    return path.parent


def _disk_search_candidates(stats: ScanStats, max_depth: int | None) -> list[tuple[str, str]]:
    """Search fixed disks, recording directories that could not be inspected."""
    output: list[tuple[str, str]] = []
    skip = {
        "$recycle.bin",
        "system volume information",
        "windows",
        "windowsapps",
        "node_modules",
        ".git",
    }
    started = time.monotonic()
    if max_depth is None:
        stats.exhaustive_scan_performed = True
        source = "exhaustive-search"
    else:
        stats.bounded_scan_performed = True
        source = "bounded-search"

    def onerror(exc: OSError) -> None:
        if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM):
            stats.permission_denied_directories += 1
        else:
            stats.other_scan_errors += 1

    for drive in fixed_drives():
        root_depth = len(Path(drive).parts)
        for current, dirs, files in os.walk(drive, topdown=True, onerror=onerror):
            stats.scanned_directories += 1
            depth = len(Path(current).parts) - root_depth
            within_depth = max_depth is None or depth < max_depth
            dirs[:] = [name for name in dirs if name.casefold() not in skip and within_depth]
            matching = next((name for name in files if name.casefold() == "zosapi_nethelper.dll"), None)
            if matching:
                output.append((str(_root_from_net_helper(Path(current) / matching)), source))
    stats.elapsed_seconds += time.monotonic() - started
    return output


def root_kind(root: str | Path) -> str:
    root_path = Path(norm_path(root))
    if all(path_exists(root_path / name) for name in _DLL_NAMES):
        return "install"
    if path_exists(root_path / "ZOS-API" / "Libraries" / "ZOSAPI_NetHelper.dll"):
        return "data"
    if path_exists(root_path / "ZOSAPI_NetHelper.dll"):
        return "nethelper-only"
    return "unknown"


def net_helper_candidates(root: str | Path) -> list[str]:
    root_path = Path(root)
    return [
        str(root_path / "ZOSAPI_NetHelper.dll"),
        str(root_path / "ZOS-API" / "Libraries" / "ZOSAPI_NetHelper.dll"),
    ]


def _materialize_candidates(
    raw: Iterable[tuple[str, str]], preferred_version: int | None
) -> list[DiscoveryCandidate]:
    output: list[DiscoveryCandidate] = []
    for path, source in _dedupe(raw):
        version = detect_version(path) or detect_version(source)
        if preferred_version is not None and version is not None and version != preferred_version:
            continue
        output.append(
            DiscoveryCandidate(
                path=path,
                source=source,
                root_kind=root_kind(path),
                version=version,
                has_net_helper=any(path_exists(item) for item in net_helper_candidates(path)),
            )
        )
    return output


def _has_trusted_candidate(candidates: Iterable[DiscoveryCandidate]) -> bool:
    return any(item.has_net_helper and item.root_kind in ("install", "data") for item in candidates)


def discover_candidates(
    explicit_root: str | None = None,
    preferred_version: int | None = None,
    deep_search: bool = False,
    *,
    exhaustive_search: bool = False,
    confirm_long_scan: bool = False,
    scan_stats: ScanStats | None = None,
) -> list[DiscoveryCandidate]:
    if preferred_version is not None and preferred_version not in SUPPORTED_VERSIONS:
        raise ZemaxDiscoveryError(
            f"Unsupported version {preferred_version}; choose {', '.join(map(str, SUPPORTED_VERSIONS))}."
        )
    stats = scan_stats if scan_stats is not None else ScanStats()
    raw: list[tuple[str, str]] = []
    if explicit_root:
        raw.append((explicit_root, "explicit"))
    else:
        raw.extend(_running_opticstudio_candidates())
        for key in ("ZEMAX_ROOT", "OPTICSTUDIO_ROOT", "ZEMAX_DATA_DIR"):
            value = os.environ.get(key)
            if value:
                raw.append((value, f"environment:{key}"))
        raw.extend(_documents_candidates())
        raw.extend(_zemax_registry_candidates())
        raw.extend(_app_paths_registry_candidates())
        raw.extend(_uninstall_registry_candidates())
        raw.extend(_windows_installer_candidates())
        raw.extend(_path_environment_candidates())
        raw.extend(_common_install_candidates())

        fast_candidates = _materialize_candidates(raw, preferred_version)
        if deep_search or not _has_trusted_candidate(fast_candidates):
            raw.extend(_disk_search_candidates(stats, BOUNDED_SEARCH_MAX_DEPTH))
        bounded_candidates = _materialize_candidates(raw, preferred_version)
        if exhaustive_search and not _has_trusted_candidate(bounded_candidates):
            if not confirm_long_scan:
                raise ExhaustiveSearchConfirmationRequired(
                    "EXHAUSTIVE_SCAN_CONFIRMATION_REQUIRED: 有限深度搜索未找到 ZOSAPI_NetHelper.dll。"
                    f"全盘扫描{EXHAUSTIVE_SEARCH_ESTIMATE}。先告知用户并取得明确允许；允许后同时传入 "
                    "--exhaustive-search --confirm-long-scan。"
                )
            raw.extend(_disk_search_candidates(stats, None))

    return _materialize_candidates(raw, preferred_version)


def candidate_roots(
    explicit_root: str | None = None,
    preferred_version: int | None = None,
    deep_search: bool = False,
) -> list[str]:
    return [item.path for item in discover_candidates(explicit_root, preferred_version, deep_search)]


def locate_zosapi(
    explicit_root: str | None = None,
    preferred_version: int | None = None,
    deep_search: bool = False,
    *,
    exhaustive_search: bool = False,
    confirm_long_scan: bool = False,
    scan_stats: ScanStats | None = None,
    candidates: list[DiscoveryCandidate] | None = None,
) -> ZOSAPILocation:
    if candidates is None:
        candidates = discover_candidates(
            explicit_root,
            preferred_version,
            deep_search,
            exhaustive_search=exhaustive_search,
            confirm_long_scan=confirm_long_scan,
            scan_stats=scan_stats,
        )
    valid = [item for item in candidates if item.has_net_helper]
    if not valid:
        checked = "\n".join(f"- {item.path} ({item.source})" for item in candidates[-12:])
        raise ZemaxDiscoveryError(
            "Cannot locate ZOSAPI_NetHelper.dll. Quick Windows sources and the default bounded disk search "
            "did not find a valid root. Pass --zemax-root, or ask permission before an exhaustive scan. Checked:\n"
            + checked
        )

    if explicit_root:
        selected = valid[0]
    else:
        running = [item for item in valid if item.source.startswith("running-process:")]
        data_roots = [item for item in valid if item.root_kind == "data"]
        installs = [item for item in valid if item.root_kind == "install"]
        nethelper_only = [item for item in valid if item.root_kind == "nethelper-only"]
        if len(running) == 1:
            selected = running[0]
        elif len(running) > 1:
            choices = "\n".join(f"- path={item.path} source={item.source}" for item in running)
            raise MultipleZemaxInstallationsError(
                "Multiple running OpticStudio installations were found. Ask the user which running instance to use "
                "and pass --zemax-root.\n" + choices
            )
        elif len(installs) == 1:
            selected = installs[0]
        elif len(installs) > 1:
            choices = "\n".join(
                f"- version={item.version or 'unknown'} path={item.path} source={item.source}" for item in installs
            )
            raise MultipleZemaxInstallationsError(
                "Multiple OpticStudio installations were found. Ask the user to choose 2021, 2022, 2023, "
                "2024, 2025, a directory, or 'I don't know'; then pass --version or --zemax-root.\n" + choices
            )
        elif len(data_roots) == 1:
            selected = data_roots[0]
        elif len(data_roots) > 1:
            choices = "\n".join(f"- data-root path={item.path} source={item.source}" for item in data_roots)
            raise MultipleZemaxInstallationsError(
                "Multiple Zemax data roots were found and no complete install directory was discovered. "
                "Ask the user to choose a directory; then pass --zemax-root.\n" + choices
            )
        elif len(nethelper_only) == 1:
            selected = nethelper_only[0]
        else:
            choices = "\n".join(f"- NetHelper-only path={item.path} source={item.source}" for item in nethelper_only)
            raise MultipleZemaxInstallationsError(
                "Only multiple isolated NetHelper copies were found; selecting one could load the wrong product or "
                "extension. Ask for the OpticStudio/Zemax directory or run a deeper manual search.\n" + choices
            )

    net_helper = next((item for item in net_helper_candidates(selected.path) if path_exists(item)), None)
    if net_helper is None:
        raise ZemaxDiscoveryError(f"ZOSAPI_NetHelper.dll disappeared during discovery: {selected.path}")
    initializer_path = selected.path if selected.root_kind == "install" else ""
    notes = [
        "Resolved a complete install directory and will initialize it explicitly."
        if initializer_path
        else "Resolved a data/NetHelper root; Initialize() must resolve and validate the actual install directory."
    ]
    return ZOSAPILocation(
        requested_root=explicit_root,
        requested_version=preferred_version,
        resolved_root=selected.path,
        root_kind=selected.root_kind,
        source=selected.source,
        detected_version=selected.version,
        net_helper_path=norm_path(net_helper),
        initializer_path=initializer_path,
        notes=notes,
    )
