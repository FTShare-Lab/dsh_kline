# v0.6.4 验收

## 修复与回归范围

- 根目录安装与 bundle 嵌套安装（profile 根不存在 K 线包），包含中文和空格路径。
- 已有 venv 在缺少 PATH 基础解释器时补装；依赖版本不符时修复；失败后不得提前更新指纹或启动服务。
- 配置更正或解释器新增后立即重试；未改变环境的安装失败保留有限冷却。
- Windows Desktop 随附解释器和 pyvenv.cfg 路径解析；裁剪解释器缺 venv/ensurepip 时给出不同于版本不足的错误。
- 构建、完整 Node/Python 回归、双包、独立 GitHub 插件目录同步及安装烟测。
- macOS/Linux/Windows × Python 3.11/3.12/3.13 的同一提交 CI。

## 证据

- 本机 macOS：侧栏构建和包内容校验通过；Node 327/327，Python 498 通过、1 跳过、361 个子测试通过；诊断与路径测试在最后调整后另行通过。
- 真实 Python/venv/pip 离线升级用例通过：缺少基础解释器时复用旧 venv，不请求行情或依赖网络。
- 中文与空格路径中的 DSH 全新首启、41 个 MCP 工具、TA-Lib 201 函数、HTTP 服务与访问限制烟测通过。
- 实际 DSH Web 的直接安装与嵌套 bundle 安装都能启动 MCP/图表服务；嵌套测试确认 profile 根没有 K 线包。模块路径及显式覆盖路径还覆盖 symlink / Windows junction。
- Codex ZIP 与公开 GitHub 插件目录的桌面 / CLI 入口烟测通过，独立目录逐文件校验通过。
- 使用已安装 Desktop 的 Electron 可执行文件及 `ELECTRON_RUN_AS_NODE=1`，完成全新 venv、41 个工具、201 个 TA-Lib 函数和图表 HTTP 服务首启烟测。未修改 Electron 启动方式或签名设置。
- 补测发现 macOS 应用内 Python 的签名限制会阻止加载新装的原生 wheel，因此自动探测宿主私有 Python 仅限 Windows；macOS 使用独立解释器或显式配置。
- 第一轮 Windows CI 的直接安装通过；嵌套测试被 Git-for-Windows tar 的中文参数编码阻断，已改为 Python 标准库的 Unicode 解包。发布以修正后的同一提交重跑九组结果为准，不沿用该失败运行。
- 发布前以同一提交的九组跨平台 CI 和双包发行流水线为门槛；记录可在 [GitHub Actions](https://github.com/FTShare-Lab/dsh_kline/actions) 按版本或提交核对。发布资产须下载后校验 SHA-256、版本及插件目录内容。

以上不等于报告方 Windows/Electron 机器的现场验收；本次没有重新评估行情与绘图能力。
