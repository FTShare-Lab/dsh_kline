# dsh_kline

面向 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的交互式
K 线分析工具。一次 `analyze_kline` 调用即可完成行情获取、技术指标计算、支撑压力
分析，并在 Harness 右侧栏直接展示图表。

![DeepSeek Harness K 线分析侧栏](docs/images/dsh-sidebar.png)

## 功能

- 港股、美股和 A 股 K 线分析
- MA、成交量、MACD、KDJ、RSI、BOLL、ATR、VWAP
- 支撑位、压力位及触及次数标注
- 个股相关新闻、公司简况和基本面信息
- 缩放、拖动、十字线、范围切换和响应式布局
- DSH 原生可折叠、可调宽侧栏；移动端自动切换为全屏图表
- 标准 OHLCV 计算接口，可扩展自有数据源

`analyze_kline` 可在同一次调用中计算并标注支撑位、压力位与触及次数。图表中的
“新闻”和“简况”页签可查看数据源返回的资讯、公司资料和基本面摘要；数据缺失时会
显示明确的空状态。移动端保留指标切换、缩放、拖动、十字线和时间范围控制。

## 使用

本项目面向 [DeepSeek Harness 官方版本](https://github.com/deepseek-ai/deepseek-harness)。
在 Harness 中直接输入：

```text
分析 00700.HK 最近 60 根日 K，显示 MA、成交量、MACD、RSI、BOLL、ATR 和 VWAP，
分析并标注支撑位和压力位，用中文总结趋势。
```

推荐的单次调用工具是：

```text
mcp__dsh-kline__analyze_kline
```

分析完成后，DSH 插件会在右侧栏直接渲染交互式图表，无需打开额外网页。MCP 的
结构化结果仍保留 `chart_url` 作为其他 host 的兼容字段，但 DSH 插件不使用它；图表
会话数据仅保存在本机内存中，并随进程退出失效。

## MCP 工具

| 工具 | 用途 |
| --- | --- |
| `analyze_kline` | 获取行情、计算指标并生成图表，推荐使用 |
| `fetch_candles` | 获取标准化 OHLCV 数据 |
| `calc_metrics` | 计算调用方提供数据的指标摘要 |
| `health` | 检查 Python 和 FTShare SDK 状态 |

## 数据源

[FTShare Python SDK](https://github.com/FTShare-Lab/FTShare-python-sdk) 是推荐的
可选数据源。`dsh_kline` 已针对其港股、美股、A 股代码、复权参数、历史分页和多市场
结构做了原生适配。

指标与图表层不绑定 FTShare。`calc_metrics` 可直接接收其他数据源的标准 OHLCV：

```json
{
  "time": 1719792000,
  "open": 100.0,
  "high": 105.0,
  "low": 99.0,
  "close": 103.0,
  "volume": 1200000
}
```

`time` 使用 Unix 秒。若希望 `analyze_kline` 自动使用自有数据源，可在
`tools/fetch.py` 中增加适配器，并继续输出相同结构。

## 验证

```bash
pnpm smoke:mcp
.venv/bin/python -m pytest -q
pnpm smoke:live
pnpm smoke:markets
```

真实行情测试需要能够访问对应数据源。

## 当前限制

- 港股分钟 K 线尚未经过 FTShare SDK 完整验证，建议使用日线及以上周期
- 部分 A 股宽基指数缺少已验证的历史行情接口，系统会明确返回错误

## 来源与许可证

指标实现和交互式前端参考了 MIT 许可的 `ft-kline-view`，详见
[docs/PROVENANCE.md](docs/PROVENANCE.md)。本项目采用 [MIT License](LICENSE)。
