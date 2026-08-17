# dsh_kline

Standalone K-line MCP for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness),
powered by the FTShare Python SDK.

`dsh_kline` is one repository and one MCP process. It contains its own FTShare
adapter, OHLCV normalization, deterministic indicator calculations, tests, and
DeepSeek Harness profile. It does not call or require another MCP server.

## Status

Developer preview. The repository pins DeepSeek Harness `0.1.0-rc.6`, which may
introduce breaking changes.

Verified locally on 2026-08-16 with:

| Component | Version |
| --- | --- |
| DeepSeek Harness | `0.1.0-rc.6` |
| Node.js | `26.7.0` |
| pnpm | `11.7.0` |
| Python | `3.12.13` |
| MCP Python SDK | `1.28.1` |
| FTShare Python distribution | `0.1.1` |

## Architecture

```text
DeepSeek model
  -> DeepSeek Harness
  -> @deepseek-ai/dsh-mcp-client
  -> this repository's server.py over stdio
       -> FTShare Python SDK
       -> canonical OHLCV normalization
       -> deterministic indicators
       -> compact model-facing summary + structured chart data
       -> loopback chart service with an expiring chart URL
```

There is no FTShare-MCP connection and no external K-line MCP process.

## Tools

| Tool | Purpose |
| --- | --- |
| `analyze_kline` | Preferred single call: fetch, calculate indicators, and build chart data from one FTShare row set |
| `fetch_candles` | Fetch canonical OHLCV rows directly through the FTShare SDK |
| `calc_metrics` | Calculate deterministic summaries for caller-supplied canonical rows |
| `health` | Report Python and FTShare SDK readiness |

Use `analyze_kline` for normal DeepSeek tasks. It remains one MCP call and now
returns both `chart.rows` and a `chart_url`. Open the URL from the MCP text
result to view the interactive chart in a normal browser; the chart service is
owned by the same dsh process and listens on loopback only.

## Prerequisites

- Node.js `>=22.19.0`
- pnpm `11.7.0`
- Python `>=3.10`
- Git access to the FTShare Python SDK repository
- a DeepSeek API key for natural-language agent tasks

Tool discovery, unit tests, and MCP protocol checks do not require a DeepSeek
API key. A live market-data test requires network access to FTShare.

## Install

```bash
git clone https://github.com/FTShare-Lab/dsh_kline.git
cd dsh_kline
pnpm install --frozen-lockfile
./scripts/bootstrap.sh
```

`bootstrap.sh` creates `.venv` and installs the pinned MCP runtime plus a pinned
FTShare SDK source archive. No sibling repository or Git credential is needed.

To use a different interpreter, set:

```bash
export DSH_KLINE_PYTHON=/absolute/path/to/python
```

The interpreter must have `mcp`, `pydantic`, and `ftshare` installed.

## Verify

```bash
pnpm dsh:version
pnpm smoke:mcp
pnpm smoke:markets
.venv/bin/python -m pytest -q
pnpm smoke:live
```

The MCP smoke test must discover exactly:

```text
analyze_kline
calc_metrics
fetch_candles
health
```

Inspect the composed dsh profile:

```bash
pnpm dsh:dump
```

It should contain one MCP server named `dsh-kline` and no external MCP URL.

`pnpm smoke:live` calls `analyze_kline` through the real stdio protocol and
requires FTShare data, exactly 60 bars, RSI, MACD, and a chart URL.

`pnpm smoke:markets` is the live provider regression for `00700.HK`, `NVDA.US`,
and `600519.XSHG`, followed by malformed-symbol and unsupported-interval checks.

## Configure DeepSeek

Start the Web UI, open **Settings -> Models**, enter a DeepSeek API key, and
save it. The key belongs in dsh's local credential store, never in Git.

You may also provide the key through your local environment:

```bash
export DEEPSEEK_API_KEY=your_key_here
```

## Run

```bash
pnpm dsh:web
```

Open [http://127.0.0.1:3080](http://127.0.0.1:3080), choose the `dsh_kline`
workspace, and send:

```text
Use dsh-kline analyze_kline exactly once for 00700.HK with interval day,
limit 60, indicators [ma, vol, macd, rsi], and metrics [rsi]. Report the
source, latest close, RSI, and MACD values in Chinese. Do not use another
provider or reconstruct rows.
```

The expected tool is:

```text
mcp__dsh-kline__analyze_kline
```

## Data Contract

Canonical rows use Unix seconds and this shape:

```json
{
  "time": 1786636800,
  "open": 436.0,
  "high": 445.0,
  "low": 436.0,
  "close": 440.0,
  "volume": 30601060.0
}
```

Supported chart indicators are MA, volume MA, MACD, KDJ, BOLL, RSI, ATR, and VWAP.
Summary metrics additionally include maximum drawdown, support/resistance,
MA crosses, volume breakout, Bollinger state, RSI, and ATR.

## Verified Behavior

The standalone release checks completed successfully:

- 64 provider, normalization, indicator, chart-session, frontend-contract, and MCP server tests passed;
- stdio discovery exposed exactly four local tools;
- the chart payload contains candles plus MA, volume, MACD, RSI, BOLL, ATR, and
  VWAP series without an MCP Apps handshake;
- the standalone chart fetches missing long-history rows on range expansion;
  the real A-share 5Y view was verified back to August 2021;
- a clean directory with no `ft-kline-view` sibling installed all Node and
  Python dependencies from pinned inputs;
- the clean directory completed a real FTShare `00700.HK` analysis with 60
  bars, close `440.0`, RSI(14) `40.444`, MACD DIF `0.597986`, DEA `4.929754`,
  and histogram `-8.663534`;
- the dsh Web UI called only `mcp__dsh-kline__analyze_kline` and produced the
  corresponding Chinese summary without Bash, Web, or another provider.

## Current Boundaries

- DeepSeek Harness `0.1.0-rc.6` bridges MCP tools but does not render MCP Apps;
  `dsh_kline` therefore serves a normal browser chart URL from the MCP process.
- Chart sessions are in-memory, expire after six hours, and are reachable only
  on `127.0.0.1` by default. Port `8765` is preferred; if it is occupied, the
  service chooses an available loopback port and returns the exact URL.
- Daily-or-larger generic FTShare history is fetched in pages no wider than 360
  days, which stays inside the provider's 12-natural-month request limit while
  supporting the chart's 1Y and 5Y ranges.
- The installed FTShare SDK has no verified Hong Kong minute-candle endpoint;
  use daily-or-larger Hong Kong intervals.
- A-share broad-index K-lines fail closed where the installed SDK has no
  verified index-history endpoint.

## Repository Layout

```text
server.py                 standalone MCP server
chart_service.py          loopback chart session and HTTP service
core/                     OHLCV normalization and indicators
tools/                    FTShare adapter, calculation wrapper, and chart payloads
view/                     vendored interactive K-line frontend
config/dsh-kline.patch.yml
scripts/bootstrap.sh      Python environment setup
scripts/run-dsh-kline.sh  stdio launcher used by dsh
scripts/smoke-mcp.py      MCP protocol discovery check
scripts/smoke-markets.py  live HK/US/CN/error regression
tests/                    provider, indicator, and server tests
```

## Security

- Never commit API keys, credential files, dsh sessions, or generated market data.
- Rotate any key pasted into chat, issues, or terminal logs.
- `DSH_KLINE_CACHE_DIR` may contain provider metadata; do not publish it.
- The chart service binds to loopback and keeps chart rows in memory only.

## Provenance

The deterministic OHLCV and indicator implementation was adapted from the
MIT-licensed `ft-kline-view` codebase. See [docs/PROVENANCE.md](docs/PROVENANCE.md).
The interactive frontend and vendored chart library were copied into `view/`
for this repository's standalone browser service. `ft-kline-view` is source
provenance only and is not a runtime dependency.

## License

MIT. See [LICENSE](LICENSE).
