# dsh_kline 安装、更新与发布优化计划

更新日期：2026-09-09

## Windows 原生适配实施记录（2026-09-09）

范围边界：Linux/Windows 上安装 DSH Web 宿主本身不属于插件职责；用户已有可运行的 DSH Web 后，插件的市场安装、首次启动、配置 Key、升级和卸载属于 `dsh_kline` 兼容范围。npm 发布继续暂缓，不影响 GitHub 安装或 Windows 适配。

本轮已实现：

- 新增跨平台 Node 启动器，由 DSH 自带的 `process.execPath` 启动，不再要求普通用户安装 Bash、Git Bash 或 WSL。
- Windows 原生识别 Python Launcher 的 3.13/3.12/3.11/3.10，以及 `python`/`python3`；虚拟环境使用 `Scripts/python.exe`。
- Windows 受管 venv、首次启动日志和图表运行文件使用 `%LOCALAPPDATA%\dsh_kline`；支持空格与中文路径，并可用环境变量显式覆盖。
- FTShare Key 在 POSIX 继续执行 `0600/0700` 校验；Windows 不再调用 Python 3.10–3.12 不支持的 `os.fchmod`，也不再套用无效的 Unix mode-bit 判断。
- Windows 原子文件替换加入有上限的短暂重试，降低杀毒软件扫描或短时文件占用导致的首次配置失败。
- 发布包普通用户 smoke test 改为直接调用跨平台 Node 入口，验证全新 venv、MCP 初始化、匿名行情、图表服务 locator 和鉴权。
- 新增 `windows-2025` 原生 CI，与 Ubuntu 一起构建、运行 Python/Node 测试并验证发布包首次启动；不能用 Wine 结果替代原生 Windows 验收。
- Release 工作流在上传资产前增加发布包首次启动 smoke test，并校验跨平台入口确实包含在 tarball 中。
- 本机已从打包后的 `0.2.2` 产物创建隔离 DSH Web profile，完成插件安装、bundle patch 解析、全新 Python venv、MCP 工具发现和图表服务健康检查；未引用开发环境。
- 本机最终回归：Python `100 passed / 1 Windows-only skipped`，Node/前端 `55 passed`，TypeScript 构建、发布包白名单、匿名行情、loopback 鉴权及隔离 DSH Web 启动均通过。

尚需完成：

- 等待 GitHub 原生 Windows CI 首次实跑，根据真实文件锁、路径或 Python Launcher 行为修正问题。
- CI 通过后，在真实 Windows DSH Web 中执行“市场安装 → 首次启动 → 配置 Key → K 线展示 → 升级 → 重启”人工验收。
- 人工验收通过前，不在正式 Release 中宣称 Windows 已完整验收。

Windows CI 首轮记录：构建、Python/Node 测试均通过；首次失败发生在发布打包器直接执行 Unix 风格 `npm` shim，Windows 返回 `spawnSync npm ENOENT`。已改为 Windows 显式使用 `npm.cmd`，并拆分打包、发布包 smoke 和 DSH profile smoke 三个 CI 步骤，等待第二轮验证。

Windows CI 第二轮记录：`npm.cmd` 调用已修复；随后发现 runner 临时目录在 C 盘、仓库在 D 盘，发布包从临时目录 `rename` 到仓库触发 `EXDEV`，已改为跨卷安全的复制。完整测试同时发现两处测试代码的 Unix 假设（系统默认文本编码与固定 `0600` mode），产品代码未失败；已改为显式 UTF-8，并仅在 POSIX 断言 Unix mode。CI 的 Python、Node 与会话测试也拆成独立步骤，避免 PowerShell 继续执行后掩盖前序失败。

Windows CI 第三轮记录：产品测试、启动器测试、会话测试及跨卷打包均通过；发布包 smoke 的系统 `tar` 无法直接 `chdir` 到中文目录，runner codepage 将路径显示成 `??`。已调整为先在 ASCII 临时目录解压，再用 Node 文件 API 移入中文/空格安装路径；继续保留 Unicode 安装路径的真实运行验证，不把系统 tar 的编码限制绕过为纯 ASCII 测试。

## 目标

让普通用户能够从 DSH 插件市场可靠地找到、安装、首次启动和更新 `dsh_kline`，并能明确看到当前版本与最新稳定版本。

核心原则：

- 优先保证普通用户安装成功，不要求用户理解 Python、venv 或 MCP 调试。
- GitHub 提交、版本号、Release 和插件市场记录必须形成可核验的发布链路。
- 不覆盖或自动修复开发者自行维护的项目 `.venv`。
- 每一步独立实施、验证和提交，避免把安装问题、市场问题和业务功能混在一起。

## 当前状态

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 1. 安装与首次启动自修复 | 已完成，待推送 | 本地实现及测试已完成 |
| 2. 插件市场版本与更新链路 | 已完成可控部分，待推送 | Release 产物与自动化已完成；市场语义版本受上游能力限制 |
| 3. 普通用户完整安装验收 | 待开始 | 使用全新环境验证 |
| 4. 跨平台支持 | 已实现，待原生 CI 与实机验收 | Node 跨平台入口、Windows 路径/凭据与安装测试已加入 |
| 5. 发布自动化与长期监控 | 待开始 | 在前面流程稳定后实施 |

## 第一阶段：安装与首次启动自修复

状态：已完成，待提交和推送。

已实现：

- 首次启动时自动创建用户级 Python 环境并安装依赖。
- 使用 `requirements.txt` 指纹识别依赖变化，版本升级后自动同步依赖。
- 启动前验证 `ftshare`、`mcp`、`pydantic` 和 `pydantic-settings` 等核心模块。
- 安装中断或环境不完整时，下次启动自动续装和修复。
- 安装过程输出清晰的阶段提示，并保存最新一次 `bootstrap.log`。
- 仓库内开发 `.venv` 保持人工管理；发现异常时只提示，不自动改写。

验收结果：

- 安装专项测试：8/8 通过。
- Python 全量测试：103/103 通过。
- Shell 语法、代码差异和发布产物检查通过。

涉及文件：

- `scripts/run-dsh-kline.sh`
- `scripts/bootstrap.sh`
- `tests/test_distribution_install.py`

## 第二阶段：插件市场版本与更新链路

目标：插件市场能够正确展示当前版本和最新稳定版本，并让用户安装或更新到对应的 GitHub Release。

机制核实结果（2026-09-09）：

- `awesome-dsh-plugin` 的在线目录已经收录 `dsh_kline`，但当前为 GitHub-only 安装，因此目录中的 `version` 是 `null`。
- 当前 `dsh-market` 对 GitHub 安装使用 commit SHA 判断是否有更新；已安装版本可从插件 `package.json` 读取，但更新目标不是 GitHub Release 版本号。
- 目录仅为已自动关联的 npm 包填充最新版本；GitHub Release 版本暂未进入市场发现页的版本字段。
- 市场支持作者提供 GitHub Release `.tgz`，并推荐使用不带版本号的固定资产名配合 `releases/latest/download/`。
- 实测 `dsh-market` 1.45.1：从上述 Release tarball 安装只需约 4 秒，但更新检查会把该 URL 归入 npm 路径，返回 `current: null`、`latest: null`，无法发现后续更新。因此当前不能把市场安装源切换为 tarball。
- 本机没有 npm 登录状态，`@ftshare-lab/dsh-kline` 也尚未发布至 npm，因此本阶段不把 npm 发布作为前置条件。

当前实施方案：

- GitHub Release 固定附加 `dsh-kline.tgz` 和校验文件。
- 发布工作流校验 Git tag 与 `package.json` 版本完全一致。
- 发布包使用明确的文件白名单，避免把开发环境、测试缓存或本地文件打入安装包。
- 插件市场暂时保留 `github:FTShare-Lab/dsh_kline`，以保留基于 commit SHA 的更新检测。
- `https://github.com/FTShare-Lab/dsh_kline/releases/latest/download/dsh-kline.tgz` 作为正式 Release 的固定安装资产和故障兜底，不作为当前市场默认来源。
- 保留插件自身基于 GitHub 最新稳定 Release 的版本提示。

已完成：

- `v0.2.0` Release 已附加固定名称的 `dsh-kline.tgz` 与 SHA-256 校验文件。
- 已用隔离的普通 DSH 环境从 Release 包完成安装，耗时约 4 秒，包版本为 `0.2.0`。
- 已增加 Release 工作流：校验 tag/版本、运行构建和 Python 全量测试、检查发布包内容，再上传固定名称资产。
- 已增加发布文件白名单与发布包专项测试，避免将 `.venv`、`node_modules`、测试文件或开发缓存带给用户。

已知边界：在 `dsh-market` 支持 GitHub Release 版本字段之前，市场发现页仍不能为 GitHub-only 插件直接显示最新语义化版本。要彻底实现该项，需要发布 npm 包，或向 `awesome-dsh-plugin`/`dsh-market` 上游补充 GitHub Release 版本协议、tarball 更新判断与展示逻辑。就现有市场实现而言，发布 npm 是较短且可控的路径，但需要 `@ftshare-lab` 的 npm 发布权限。

计划：

1. 核实 DSH 插件市场的索引格式、缓存策略、版本解析规则和安装来源。
2. 核实 `awesome-dsh-plugin` 中 `dsh_kline` 的条目、搜索字段、仓库地址及版本字段。
3. 明确四个版本来源的唯一对应关系：
   - `package.json` 中的版本号；
   - Git tag；
   - GitHub Release；
   - 插件市场展示与安装的版本。
4. 让“安装”默认获取最新稳定 Release，而不是不确定的分支快照或旧缓存。
5. 让已安装用户能判断是否存在新版本，并提供明确的更新入口或提示。
6. 为市场索引不可用、GitHub 请求失败和旧版 DSH 客户端设计降级提示。

验收标准：

- 搜索 `dsh_kline` 可以稳定找到插件。
- 市场页面显示的最新版本与 GitHub 最新稳定 Release 一致。
- 已安装页面能区分“当前版本”和“可更新版本”。
- 全新用户安装后实际运行的版本与页面展示一致。
- 发布新版本后，按已确认的缓存刷新周期能被市场识别。
- 未创建新版本号和 GitHub Release 时，普通 `push` 不会被错误地宣传为正式更新。

预计耗时：2–4 小时。如果 DSH 市场本身不支持版本或更新字段，需要同时修改市场/DSH 上游逻辑，时间需另行评估。

## 第三阶段：普通用户完整安装验收

目标：从“搜索插件”开始，以普通用户身份验证完整流程，而不是复用开发环境。

测试场景：

- 全新 DSH Web 环境首次安装。
- 路径包含空格和中文。
- 机器只有一个符合要求的 Python 版本。
- 首次安装被中断后重新启动。
- 从上一稳定版本升级到最新稳定版本。
- 未配置 FTShare Key、免费 Key 和付费 Key 三种启动状态。
- 卸载后重新安装，不依赖仓库目录或开发软链接。

验收标准：

- 安装过程不会长时间无反馈。
- 首次启动失败时能给出用户可执行的原因和日志位置。
- MCP Server、侧栏页面和 K 线功能均能正常加载。
- 安装和更新不引用开发机绝对路径。

预计耗时：1–2 小时。

## 第四阶段：跨平台支持

实现状态：代码适配完成，待 GitHub 原生 Windows CI 和真实 Windows DSH Web 验收。

本插件不负责安装 DSH Web 宿主。普通用户运行入口已经从 Bash 迁移到 Node，并补齐 Windows Python Launcher、用户目录、凭据权限和短暂文件锁处理。只有原生 CI 及实机完整流程均通过后，才能对外标记 Windows supported。

## 第五阶段：发布自动化与长期监控

计划：

- 在 CI 中校验 `package.json`、Git tag、Release 和市场条目版本一致。
- Release 前自动运行安装专项测试、全量测试和发布包检查。
- 对发布包执行一次隔离环境 MCP 启动测试。
- 生成版本更新说明和安装验证记录。
- 对插件市场索引延迟或版本不一致给出告警，而不是依赖人工发现。

预计耗时：2–4 小时，具体取决于插件市场是否提供可自动查询的版本接口。

## 推荐执行顺序

1. 审核并提交第一阶段改动。
2. 完成第二阶段的市场机制核实，再决定只修改市场条目，还是同时修改 DSH 更新逻辑。
3. 创建一个测试 Release，执行第三阶段的普通用户端到端验收。
4. 验收通过后发布正式版本。
5. 最后补齐 CI、自动校验和可选的 Windows 支持。

## 发布纪律

一次正式发布至少应同时满足：

- 版本号已更新。
- 对应 Git tag 已创建并推送。
- GitHub Release 已发布且产物可安装。
- 插件市场指向同一稳定版本。
- 普通用户安装验收已通过。

仅向 GitHub 分支执行 `push` 不等同于发布新版本，也不能保证插件市场用户自动获得最新版。
