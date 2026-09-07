# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

（新版本变更将集中在此。）

## 0.1.5 - 2026-09-07

### Fixed

- Pass the loaded KLineCharts dependency explicitly into the scoped chart runtime instead of relying on a cross-realm global lookup.
- Ship the browser runtime in the repository so direct GitHub installs and updates do not depend on blocked lifecycle build scripts.
- Make failed vendor loads retryable and replace the obsolete inline vendor placeholder with a working standalone preview script.

## [0.1.4] - 2026-09-05

### Added

- 底部大盘行情条接入官方全球指数端点：恒生/纳指/上证/沪深300/深成 5 条指数在配置 FTShare Key 后全部走官方数据（A 股指数走 `index_candlesticks`，全球指数走新增登记的 `global_index_daily_kline`）；大盘条条目可点击，直接打开对应指数的 K 线图。
- 内置免费大盘兜底（`tools/free_sources.py`）：无 Key/匿名或官方接口不可用时，大盘条自动回退腾讯公开行情快照，指数日 K 回退东方财富（再兜底腾讯），保证免费用户仍能看到大盘数据；所有免费回退数据均标注 `eastmoney_free` / `tencent_free` 来源与链接，不冒充 FTShare。

### Changed

- 将 FTShare Python SDK 从 1.0.0 升级到 1.0.3，并将默认 `/gateway` 基址、免费/基础/进阶/专业套餐边界同步到官方文档。
- 免费版股票日 K、指数日 K 和证券目录能力重新执行匿名实测；需付费权限的股票/指数历史分钟、港股与新闻能力仅按官方 SDK 契约对齐，不标记为实盘验证通过。
- `fetch_candles` 识别全球指数（`100.*`）并路由到 FTShare 官方日 K 端点（周/月/季/年本地聚合）；`data_source_status` 与设置页数据源信息新增内置免费源能力摘要。

### Fixed

- 将指数历史分钟行情路由从旧的 `api/v3` 对齐为 1.0.3 的 `api/v2`，调用时转换为接口要求的 `.SH/.SZ/.BJ` 短后缀并移除不支持的复权参数。
- SDK 分钟接口显式请求 Python 行数据，避免默认 DataFrame 返回类型绕过适配层约定。
- 兼容 FTShare 1.0.3 免费指数目录的双层 `data.records` 响应包装，避免目录刷新静默丢失指数条目。
- 修复 `scripts/bootstrap.sh` 在受支持 Python 版本上仍会抛出 `TypeError` 的条件退出写法。

## [0.1.3] - 2026-09-04

### Added

- FTShare SDK 1.0.0 适配：实测并登记 A 股指数日 K 端点 `index_candlesticks`（api/v1/market/data/index-candlesticks，免费可用），沪深300/上证/深成指等指数对比预设随之启用；指数分钟（`index_minutes`）依赖套餐，无 Key 时返回可执行提示。
- 标的名称旁新增收藏星标：点击即可将当前标的加入/移出当前自选分组，状态随浏览器本机保存，并与图表右键菜单、自选栏保持一致。
- 新增“点位”标注能力：可在图表上添加任意价格的水平价位线，或在任意 K 线上放置文本标注，支持名称/备注/颜色，行内改价、改名、单条删除与一键清空。
- 关键点位标注可编辑：点击“关键点位”后，自动识别的支撑/压力进入可编辑列表，可改价（名称自动同步）、改名、删除或“转我的”固化为自定义点位，不会被后续重分析冲掉。
- 补齐侧栏“关键点位”按钮的后端通道：新增 `analyze_kline` 的 loopback chart API action 并在 web 白名单放行（此前点击必然返回 `unsupported_chart_action`）。
- 对比面板指数预设按数据源能力控制：`data_source_status` 新增 `index_kline` 能力字段；数据源不支持 A 股指数 K 线时，“沪深300/上证”预设自动禁用并提示原因。
- 点位数据随浏览器本地持久化（工作区存储升级为 v8，兼容旧版本读取），并纳入“导出/导入本机数据”。
- provider-neutral 测试补充 chart API `analyze_kline`（支撑/压力标注命令、参数校验、取数错误透传）与 `index_kline` 能力位覆盖。

### Fixed

- 修复“清标注”按钮无反应的问题：现在会清除自动支撑/压力等分析标注与选区（含点位面板中的自动列表），保留自定义点位与用户画线，并在没有可清除内容时给出提示。
- 修复 MA 与 BOLL 无法同屏显示的问题：蜡烛窗内的指标改为叠加创建，二者（及 VWAP）可同时显示。
- 修复侧栏“关键点位”按钮始终失败的问题（补齐 chart service `analyze_kline` 与 web 层白名单）。
- 修复对比预设指数在当前数据源必然失败却可点的问题（改为按能力禁用而非点击后报错）。
- 修复自定义价位/文本标注价格输入在列表中被千分位格式化污染的问题（数值框使用原生数字值）。
- 补充 DeepSeek Harness 插件市场接入说明和界面截图；用户可在插件市场搜索并安装 `dsh_kline`，发布新版本后可从同一处同步并更新插件。
- 增加受控的 FTShare 契约注册表与通道记录：仅在已核实的官方路径和 SDK 候选之间有限回退；认证/套餐权限不换通道，限流仅在原通道退避重试，并补充 SDK 漂移错误分类与回归测试。
- 在数据源状态中公开候选通道的验证标记；未取得分钟权限前不把分钟 GET/SDK 候选标记为真实通过。
- 明确契约候选验证标记随每次发版或 SDK 升级重新核验；日 K 的 SDK 候选已纳入已验证通道。
- 连接测试改为先验证基础行情，再单独探测分钟行情权限；免费版 Key 不会因分钟线未开通而被误报为无效，并返回安全的能力状态。
- 新增本地证券目录驱动的标的名称解析，支持中文名称、裸代码和常见交易所代码格式；新增 `search_symbols` MCP 工具。
- 新增关键点位分析、区间统计、右键加入/移出自选反馈，以及外部数据源提供 OHLCV 后的完整分析工作流。
- 新增英文模式下区间统计、简况、财务和股东信息的字段本地化。
- 新增 `analyze_kline_rows`，支持任意调用方提供的标准化 OHLCV 数据完成指标、图表和侧栏工作流。
- 前端数据源状态栏提示外部数据源接入方式。
- 分钟线在 FTShare 返回 401 时显示配置 `FTSHARE_API_KEY` 的简明提示。
- 保留底部大盘行情区域；暂无大盘数据时显示占位，接入数据源后自动展示。
- 统一数据源提示为“温馨提示”，并在新闻/简况无数据时显示可理解的说明。
- 右上角新增使用帮助，说明分钟线、外部数据源、FTShare 配置、当前版本和更新入口。
- 修复无 API key 时只能搜索内置少量标的的问题，优先使用本地证券目录搜索。
- 明确搜索入口只使用 dsh_kline 本地证券目录，彻底移除 FTShare 搜索接口调用。
- 在帮助面板说明自选与分组的浏览器本地保存边界。
- 设置页增加 FTShare API Key 的配置、清除和连接测试入口；Key 可安全保存到本机并在重启后自动加载，不回显、不写入图表状态。
- 新增 `data_source_status`、`configure_ftshare` 和 `test_ftshare_connection`，为未来支持更多 API 数据源预留统一配置边界。
- 将非法 K 线周期改为中文可执行提示并列出允许值，避免暴露 Pydantic 内部错误和文档链接。
- 修复设置页 FTShare 配置请求未接入 loopback chart service、导致配置操作被误报为不支持 action 的问题。
- 修复美股周/月/季/年线先截断再聚合导致首根 K 线不完整的问题。
- 修复外部 `analyze_kline_rows` 将自定义标的标签错误限制为本地证券目录的问题。
- 统一无数据、数据权限和分钟线不可用时的中文可执行提示，并清理跨标的残留选择状态。
- 移除无引用的本地证券 mock 数据，避免模拟内容被误认为真实行情或资讯。

### Changed

- 默认展示收敛为 MA + VOL + MACD（BOLL/KDJ/RSI/ATR/VWAP 仅在需要时手动开启），默认时间范围为今年（YTD）；仅当分析请求明确指定指标时才自动切换指标栈，旧版偏好在首次打开时迁移一次。
- FTShare 降级为可选适配器；`health` 不再因 FTShare 缺失而判定 dsh_kline 整体不可用。
- 使用 FTShare v1 SDK 的 `stock_minutes` 接口获取分钟线，并保留旧 SDK 兼容回退。
- 设置页集中语言、主题、数据源和帮助，FTShare 配置失败时保留其他数据源工作流。

### Security

- 外部 K 线输入增加有限数值校验和 12000 行输入上限。
- FTShare API key 仅由服务端注入 FTShare 请求，可通过本机凭据文件或环境变量提供，不写入仓库或图表数据。
- 图表 loopback 服务增加进程级 token、Host 白名单和 JSON 请求校验；公开会话与浏览器不持有服务 token。

## [0.1.2] - 2026-08-21

### Added

- 搜索栏支持直接搜索股票代码或名称，并可从搜索结果打开新的标的工作区。
- 支持同时打开多个标的，并在搜索栏下方以独立 tab 栏管理工作区。
- 自选列表支持行情展示、分组、排序和批量打开。

### Fixed

- 标的 tab 从搜索/操作栏移出，避免与品牌、搜索框和操作按钮争抢横向空间。
- 单个标的时自动隐藏 tab 栏，多个标的时保持 tab 宽度稳定并支持横向滚动。
- 稳定图表头部、行情信息和指标值布局，避免与 K 线区域重叠。

### Removed

- 移除仅用于开发验证的 smoke/live 脚本、测试代码和调试命令，精简正式源码仓库。
- 移除 README 展示截图和内部架构文档；前端来源说明保留为根目录的 `PROVENANCE.md`。

## [0.1.1] - 2026-08-20

### Added

- 原生 DeepSeek Harness 侧栏中的版本更新提示与 GitHub Release 链接。
- 中文 README、交互式图表示例和用户使用说明。

### Fixed

- 图表静态资源不再依赖已有图表会话，避免空会话时加载失败。
- 恢复原生 MA 图例的单行布局与完整标签。
- 指标切换后保持当前图表会话数据，避免错误提示。

## [0.1.0] - 2026-08-16

### Added

- 首个独立发布：支持港股、美股和 A 股的 K 线分析 MCP。
- 交互式侧栏、技术指标、支撑压力位、区间统计、新闻与基本面信息。
