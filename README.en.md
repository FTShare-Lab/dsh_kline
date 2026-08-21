# dsh_kline

[简体中文](README.md) | English

An interactive K-line analysis plugin for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness). Ask in natural language to explore prices, technical indicators, news, and company fundamentals in a sidebar chart.

## Preview

![K-line chart and key levels](docs/images/kline-support.png)

![Range statistics](docs/images/kline-range-stats.png)

![News and company overview](docs/images/kline-news.png)

## Features

- **Multi-market quotes**: supports Hong Kong, US, and mainland China stocks. Search by company name, ticker, or code.
- **Search and watchlists**: search symbols, save the current symbol, and organize watchlists into groups with quote refresh, sorting, and batch opening.
- **Interactive charts**: daily, weekly, monthly, quarterly, yearly, and intraday K-lines with zoom, pan, crosshair, and responsive layout.
- **Technical indicators**: switch K-line, volume, MA, MACD, KDJ, RSI, BOLL, ATR, and VWAP as needed.
- **Key levels**: when requested, identifies and annotates support, resistance, and touch counts.
- **Range statistics**: click a start and end candle to inspect return, volatility, maximum drawdown, candle count, and trading activity.
- **Context**: browse stock news, company overview, financials, and shareholder information.

## How To Use

Enable `dsh_kline` in [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), then ask as you would an analyst. You do not need to memorize ticker formats.

- `Show the K-line chart for Zijin Mining`
- `Show Tencent's daily chart and mark support and resistance`
- `Analyze NVIDIA's volume, MACD, and RSI over the past month`
- `Show the latest news and fundamentals for this company`
- `Switch to the weekly chart and assess the trend`

After the analysis, use the sidebar to switch timeframes and indicators or explore news and company information. To view range statistics, click two candles in sequence.
Use the search box for a company name or ticker, then select the star to add it to a watchlist. Watchlists support groups, sorting, and batch opening, and are stored locally in the current browser.

## MCP Tools

| Tool | Purpose |
| --- | --- |
| `analyze_kline` | Main entry point. Returns quotes, indicators, chart data, and optional support/resistance analysis in one call. |
| `fetch_candles` | Retrieves normalized OHLCV candle data. |
| `calc_metrics` | Calculates technical and statistical metrics from OHLCV data. |
| `health` | Checks service and data-adapter health. |

Most requests only need `analyze_kline`. The other tools are available for raw data, standalone calculations, and health checks.

## Data Sources

[FTShare Python SDK](https://github.com/FTShare-Lab/FTShare-python-sdk) is the recommended default. The plugin is optimized for its Hong Kong, US, and mainland China market data and normalizes quotes into a standard OHLCV structure, so you can also connect your own licensed data source.

## Data And Usage Notes

- Quotes may be delayed, market-closed, or affected by upstream availability.
- Support, resistance, and indicators are historical technical analysis only and are not investment advice.
- Commercial, high-frequency, or latency-sensitive use should rely on properly licensed data with an appropriate service level.

## Updates

See [Releases](https://github.com/FTShare-Lab/dsh_kline/releases) for the changelog. The sidebar displays an update notice when a newer stable release is available. Source users can update to the latest version and restart Harness.

## License

Released under the [MIT License](LICENSE). Frontend provenance is documented in [PROVENANCE.md](PROVENANCE.md).
