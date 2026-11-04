# v0.6.4 · 启动与 Python 环境升级修复

- DSH 的 MCP 入口从插件模块自身定位安装目录，修复 K 线包被 bundle 嵌套安装后因不存在的工作目录而发生 `spawn ENOENT`。保留绝对路径 `DSH_KLINE_PACKAGE_ROOT` 绕行；路径无效时明确报错。
- 依赖更新优先在有效的现有 venv 中补装，不再因为找不到 PATH 上的基础 Python 而要求重建已有环境。需要重建时，可复用 `pyvenv.cfg` 的基础解释器或 Windows Desktop 随附的 Python；必须具备 venv/ensurepip 能力，裁剪版 Python 不会被误判为可建环境。macOS 不自动选择应用内受签名限制的私有 Python，继续使用独立解释器或显式配置。
- requirements 指纹只在 pip 成功且依赖校验通过后写入。校验包含 requirements 中固定版本，修复“模块能导入但仍是旧版本”被当成升级成功的问题。
- 失败冷却记录绑定解释器配置、PATH 和候选文件状态；修正路径或安装解释器后立即重新尝试。旧格式失败标记不会继续阻挡修复。
- 失败状态记录明确的错误码，区分未找到解释器、版本过低、不能执行、缺 venv/ensurepip、pip 失败及导入校验失败。Windows Store 占位符另有提示；可正常工作的 Store Python 仍可使用。基础解释器候选的路径、版本及结果写入 bootstrap.log，不记录父进程环境或凭据。
- DSH 与 Codex 使用相同版本的运行环境修复；Codex 独立安装包和公开 GitHub 插件源同步至 v0.6.4。

安装包：`dsh-kline-v0.6.4.tgz`、`ft-kline-v0.6.4.zip`，以及各自的 SHA-256 文件。

本版不宣称已完成报告方 Windows/Electron 机器的现场验收；自动化结果和验证范围见 [验收记录](release-acceptance-v0.6.4.md)。bundle 若固定依赖旧版 K 线包，需要由 bundle 维护者更新依赖或启动入口。
