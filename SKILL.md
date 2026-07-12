---
name: zemax-python-connect
description: 当用户提到 Zemax OpticStudio Python 连接、ZOS-API 配置、独立应用程序、交互扩展、CreateNewApplication、ConnectAsExtension、ZOSAPI_NetHelper.dll、NotAuthorized、PrimarySystem None、Instance Number，或在连接 Python 与 Zemax 时遇到 --replace-current 时使用。
---

# Zemax Python 连接

## 范围

本 skill 只负责建立和验证 Python 与 Zemax OpticStudio 的 ZOS-API 连接。

当连接状态不确定时，先使用本 skill。连接验证完成后，再使用 `zemax-python` 进行模型操作、评价函数、优化、分析和容差等后续工作。

本 skill 不负责光学系统设计，也不负责具体优化策略。

## Agent 执行契约（必须遵守）

1. 不假设 Python、Zemax 数据目录、OpticStudio 安装目录或版本与其他电脑相同。
2. 先运行 `doctor.py --mode locator`。只有已经验证 `ZOSAPI_NetHelper.dll` 存在，才允许初始化 `ZOSAPI_NetHelper`。
3. 初始化后必须读取 `GetZemaxDirectory()`，并再次确认实际安装目录中存在 `ZOSAPI.dll` 和 `ZOSAPI_Interfaces.dll`。
4. 独立模式必须满足 `APP_MODE=Server`；交互模式必须满足 `APP_MODE=Plugin`。仅有非空 `app` 不代表成功。
5. 两种模式都必须确认有效许可证和非空 `PrimarySystem`。
6. 独立模式只关闭 Python 自己创建的实例；即使连接中途失败，也必须清理已创建的应用。
7. 交互模式永远不调用 `CloseApplication()`。
8. 不自动结束用户已有的 OpticStudio 进程。需要结束进程时，先解释原因并取得用户同意。
9. 每次报告解析到的数据根目录、实际安装目录、NetHelper 路径、版本、许可证、应用模式和 `PrimarySystem` 状态。
10. 路径发现必须按顺序执行：Windows 快速来源 → 自动有限深度磁盘搜索 → 经用户明确允许的全盘搜索。禁止跳过授权直接全盘搜索。
11. 全盘搜索前必须告知用户：通常约 2–15 分钟，文件很多或磁盘较慢时可能超过 30 分钟；只有用户明确允许后，才可传入 `--exhaustive-search --confirm-long-scan`。
12. 磁盘搜索必须汇报已扫描目录数、权限拒绝目录数、其他扫描错误数和耗时，不得静默忽略权限失败。

## Codex/Agent 沙箱重要规则

OpticStudio ZOS-API 使用 .NET Remoting IPC。某些 Agent 沙箱允许读取 DLL，却会阻止 IPC 连接。典型错误包括：

```text
System.Runtime.Remoting.RemotingException
连接到 IPC 端口失败: 拒绝访问
Access denied
```

出现 `ERROR_CODE=IPC_ACCESS_DENIED` 时，不要继续猜测 DLL、许可证或实例编号，也不要反复重启 Zemax。应向用户说明原因并请求批准，在 Agent 沙箱外重新运行完全相同的 Zemax Python 命令。沙箱外执行仍必须限制为本 skill 的诊断或连接脚本。

## 连接模式选择

| 用户目标 | 推荐模式 | API |
|---|---|---|
| 批量自动化、创建/打开/保存文件，不需要观察 GUI 实时变化 | 独立应用程序 | `CreateNewApplication()` |
| 用户希望在已经打开的 OpticStudio GUI 中看到实时修改 | 交互扩展 | `ConnectAsExtension(instance)` |
| 用户明确说 Python 应实时修改可见的 LDE 或 Layout | 交互扩展 | `ConnectAsExtension(instance)` |
| 用户只需要生成 `.zos` / `.zmx` 输出文件 | 独立应用程序 | `CreateNewApplication()` |

## 第一原则：先定位，再初始化，再验证实际安装目录

优先运行统一诊断：

```powershell
python scripts\doctor.py --mode locator
```

它会输出 Python 位数、pythonnet 版本、候选目录、已验证的 `ZOSAPI_NetHelper.dll`、初始化器解析出的实际 OpticStudio 安装目录，以及 `ZOSAPI.dll` / `ZOSAPI_Interfaces.dll` 的完整路径。

也可以只运行定位脚本：

```powershell
python scripts\zosapi_locator.py --list-candidates
```

快速发现来源按优先顺序包括：

- 正在运行的 `OpticStudio.exe` 的 `ExecutablePath`；如果路径有效，优先使用它。
- 显式路径和 `ZEMAX_ROOT` / `OPTICSTUDIO_ROOT` / `ZEMAX_DATA_DIR` 环境变量。
- 用户 Documents、OneDrive 和 Windows Documents Known Folder。
- Zemax 注册表、`App Paths\OpticStudio.exe`、32/64 位卸载注册表。
- Windows Installer Products、Installer UserData、`PATH`。
- 所有固定磁盘上的常见 Ansys/Zemax 安装目录。

若这些快速来源没有找到可信的安装目录或 Zemax 数据目录，`doctor.py` 和 `zosapi_locator.py` 会自动执行最大深度为 5 的有限磁盘搜索；无需先询问用户，也无需额外参数。输出中的 `scan` 必须包含：

```text
bounded_scan_performed
scanned_directories
permission_denied_directories
other_scan_errors
elapsed_seconds
```

如果发现 2021–2025 多个版本，必须询问用户，选项至少包含：`2021`、`2022`、`2023`、`2024`、`2025`、`指定目录`、`我不知道`。用户选择版本后运行：

```powershell
python scripts\doctor.py --mode locator --version 2023
```

用户选择“指定目录”时运行：

```powershell
python scripts\doctor.py --mode locator --zemax-root "C:\Path\To\Ansys Zemax OpticStudio"
```

`--deep-search` 保留用于强制执行有限搜索和向后兼容：

```powershell
python scripts\doctor.py --mode locator --deep-search
```

如果快速来源和有限搜索都失败，Agent 必须先告诉用户：

> 下一步是所有固定磁盘的全盘搜索，通常约 2–15 分钟；文件很多或磁盘较慢时可能超过 30 分钟。是否允许本次长时间扫描？

未经明确允许，到此停止，不运行全盘搜索。用户允许后才运行：

```powershell
python scripts\doctor.py --mode locator --exhaustive-search --confirm-long-scan
```

脚本会再次执行快速和有限发现，只有仍未找到可信路径才进入无深度限制的固定磁盘搜索。全盘搜索仍跳过 Windows 系统保护目录、回收站、`.git` 和 `node_modules` 等明确无关或风险较高的目录。当确实需要进入全盘搜索时，仅传 `--exhaustive-search` 而未传确认参数必须返回 `EXHAUSTIVE_SCAN_CONFIRMATION_REQUIRED`，不能开始全盘扫描；若前面的来源已经找到可信路径，则不会进行不必要的全盘搜索。

检测到多个无法唯一判断的有效安装时，不静默选择，要求用户使用 `--version` 或 `--zemax-root`。

有效路径可以是：

- OpticStudio 安装目录：包含 `ZOSAPI_NetHelper.dll`、`ZOSAPI.dll`、`ZOSAPI_Interfaces.dll`。
- Zemax 数据目录：包含 `ZOS-API\Libraries\ZOSAPI_NetHelper.dll`。

## 独立应用程序连接流程

当用户需要自动化、批处理或生成文件时，使用独立应用程序模式。

先运行检测：

```powershell
python scripts\standalone_ping.py --zemax-root "<user zemax root>"
```

成功输出应包含：

```text
MODE=StandaloneApplication
STATUS=OK
IS_VALID_LICENSE=True
HAS_PRIMARY_SYSTEM=True
```

最小使用模式：

```python
from zemax_connection import ZemaxStandaloneAPI

with ZemaxStandaloneAPI(zemax_root=zemax_root) as z:
    system = z.system
```

独立应用程序模式由 Python 创建并拥有 OpticStudio API 实例，因此结束时可以调用 `CloseApplication()`。本 skill 的封装类会自动处理关闭。

## 交互扩展连接流程

当用户希望 Python 操作当前可见的 OpticStudio GUI 会话时，使用交互扩展模式。

运行 Python 之前，先要求用户打开 OpticStudio，并点击 `ZOS-API.NET` 区域中独立的 `交互扩展 / Interactive Extension` 按钮：

```text
编程 > 交互扩展
Programming > Interactive Extension
```

用户必须看到包含 `Instance Number` 和 `Status: waiting for connection` 的等待连接对话框。让用户对照 `picture/` 文件夹中的截图，尤其是：

- `picture/interactive-extension-button.png`
- `picture/interactive-extension-waiting-dialog.png`

不要只让用户点击下面这个入口：

```text
编程 > Python > 交互扩展
Programming > Python > Interactive Extension
```

这个入口只会创建 `PythonZOSConnectionxx.py` 模板并打开文件夹；它本身不会启动等待连接的交互扩展会话。

验证交互连接：

```powershell
python scripts\interactive_ping.py --zemax-root "<user zemax root>" --instance 0
```

如果等待连接对话框显示的实例编号不是 0，则传入对应编号：

```powershell
python scripts\interactive_ping.py --zemax-root "<user zemax root>" --instance 1
```

成功输出应包含：

```text
MODE=InteractiveExtension
STATUS=OK
APP_MODE=Plugin
IS_VALID_LICENSE=True
HAS_PRIMARY_SYSTEM=True
```

最小使用模式：

```python
from zemax_connection import ZemaxInteractiveAPI

with ZemaxInteractiveAPI(zemax_root=zemax_root, instance=instance) as z:
    system = z.system
```

交互扩展模式连接的是 OpticStudio 拥有的可见 GUI 会话；不要调用 `CloseApplication()`。

## 安全可见修改测试

当 `interactive_ping.py` 成功后，如果用户希望确认 Python 修改可以在 GUI 中实时可见，运行安全注释测试：

```powershell
python scripts\interactive_comment_test.py --zemax-root "<user zemax root>" --instance 0
```

预期现象：Lens Data Editor 中的表面注释发生变化。这个测试只改注释，不替换当前光学系统。

## `--replace-current`

如果脚本提示拒绝替换当前可见的 OpticStudio 系统，直接告诉用户：

保存原有镜头内容后，重新点击 Zemax 界面 `ZOS-API.NET` 区域中的 `交互扩展 / Interactive Extension`，保持等待连接对话框打开，然后运行新的程序，并在命令后加上 `--replace-current`。

## 常见诊断

| 现象 | 可能原因 | 下一步操作 |
|---|---|---|
| 找不到 `ZOSAPI_NetHelper.dll` | 快速来源和默认有限搜索均未找到 | 汇报扫描统计；告知全盘搜索耗时并取得允许，然后使用 `--exhaustive-search --confirm-long-scan` |
| `EXHAUSTIVE_SCAN_CONFIRMATION_REQUIRED` | 请求了全盘搜索但没有记录用户明确允许 | 先告知预计 2–15 分钟、极端情况 30 分钟以上；用户允许后补充 `--confirm-long-scan` |
| `ERROR_CODE=IPC_ACCESS_DENIED` | Agent 沙箱阻止 .NET Remoting IPC | 请求用户批准，在沙箱外重跑完全相同的命令 |
| `INTERACTIVE_MODE_MISMATCH` 且为 `Server/Timeout` | 可能是 Agent 沙箱返回的伪 Server 对象，也可能是错误的交互会话 | 在 Agent 环境先在沙箱外重跑；若仍失败，再重开独立交互扩展并核对实例号 |
| `ERROR_CODE=MULTIPLE_INSTALLATIONS` | 找到多个有效版本，无法安全选择 | 询问 2021–2025、指定目录或“我不知道”；传入 `--version` / `--zemax-root` |
| `ConnectAsExtension returned None` | 交互扩展等待连接对话框没有打开 | 在 `ZOS-API.NET` 区域打开独立的 `交互扩展 / Interactive Extension` 按钮 |
| 交互模式下出现 `NotAuthorized` | 通常是启动入口错误，或等待对话框状态失效 | 关闭并重新打开独立的交互扩展对话框，然后重跑 |
| 交互连接尝试中出现 `APP_MODE=Server` | 连接到的对象不是插件会话 | 重新启动独立的交互扩展对话框 |
| 独立模式多次返回 `LICENSE=Unknown`、`Timeout` 或 `NotAuthorized` | 隐藏的 OpticStudio 进程或许可证状态可能阻塞 API 启动 | 关闭隐藏 OpticStudio 进程或重启 OpticStudio，然后重跑 `standalone_ping.py`；若仍失败，检查许可证/API 支持 |
| `This application was not launched by Optic Studio` | 当前场景使用了错误的 API 方法 | 使用 `ConnectAsExtension(instance)`，不要使用 `ConnectToApplication()` |
| `PrimarySystem is None` | 当前没有有效的可见/打开系统 | 先在 OpticStudio 中打开或新建一个镜头文件 |
| 启动了多个 GUI 实例 | 实例编号错误 | 使用等待连接对话框中的 `Instance Number`，并传入 `--instance N` |

完整诊断命令：

```powershell
python scripts\doctor.py --mode both --zemax-root "<user zemax root>" --instance 0
```

`connection_diagnose.py` 保留用于向后兼容，新工作流使用 `doctor.py`。

## 汇报要求

帮助用户连接 Zemax 时，至少汇报以下内容：

- 选择的连接模式：`StandaloneApplication` 或 `InteractiveExtension`
- 解析到的 Zemax root
- 初始化器解析到的实际 OpticStudio 安装目录和版本
- `ZOSAPI_NetHelper.dll` 路径
- 许可证状态
- 应用模式：`Server` 或 `Plugin`
- 是否存在 `PrimarySystem`
- 用户下一步需要运行的准确命令
