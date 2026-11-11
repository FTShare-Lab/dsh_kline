# 非凸 K 线助手 · FT K-Line

在 **DeepSeek Harness** 与 **Codex** 中看行情、分析走势，用自然语言或绘图工具直接操作图表。

简体中文 · [English](README.en.md)

[![跨平台测试](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/install.yml/badge.svg?branch=main)](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/install.yml) [![最新发布](https://img.shields.io/github/v/release/FTShare-Lab/dsh_kline?label=Release)](https://github.com/FTShare-Lab/dsh_kline/releases) [![MIT](https://img.shields.io/github/license/FTShare-Lab/dsh_kline)](LICENSE)

[功能展示](#功能展示) · [安装](#安装) · [开始使用](#开始使用) · [数据与适用范围](#数据与适用范围) · [文档](#文档)

> 本页对应 **v0.6.9**。正式安装包以 [Releases](https://github.com/FTShare-Lab/dsh_kline/releases) 为准；npm 发布与安装说明见[发布指南](docs/npm-release.md)。

## 功能展示

### 在主图中比较走势

把个股、指数或 ETF 的折线叠加在 K 线背景中，保留主标的的蜡烛图与指标。搜索添加、快捷选择常用指数，也可单独隐藏或移除对比线。

[![上证指数主图与沪深300、创业板指对比](docs/images/main-chart-comparison-v0.6.9.png)](docs/images/main-chart-comparison-v0.6.9.png)

*上证指数日 K，叠加沪深300与创业板指。对比线按图例中的共同基准归一化，比较累计涨跌幅，不直接比较价格，也不计算对比标的的指标。点击图片查看原图。*

### 从大盘进入个股

一页浏览 A／港／美主要指数、板块排行与龙虎榜，点击标的进入图表，继续研究行情、资讯和公司资料。

[![大盘概览：主要指数、板块排行与龙虎榜](docs/images/market-overview-v0.6.9.png)](docs/images/market-overview-v0.6.9.png)

### 自动绘图，也支持自己选点

「绘图」统一提供水平线、趋势线、平行通道、平台框、斐波那契、ABC 标注、双顶／底、头肩顶／底、平台突破／失效和基础九转。选择工具后绘制最近合格结果，也可切换候选或手动选点。关闭工具栏保留图形，通过「清除」移除。

[![微软日 K 平台箱体与上破确认日](docs/images/platform-breakout-msft-v0.6.9.png)](docs/images/platform-breakout-msft-v0.6.9.png)

*微软日 K：08/28—09/25 形成平台，10/06 确认上破。平台边界冻结后不被后续行情扩大。截图展示规则识别结果，不代表收益预测。*

以上为 **2026-11-11 的 DSH Web 实页截图**，保留原生 Retina 像素，以无损 PNG 保存；行情为当时快照。Codex 桌面版以应用卡片展示图表，计算规则共用，外观以实际宿主为准。

| 能力 | 使用方式 |
| --- | --- |
| 常用指标 | SMA、EMA、VOL、MACD、KDJ、RSI、BOLL、ATR、VWAP |
| 自然语言绘图 | 创建、修改、改色、改名或删除指定图形；与工具栏操作同一张图 |
| 点位与复盘 | 支撑／压力分析、自定义价位、区间涨跌与回撤统计 |
| 市场研究 | 大盘、板块、资讯、公司资料、龙虎榜；受来源和权限限制 |
| 自选管理 | 收藏、分组、排序、导入、批量打开；DSH 支持跨对话保留 |
| 技术函数 | 201 个 TA-Lib 函数可查询计算；其中 SMA／EMA／BBANDS 支持受控落图 |

## 安装

支持 macOS、Linux 和原生 Windows。首次启动需要联网准备依赖，可能耗时数分钟。

### DeepSeek Harness

先安装可用的 DSH Web 和 **Python 3.11+**，在插件市场搜索 `dsh_kline`，或执行：

```bash
dsh plugin --profile web add github:FTShare-Lab/dsh_kline
```

启用后点击右侧 **K** 打开工作台，或直接在对话中请求分析。Better Sidebar 是可选增强，普通侧栏不依赖它。

### Codex

先安装支持插件的 Codex、Git、**Node.js 22.19+** 和 **Python 3.11+**：

```bash
codex plugin marketplace add FTShare-Lab/dsh_kline --ref main
codex plugin add ft-kline@ftshare
```

重新打开 Codex，请求「打开招商银行日 K」。FTShare 是本项目维护的公开 GitHub 插件源，尚未上架官方公共插件目录。

| 宿主 | 交互图表与手动绘图 | 自然语言绘图 | 行情与结构化分析 |
| --- | --- | --- | --- |
| DSH Web | 支持 | 支持 | 支持 |
| Codex 桌面版 | 应用卡片内使用 | 支持 | 支持 |
| Codex CLI | 不提供 | 不落图 | 支持 |

更新、固定版本 ZIP、旧安装迁移、Key 配置与启动排障见[完整指南](docs/guide.md)。

## 开始使用

**用对话提出需求：**

```text
打开腾讯控股日 K，分析最近一个月的成交量、MACD 和 RSI。
在当前图画一条 31.2 元的蓝色支撑线，命名为“关键支撑”。
把关键支撑移到 30.8 元，其他图形不动。
找最近一个符合规则的双底并画出来，说明当前状态。
```

**在工作台操作：** 搜索标的 → 选择范围与周期 → 开启指标 → 在「绘图」选择工具并点击「绘图」。需要自行指定锚点时切换「手动选点」；「设置」调整参数。图形直接展示，无需另行保存。

「点位」分析支撑与压力；「对比」添加背景折线。窄画布放不下的工具进入行末菜单，收起面板不会删除图形。更多对话实例见[自然语言绘图演示](docs/drawing-examples.md)。

## 数据与适用范围

- **数据来源：** 默认可接入 FTShare，在「设置 → 数据源」配置并测试 Key。不配置 Key 时可尝试部分 A 股、港美股历史日 K 和指数备用行情，覆盖与可用性取决于公开源；分钟线、新闻和公司资料取决于相应权限。
- **形态与九转：** 当前仅支持已加载的 A／港／美股已收盘日线。ABC 是折线标注与候选辅助，不自动判定专业波浪；基础九转不包含完整 DeMARK 13 Countdown。
- **图形与状态：** 绘图使用当前图真实 K 线；数据来源不明、结果过期或活动视图有歧义时停止修改。绘图不保证跨服务重启恢复，鼠标拖拽与撤销暂不支持。
- **宿主差异：** DSH 自选为用户级持久化数据；Codex 图表、自选和应用内临时 Key 仅保存在当前连接内存中，不继承 DSH 配置。

行情可能延迟，技术分析用于研究和学习。数据口径见[无 Key 支持范围](docs/anonymous-market-support.md)和[港美股免费日线](docs/free-foreign-daily.md)。

## 文档

| 主题 | 入口 |
| --- | --- |
| 安装、更新、Key、故障排查 | [完整指南](docs/guide.md) |
| 自动绘图流程与扩展 | [共享绘图骨架](docs/automatic-drawing.md) |
| 形态定义与真实样本 | [规则](docs/price-pattern-rules-v1.md) · [样本](docs/price-pattern-samples-v1.md) |
| 技术函数 | [查询与绘图范围](docs/chart-functions.md) |
| 宿主与数据源接入 | [面板嵌入](docs/embedding.md) · [数据适配](docs/provider-adaptation.md) |
| 版本与验收 | [更新日志](CHANGELOG.md) · [v0.6.9 候选说明](docs/release-notes-v0.6.9.md) · [验收记录](docs/release-acceptance-v0.6.9.md) |

[MIT License](LICENSE) · [前端来源](PROVENANCE.md) · [GitHub Releases](https://github.com/FTShare-Lab/dsh_kline/releases)
