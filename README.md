# dsh_kline

Connect [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
to the [ft-kline-view](https://github.com/FTShare-Lab/ft-kline-view) MCP
server.

The default integration gives a DeepSeek agent a small, chart-focused tool
surface. The agent can retrieve FTShare-backed candles through
`ft-kline-view.fetch_candles`, calculate deterministic indicators, and invoke
the K-line renderer without separately orchestrating the full FTShare-MCP tool
catalog.

## Status

This repository targets DeepSeek Harness `0.1.0-rc.6`, which is a developer
preview and may introduce breaking changes.

Verified on 2026-08-15 with:

| Component | Verified version |
| --- | --- |
| DeepSeek Harness | `0.1.0-rc.6` |
| ft-kline-view | `0.1.55` |
| Node.js | `26.7.0` |
| pnpm | `11.7.0` |
| Python | `3.12.13` |
| MCP Python SDK | `1.28.1` |
| FTShare Python distribution | `0.1.1` |

The current dsh MCP client bridges MCP tools, but it does not render the
`ui://ft-kline-view/...` MCP App resource. `draw_kline` succeeds and returns
structured chart commands; the interactive chart still requires an
MCP Apps-capable host or a future dsh UI adapter.

## Architecture

Default path:

```text
DeepSeek model
  -> DeepSeek Harness
  -> @deepseek-ai/dsh-mcp-client
  -> ft-kline-view over stdio MCP
  -> FTShare Python SDK through fetch_candles
  -> calc_metrics / draw_kline
```

An opt-in profile can also expose the public FTShare-MCP server for broader
finance-data workflows. It is not required for the default K-line flow.

## Prerequisites

- Node.js `>=22.19.0`
- pnpm `11.7.0`
- a local `ft-kline-view` checkout
- a Python environment that can start `ft-kline-view`
- the optional FTShare Python SDK installed in that same Python environment
- a DeepSeek API key for natural-language agent tasks

Tool discovery and configuration checks do not require a DeepSeek API key.

## Install

Clone this repository next to `ft-kline-view` when possible:

```bash
git clone https://github.com/FTShare-Lab/dsh_kline.git
cd dsh_kline
pnpm install
```

Set the ft-kline-view checkout and interpreter explicitly:

```bash
export FT_KLINE_VIEW_ROOT="$(cd ../ft-kline-view && pwd)"
export FT_KLINE_VIEW_PYTHON=/absolute/path/to/ft-kline-view-python
```

The verified local interpreter was:

```text
/opt/homebrew/Caskroom/miniforge/base/envs/ft-kline-view/bin/python
```

Verify that the selected interpreter can import the server and FTShare SDK:

```bash
"$FT_KLINE_VIEW_PYTHON" "$FT_KLINE_VIEW_ROOT/scripts/doctor.py"
```

## Configure DeepSeek

Natural-language agent tasks require `DEEPSEEK_API_KEY`. Provide it through
your local environment or the dsh credential store. Never commit it to this
repository.

```bash
export DEEPSEEK_API_KEY=your_key_here
```

The included `.env.example` documents supported environment variables, but
dsh does not require a repository-local secret file.

## Verify

Discover the local MCP tools without calling a model or live market endpoint:

```bash
pnpm smoke:mcp
```

The smoke test must discover at least:

```text
fetch_candles
calc_metrics
draw_kline
doctor_view
```

Inspect the composed dsh profile:

```bash
pnpm dsh:version
pnpm dsh:dump
```

The default dump should contain one MCP server named `ft-kline-view` and no
`mcp-ftshare` entry.

## Run

Start the dsh Web UI:

```bash
pnpm dsh:web
```

The default address is `http://127.0.0.1:3080`.

Run one headless agent task:

```bash
pnpm exec dsh --profile headless \
  --patch ./config/ft-kline-view.patch.yml \
  "Use ft-kline-view tools to fetch 60 daily candles for 00700.HK, calculate RSI, and invoke draw_kline with MA, volume, and MACD."
```

The expected tool sequence is:

```text
mcp__ft-kline-view__fetch_candles
mcp__ft-kline-view__calc_metrics
mcp__ft-kline-view__draw_kline
```

## Optional FTShare-MCP Profile

Use the dual-MCP profile only when the agent needs FTShare tools outside the
chart server's built-in data workflow:

```bash
pnpm dsh:dump:ftshare
pnpm dsh:web:ftshare
```

This profile connects to the public Streamable HTTP endpoint:

```text
https://market.ft.tech/gateway/mcp
```

The default profile intentionally omits this catalog to reduce tool-schema
overhead and model routing ambiguity.

## Verified Behavior

The local release checks completed successfully:

- dsh discovered all 15 ft-kline-view tools;
- DeepSeek headless mode autonomously invoked `fetch_candles`,
  `calc_metrics`, and `draw_kline` through the default profile;
- the SDK path returned 70 recent `00700.HK` daily candles;
- A-share daily, forward-adjusted daily, and 5-minute candles succeeded;
- U.S. daily candles succeeded;
- `draw_kline` returned `ui://ft-kline-view/kline-v0.1.55`;
- ft-kline-view passed 98 tests and its local doctor/probe checks.

Current provider boundary: the installed FTShare SDK has no verified Hong Kong
minute-candle endpoint. `ft-kline-view` returns a structured
`intraday_provider_unavailable` error instead of treating that capability gap
as empty market data.

## Troubleshooting

### `ftshare_not_installed`

Install the FTShare Python SDK into the exact interpreter configured by
`FT_KLINE_VIEW_PYTHON`, then rerun:

```bash
"$FT_KLINE_VIEW_PYTHON" "$FT_KLINE_VIEW_ROOT/scripts/doctor.py"
```

### MCP server exits during startup

Check that both paths are absolute and that the Python interpreter is
executable:

```bash
test -f "$FT_KLINE_VIEW_ROOT/server.py"
test -x "$FT_KLINE_VIEW_PYTHON"
pnpm smoke:mcp
```

### Native Node module or macOS signing errors

Use a regular Homebrew Node installation rather than an application-bundled
Node runtime. The verified local runtime is Homebrew Node `26.7.0`.

### `draw_kline` succeeds but no interactive chart appears

This is an expected limitation of the current dsh MCP client. It bridges MCP
tools but does not yet consume and render MCP App resources.

### Hong Kong minute candles fail

Use daily-or-larger Hong Kong candles, or provide verified minute rows from
another data provider. The default SDK path fails explicitly for this
unsupported capability.

## Repository Layout

```text
config/
  ft-kline-view.patch.yml                 default, ft-kline-view only
  ft-kline-view-with-ftshare.patch.yml    optional dual-MCP profile
scripts/
  run-ft-kline-view.sh                    stdio server launcher
  smoke-mcp.sh                            keyless discovery entrypoint
  smoke-mcp.py                            MCP protocol smoke test
docs/
  ARCHITECTURE.md                         integration boundaries and risks
```

## Security

- Never commit `DEEPSEEK_API_KEY` or other credentials.
- Keep local `.env` files ignored.
- Do not publish dsh credential files or session logs.
- Rotate any key that has been pasted into chat, issues, or terminal logs.

## License

MIT. See [LICENSE](LICENSE).
