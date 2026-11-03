# v0.6.1 · 安装与宿主适配修复

- Codex 连接先完成 MCP 握手，首次 Python 依赖安装在后续进行；准备期间提供 `ft_kline_runtime_status`，就绪后在同一连接通知更新工具目录，避免安装耗时阻塞连接。
- 默认入口按宿主声明的 MCP Apps HTML 能力选择图表或无界面模式；CLI 不再误启用桌面绘图工具。高级接入可显式指定模式。
- 支持只读复用用户明确指定的 `FTSHARE_API_KEY_FILE`。凭据优先级为环境变量、显式文件、App 临时 Key；不扫描 DSH 或其他应用、不回显 Key/路径、不修改文件。
- 修复图表初始化期间收到的新结果被误去重，导致画布漏更新的问题。
- Codex ZIP 自带本地 marketplace 清单；README 提供完整安装命令、前提、首次验证和 Key 来源说明。

下载 `dsh-kline-v0.6.1.tgz` 安装 DeepSeek Harness 版；下载 `ft-kline-v0.6.1.zip` 安装 Codex 版。两者使用不同安装入口，并非通用包自动猜测宿主。每个包均附同名 `.sha256` 校验文件。

Codex 包解压到长期保留的目录后执行：

```bash
codex plugin marketplace add "/absolute/path/ft-kline-v0.6.1"
codex plugin add ft-kline@ftshare-local
```

需要 Node.js 22.19+ 和 Python 3.11+。首次准备可能需要数分钟；不支持工具目录变更通知的客户端，可在准备完成后重开对话。桌面应用仅能继承自身启动环境中的 Key；终端中的配置不一定可见。

自动化覆盖实际 Node 入口、准备状态到完整工具的升级、桌面/CLI 能力选择、显式凭据文件和渲染缓存回放。完整 macOS/Windows 桌面人工画布验收尚未补齐；服务端提交和 UI 回执不等于实际屏幕观察。Codex 仍通过本地/私有来源分发，尚未上架公共插件目录。详见[验收说明](https://github.com/FTShare-Lab/dsh_kline/blob/v0.6.1/docs/release-acceptance-v0.6.1.md)。
