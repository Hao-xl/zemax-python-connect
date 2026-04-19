---
name: zemax-python-connect
description: Use when users mention Zemax OpticStudio Python connection, ZOS-API setup, Standalone Application, Interactive Extension, CreateNewApplication, ConnectAsExtension, ZOSAPI_NetHelper.dll, NotAuthorized, PrimarySystem None, Instance Number, or --replace-current while trying to connect Python to Zemax.
---

# Zemax Python Connect

## Scope
This skill only establishes and verifies Python connection to Zemax OpticStudio through ZOS-API.

Use this skill before optical operations when connection status is uncertain. After connection is proven, use `zemax-python` for model operations, merit functions, optimization, analyses, and tolerancing.

Do not use this skill to design optical systems or define optimization strategy.

## Choose Connection Mode

| User intent | Mode | API |
|---|---|---|
| Batch automation, create/open/save files without watching GUI | Standalone Application | `CreateNewApplication()` |
| User wants to see live edits in an already open OpticStudio GUI | Interactive Extension | `ConnectAsExtension(instance)` |
| User says Python should modify the visible LDE/Layout in real time | Interactive Extension | `ConnectAsExtension(instance)` |
| User only needs to generate output `.zos`/`.zmx` files | Standalone Application | `CreateNewApplication()` |

## First Rule: Locate the User's Own Zemax Installation

Never assume the user's path matches another computer. First locate `ZOSAPI_NetHelper.dll` and the OpticStudio install/data root.

Use bundled script:

```powershell
python scripts\zosapi_locator.py --list-candidates
```

If automatic discovery fails, ask the user for the OpticStudio install directory or pass it explicitly:

```powershell
python scripts\zosapi_locator.py --zemax-root "C:\Path\To\Ansys Zemax OpticStudio"
```

Valid roots may be:

- OpticStudio install directory containing `ZOSAPI_NetHelper.dll`, `ZOSAPI.dll`, and `ZOSAPI_Interfaces.dll`.
- Zemax data directory containing `ZOS-API\Libraries\ZOSAPI_NetHelper.dll`.

## Standalone Application Workflow

Use this when the user wants automation, batch work, or file generation.

Verify first:

```powershell
python scripts\standalone_ping.py --zemax-root "<user zemax root>"
```

Success indicators:

```text
MODE=StandaloneApplication
STATUS=OK
IS_VALID_LICENSE=True
HAS_PRIMARY_SYSTEM=True
```

Minimal usage pattern:

```python
from zemax_connection import ZemaxStandaloneAPI

with ZemaxStandaloneAPI(zemax_root=zemax_root) as z:
    system = z.system
```

Standalone mode owns the OpticStudio instance it creates; closing with `CloseApplication()` is appropriate and handled by the wrapper.

## Interactive Extension Workflow

Use this when the user wants Python to operate on the visible OpticStudio GUI session.

Before running Python, tell the user to open OpticStudio and click the independent Interactive Extension button in the `ZOS-API.NET` area:

```text
编程 > 交互扩展
Programming > Interactive Extension
```

The user must see the waiting dialog with `Instance Number` and `Status: waiting for connection`. Ask them to compare with screenshots in `picture/`, especially:

- `picture/interactive-extension-button.png`
- `picture/interactive-extension-waiting-dialog.png`

Do not tell the user to use only:

```text
编程 > Python > 交互扩展
Programming > Python > Interactive Extension
```

That entry creates a `PythonZOSConnectionxx.py` template and opens a folder. It does not by itself start the waiting Interactive Extension session.

Verify connection:

```powershell
python scripts\interactive_ping.py --zemax-root "<user zemax root>" --instance 0
```

If the dialog shows a different instance number, pass it:

```powershell
python scripts\interactive_ping.py --zemax-root "<user zemax root>" --instance 1
```

Success indicators:

```text
MODE=InteractiveExtension
STATUS=OK
APP_MODE=Plugin
IS_VALID_LICENSE=True
HAS_PRIMARY_SYSTEM=True
```

Minimal usage pattern:

```python
from zemax_connection import ZemaxInteractiveAPI

with ZemaxInteractiveAPI(zemax_root=zemax_root, instance=instance) as z:
    system = z.system
```

Interactive mode connects to a GUI session owned by OpticStudio; do not call `CloseApplication()`.

## Safe Visible Edit Test

After `interactive_ping.py` succeeds, use the safe comment test if the user wants visible proof:

```powershell
python scripts\interactive_comment_test.py --zemax-root "<user zemax root>" --instance 0
```

Expected visible result: Lens Data Editor surface comments change. This verifies live GUI control without replacing the optical system.

## `--replace-current`

If a script reports that it refuses to replace the visible OpticStudio system, tell the user:

Save the original lens, click OpticStudio `ZOS-API.NET` area `交互扩展 / Interactive Extension` again, keep the waiting dialog open, then run the new program with `--replace-current` appended.

## Common Diagnostics

| Symptom | Likely cause | Next action |
|---|---|---|
| `ZOSAPI_NetHelper.dll` not found | Wrong root or nonstandard install location | Run `zosapi_locator.py --list-candidates`; pass `--zemax-root` |
| `ConnectAsExtension returned None` | Interactive Extension waiting dialog is not open | Open independent `交互扩展 / Interactive Extension` button in `ZOS-API.NET` area |
| `NotAuthorized` in interactive mode | Usually wrong startup path or stale dialog | Close/reopen the independent Interactive Extension dialog, then rerun |
| `APP_MODE=Server` for interactive attempt | Connected object is not the plugin session | Restart the independent Interactive Extension dialog |
| Standalone returns `LICENSE=Unknown`, `Timeout`, or `NotAuthorized` after repeated attempts | Stale hidden OpticStudio process or license state may be blocking API startup | Close hidden OpticStudio processes or restart OpticStudio, then rerun `standalone_ping.py`; if it persists, check license/API support |
| `This application was not launched by Optic Studio` | Wrong API method for this use case | Use `ConnectAsExtension(instance)`, not `ConnectToApplication()` |
| `PrimarySystem is None` | No valid visible/open system | Open or create a lens in OpticStudio before connecting |
| Multiple GUI instances | Wrong instance number | Use the dialog's `Instance Number` with `--instance N` |

For full diagnostics:

```powershell
python scripts\connection_diagnose.py --mode both --zemax-root "<user zemax root>" --instance 0
```

## Reporting Contract

When helping a user connect, report at minimum:

- selected mode: `StandaloneApplication` or `InteractiveExtension`
- resolved Zemax root
- `ZOSAPI_NetHelper.dll` path
- license status
- app mode: `Server` or `Plugin`
- whether `PrimarySystem` exists
- exact next command for the user to run
