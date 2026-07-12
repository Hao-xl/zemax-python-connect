# zemax-python-connect

`zemax-python-connect` 是一个用于建立 Python 与 Ansys Zemax OpticStudio 之间 ZOS-API 连接的 Codex/agent skill。

这个包只负责连接配置和连接验证，不负责光学设计、评价函数构建、优化、MTF/点列图分析或容差策略。

## 支持能力

- 独立应用程序模式：Python 通过 `CreateNewApplication()` 启动并控制自己的 OpticStudio API 会话。
- 交互扩展模式：Python 通过 `ConnectAsExtension(instance)` 连接到当前可见的 OpticStudio GUI。
- 在不同用户电脑上自动查找 ZOS-API DLL。
- 提供基础连接诊断和安全的 GUI 可见修改验证。

## 环境要求

- Windows
- 支持 ZOS-API 的 Ansys Zemax OpticStudio
- 与当前 OpticStudio/pythonnet 环境兼容的 Python
- `pythonnet`

安装依赖：

```powershell
pip install -r requirements.txt
```

## 零基础推荐流程

只需先运行一个命令：

```powershell
python scripts\doctor.py --mode locator
```

该命令会检查 Python/pythonnet、查找 `ZOSAPI_NetHelper.dll`、初始化 NetHelper，并验证初始化器返回的实际 OpticStudio 安装目录中确实存在 `ZOSAPI.dll` 和 `ZOSAPI_Interfaces.dll`。

如果检测到多个版本，请选择 `2021`、`2022`、`2023`、`2024` 或 `2025`：

```powershell
python scripts\doctor.py --mode locator --version 2023
```

如果你知道安装目录，可以直接指定：

```powershell
python scripts\doctor.py --mode locator --zemax-root "D:\Path\To\OpticStudio"
```

快速来源没有找到可信路径时，脚本会自动执行最大深度为 5 的有限磁盘搜索。`--deep-search` 可用于强制执行有限搜索或兼容旧工作流：

```powershell
python scripts\doctor.py --mode locator --deep-search
```

搜索输出会列出已扫描目录数、权限拒绝目录数、其他扫描错误数和耗时，不会静默忽略无权限目录。

若有限搜索仍失败，全盘搜索通常约需 2–15 分钟；文件很多或磁盘较慢时可能超过 30 分钟。Agent 必须先告知此估计并询问用户是否允许。只有用户明确允许后才能运行：

```powershell
python scripts\doctor.py --mode locator --exhaustive-search --confirm-long-scan
```

当快速来源和有限搜索均失败、确实需要全盘搜索时，只传 `--exhaustive-search` 不会开始扫描，而会返回 `EXHAUSTIVE_SCAN_CONFIRMATION_REQUIRED`。若前面的来源已经找到可信路径，则会直接使用该路径。Agent 向用户询问版本或目录时，应始终提供“我不知道”选项。

### Agent 沙箱说明

ZOS-API 使用 .NET Remoting IPC。Agent 沙箱可能允许找到和加载 DLL，却阻止创建/连接 OpticStudio，典型输出为：

```text
ERROR_CODE=IPC_ACCESS_DENIED
System.Runtime.Remoting.RemotingException
连接到 IPC 端口失败: 拒绝访问
```

这时不要误判为 DLL 或许可证问题。Agent 应请求用户批准，在沙箱外重新运行完全相同的连接命令。

## 第一步：定位 ZOS-API

先尝试自动发现：

```powershell
python scripts\zosapi_locator.py --list-candidates
```

如有需要，显式传入你的 OpticStudio 路径：

```powershell
python scripts\zosapi_locator.py --zemax-root "C:\Path\To\Ansys Zemax OpticStudio"
```

这个路径可以是以下两类之一：

- OpticStudio 安装目录：包含 `ZOSAPI_NetHelper.dll`、`ZOSAPI.dll` 和 `ZOSAPI_Interfaces.dll`。
- Zemax 数据目录：包含 `ZOS-API\Libraries\ZOSAPI_NetHelper.dll`。

自动发现会检查运行中 `OpticStudio.exe` 的 ExecutablePath（最高优先级）、环境变量、Documents/OneDrive Known Folder、Zemax 与 App Paths 注册表、32/64 位卸载信息、Windows Installer Products/UserData、PATH 和常见安装目录。

## 模式 A：独立应用程序

当你需要自动化、批量建模或生成文件，并且不需要实时观察 GUI 变化时，使用这个模式。

运行：

```powershell
python scripts\standalone_ping.py --zemax-root "C:\Path\To\Ansys Zemax OpticStudio"
```

成功输出类似：

```text
MODE=StandaloneApplication
STATUS=OK
IS_VALID_LICENSE=True
HAS_PRIMARY_SYSTEM=True
```

最小示例：

```powershell
python examples\standalone_minimal.py --zemax-root "C:\Path\To\Ansys Zemax OpticStudio"
```

## 模式 B：交互扩展

当你希望 Python 修改当前正在看的 OpticStudio 窗口时，使用这个模式。

### 必须先完成的 OpticStudio GUI 操作

打开 OpticStudio，并点击 `ZOS-API.NET` 区域中独立的 `交互扩展 / Interactive Extension` 按钮：

```text
编程 > 交互扩展
Programming > Interactive Extension
```

你应该看到类似这样的等待连接对话框：

![交互扩展等待连接对话框](picture/interactive-extension-waiting-dialog.png)

对话框中应显示 `Instance Number` 和等待连接状态。运行 Python 时保持该对话框打开。

不要只依赖下面这个菜单：

```text
编程 > Python > 交互扩展
Programming > Python > Interactive Extension
```

这个菜单只会创建 Python 模板文件，本身不会启动等待连接对话框。

### 验证连接

如果对话框显示实例号为 `0`：

```powershell
python scripts\interactive_ping.py --zemax-root "C:\Path\To\Ansys Zemax OpticStudio" --instance 0
```

如果对话框显示实例号为 `1`：

```powershell
python scripts\interactive_ping.py --zemax-root "C:\Path\To\Ansys Zemax OpticStudio" --instance 1
```

成功输出类似：

```text
MODE=InteractiveExtension
STATUS=OK
APP_MODE=Plugin
IS_VALID_LICENSE=True
HAS_PRIMARY_SYSTEM=True
```

### 安全可见修改测试

当 `interactive_ping.py` 成功后，运行：

```powershell
python scripts\interactive_comment_test.py --zemax-root "C:\Path\To\Ansys Zemax OpticStudio" --instance 0
```

这个脚本只修改 Lens Data Editor 的注释，是确认 Python 修改可以在 OpticStudio 中可见的安全方法。

## 关于 `--replace-current`

如果后续程序提示拒绝替换当前可见的 OpticStudio 系统，先保存原有镜头内容，重新点击 OpticStudio `ZOS-API.NET` 区域的 `交互扩展 / Interactive Extension`，保持等待连接对话框打开，然后在运行新程序时在命令后追加 `--replace-current`。

## 完整诊断命令

```powershell
python scripts\doctor.py --mode both --zemax-root "C:\Path\To\Ansys Zemax OpticStudio" --instance 0
```

该命令会输出稳定 JSON，包括运行环境、所有候选路径、NetHelper、实际安装目录、DLL 路径、许可证状态、应用模式、主系统状态、错误分类和建议的下一步操作。`connection_diagnose.py` 保留用于向后兼容。

## 仓库结构

```text
zemax-python-connect/
  SKILL.md
  README.md
  requirements.txt
  scripts/
    zemax_discovery.py
    zemax_connection.py
    zosapi_locator.py
    doctor.py
    standalone_ping.py
    interactive_ping.py
    interactive_comment_test.py
    connection_diagnose.py
  examples/
    standalone_minimal.py
    interactive_minimal.py
  picture/
    README.md
  evals/
    evals.json
```

## 故障排查摘要

| 输出或现象 | 含义 | 处理方式 |
|---|---|---|
| `STATUS=OK` | 已正确连接 | 继续使用当前选择的连接模式 |
| 找不到 `ZOSAPI_NetHelper.dll` | 快速来源和默认有限搜索都失败 | 汇报扫描统计；说明全盘扫描耗时并取得允许，然后用 `--exhaustive-search --confirm-long-scan` |
| `EXHAUSTIVE_SCAN_CONFIRMATION_REQUIRED` | 请求全盘搜索时未确认用户已允许 | 先告知预计 2–15 分钟，极端情况超过 30 分钟；明确允许后再加 `--confirm-long-scan` |
| `ERROR_CODE=IPC_ACCESS_DENIED` | Agent 沙箱阻止 .NET Remoting IPC | 请求批准并在沙箱外重跑完全相同的命令 |
| `INTERACTIVE_MODE_MISMATCH` 且为 `Server/Timeout` | 可能是沙箱伪连接或错误交互会话 | Agent 环境先在沙箱外重跑；仍失败再重开交互扩展并核对实例号 |
| `ERROR_CODE=MULTIPLE_INSTALLATIONS` | 找到多个版本，不能安全猜测 | 使用 `--version` 或 `--zemax-root`；不知道时列出候选让用户确认，不能靠重复扫描猜测 |
| `ConnectAsExtension returned None` | 交互扩展对话框没有打开 | 打开独立的 `交互扩展 / Interactive Extension` 对话框 |
| `LICENSE=NotAuthorized` | API 对象没有授权 | 重新打开正确的交互扩展对话框，或检查许可证 |
| 独立模式多次显示 `LICENSE=Unknown`、`Timeout` 或 `NotAuthorized` | 隐藏或失效的 OpticStudio 进程、许可证状态可能阻塞 API 启动 | 关闭隐藏 OpticStudio 进程或重启 OpticStudio，然后重跑 `standalone_ping.py` |
| 交互检测中出现 `APP_MODE=Server` | 没有连接到插件会话 | 从 `ZOS-API.NET` 区域重新启动交互扩展 |
| `PrimarySystem is None` | 当前没有打开或有效的光学系统 | 在 OpticStudio 中打开或新建一个镜头文件 |
