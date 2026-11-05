# v0.6.5 验收

## 验证范围

- DSH 宿主面板属性映射、无宿主默认行为和仅内嵌挂载时安装的桥接口。
- 标的比较保留市场身份、交易所别名归一化和图表输入规则一致性；覆盖上证指数与平安银行、V 与 VZ、不同美股股类以及香港代码补零。
- 执行实际 `StandaloneKlineApp` 的属性更新及依赖驱动副作用，验证切换不同证券会调用打开接口，同一证券的别名回传不会重复打开；主题深色/浅色切回未指定时通知恢复宿主模式；全程仅挂载一次。
- 实际视图运行函数解除固定主题后跟随宿主后续配色变化。
- 版本目录生成、DSH 客户端构建、双包内容校验、Codex ZIP 与独立 GitHub 插件目录逐文件同步。
- macOS/Linux/Windows × Python 3.11/3.12/3.13 的完整测试、普通安装、DSH 独立 profile 与嵌套 bundle 安装、Codex 桌面/CLI 入口烟测。

## 证据与发布门槛

- 两处组件回归测试在原 PR 提交 `e4a12d1` 上均失败，修复后通过。
- 功能修复提交 `07df2a0` 的本地 Node 340 项、Python 498 项通过，另有 1 项跳过和 361 个子测试通过；[test 分支九组跨平台 CI 全部通过](https://github.com/FTShare-Lab/dsh_kline/actions/runs/41982003350)后已合并 main。
- v0.6.5 发行提交必须重新通过 test 分支同一提交的九组跨平台 CI，再合并 main、创建版本标签并运行双包发行流水线；可在 [安装 CI](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/install.yml)和[发行流水线](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/release.yml)按提交或标签核对。
- 正式发布前下载草稿中的两个安装包和校验文件，核对 SHA-256、版本、编译客户端与公开插件目录内容。

上述组件测试隔离了 DOM 渲染器和图表挂载，覆盖实际属性到桥接口的调用；它们不等于在实际画布或模拟盘宿主中完成了像素级验收。本次未新增这类宿主的人工验收，也未重新验收行情与绘图效果。
