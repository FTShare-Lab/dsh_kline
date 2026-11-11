# 价格形态验收样本清单

每类价格形态冻结至少两项真实单日线正例、两项真实单日线负例，记录标的、交易所、来源、复权、起止日期、原始 OHLCV 摘要、规则版本、人工核对的锚点与状态。样本分类只检验本项目规则是否按因果时间执行，不表示交易绩效。任何真实样本未核实前不得标为已通过。

| 类别 | 正例目标 | 负例目标 | 核对重点 |
|---|---:|---:|---|
| 双顶 | 2 | 2 | 严格拐点、两顶差、回撤、颈线与两日确认 |
| 双底 | 2 | 2 | 严格拐点、两底差、反弹、颈线与两日确认 |
| 头肩顶 | 2 | 2 | 两肩、头高、颈线倾斜、先行趋势 |
| 头肩底 | 2 | 2 | 两肩、头低、颈线倾斜、先行趋势 |
| 平台 | 2 | 2 | 触边、漂移、冻结边界与突破不扩箱 |

真实样本另按数据供应商可复现的原始数据文件保存；合成边界样本仅用于单元测试，不能充当上述真实例证。

## 冻结样本（2026-11-09 获取）

原始日线与每例预期保存在 [`docs/fixtures/price-pattern-real-v1.json`](fixtures/price-pattern-real-v1.json)。来源为腾讯公开港美股日线、未复权、成交量为当日股数，时间戳为交易所当地 16:00。每例固定最近 300 根已获取数据；这些样本只检验结构与状态，不能证明预测收益。

| 类别 | 结果 | 标的／前缀根数 | 首次可知／未通过原因 | 状态 |
|---|---|---|---|---|
| `double_top` | 正例 | `AAPL.US@500` | 2026-10-15 | structurally_invalid |
| `double_top` | 正例 | `MSFT.US@500` | 2026-11-02 | structurally_invalid |
| `double_bottom` | 正例 | `MSFT.US@500` | 2026-07-27 | price_confirmed |
| `double_bottom` | 正例 | `00700.HK@500` | 2026-06-30 | expired |
| `head_shoulders_top` | 正例 | `BA.US@350` | 2025-08-19 | candidate |
| `head_shoulders_top` | 正例 | `02318.HK@500` | 2025-12-04 | structurally_invalid |
| `head_shoulders_bottom` | 正例 | `PDD.US@500` | 2026-01-05 | breakout_failed |
| `head_shoulders_bottom` | 正例 | `00002.HK@350` | 2025-01-27 | structurally_invalid |
| `platform` | 正例 | `AAPL.US@500` | 2026-06-22 | breakout_failed |
| `platform` | 正例 | `MSFT.US@500` | 2026-09-25 | price_confirmed |
| `double_top` | 负例 | `BIDU.US@650` | atr_unavailable:2、insufficient_prior_trend:2、double_geometry_rejected:8、prior_trend_below_2_atr:19 | 无候选 |
| `double_bottom` | 负例 | `BIDU.US@650` | atr_unavailable:2、insufficient_prior_trend:2、prior_trend_below_2_atr:15、double_geometry_rejected:12 | 无候选 |
| `head_shoulders_top` | 负例 | `BIDU.US@650` | atr_unavailable:2、insufficient_prior_trend:2、head_shoulders_geometry_rejected:8、prior_trend_below_2_atr:18 | 无候选 |
| `head_shoulders_bottom` | 负例 | `BIDU.US@650` | atr_unavailable:2、insufficient_prior_trend:2、prior_trend_below_2_atr:14、head_shoulders_geometry_rejected:12 | 无候选 |
| `platform` | 负例 | `BIDU.US@650` | atr_unavailable:2、platform_non_alternating_touches:1 | 无候选 |
| `double_top` | 负例 | `INTC.US@650` | atr_unavailable:2、insufficient_prior_trend:2、double_geometry_rejected:13、prior_trend_below_2_atr:16 | 无候选 |
| `double_bottom` | 负例 | `INTC.US@650` | atr_unavailable:2、insufficient_prior_trend:2、prior_trend_below_2_atr:25、double_geometry_rejected:4 | 无候选 |
| `head_shoulders_top` | 负例 | `INTC.US@650` | atr_unavailable:2、insufficient_prior_trend:2、head_shoulders_geometry_rejected:11、prior_trend_below_2_atr:17 | 无候选 |
| `head_shoulders_bottom` | 负例 | `INTC.US@650` | atr_unavailable:2、insufficient_prior_trend:2、prior_trend_below_2_atr:24、head_shoulders_geometry_rejected:4 | 无候选 |
| `platform` | 负例 | `INTC.US@650` | atr_unavailable:2 | 无候选 |

正例锚点已按冻结 OHLCV 逐例绘图人工复核；自动测试另独立核对严格拐点、首次可知时点、状态及事件日期。平台新例已复核收盘轨迹与冻结边界，但仍只是规则候选，不代表所有交易者都会认作经典横盘。负例只表示该冻结窗口未满足本项目规则，不证明图表中绝无主观形态。
