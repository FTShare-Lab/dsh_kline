# Nonconvex K-Line Assistant / FT K-Line

[简体中文](README.md) | English

[![Cross-platform tests](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/install.yml/badge.svg?branch=main)](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/install.yml) [![Latest release](https://img.shields.io/github/v/release/FTShare-Lab/dsh_kline?label=Release)](https://github.com/FTShare-Lab/dsh_kline/releases) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](#get-started-with-dsh) [![MIT License](https://img.shields.io/github/license/FTShare-Lab/dsh_kline)](LICENSE)

**Supports DeepSeek Harness and Codex.** The DSH plugin is `dsh_kline`; the Codex plugin is `ft-kline`. Both support natural-language K-line analysis and guarded drawing in their desktop chart. Codex in the desktop app has an interactive chart; Codex CLI returns market data, indicators, and structured analysis without an interactive chart.

> Quotes and technical analysis are for research and education only, not investment advice.

[Features](#what-it-helps-you-do) · [Use with Codex](#use-with-codex) · [Install DSH](#get-started-with-dsh) · [Drawing preview](#preview) · [Drawing tools](#drawing-through-chat-and-the-workbench) · [Data sources](#quotes-and-data-sources)

| Environment | Chart and manual drawing | Natural-language drawing | Market data, indicators, analysis |
| --- | --- | --- | --- |
| DeepSeek Harness Web | Yes | Yes | Yes |
| Codex desktop | Yes, in an app card | Yes, after opening the current chart session | Yes |
| Codex CLI | No interactive chart | No chart drawing | Yes, as structured results |

The Codex plugin is currently **v0.6.6**, available through this repository's public **FTShare GitHub marketplace**. It is not listed in the official public plugin directory. DSH retains its existing installation path. The DSH screenshots and persistent-watchlist description below apply to DSH Web; see [Codex setup and differences](#use-with-codex) for the separate plugin.

## What it helps you do

- **Start with a sentence**: ask for a chart, a trend read, or an indicator analysis in natural language.
- **Explore on your own**: open the K-line workspace, search a name or ticker, and switch among daily, weekly, monthly, quarterly, yearly, and available intraday views.
- **Read trend and momentum**: use MA, volume, MACD, KDJ, RSI, BOLL, ATR, and VWAP.
- **Put your analysis on the chart**: create horizontal/trend lines, parallel channels, range boxes, Fibonacci retracements, and ABC polylines by chat or point selection. Preview first; save only when the result looks right.
- **Explore TA-Lib**: search and run all 201 TA-Lib 0.8.2 functions read-only on the loaded chart. Only selected SMA, EMA, and BBANDS results are directly drawable in this release; the other functions are not advertised as chart objects.
- **Find price areas**: identify support and resistance, or draw and save your own levels and notes.
- **Compare and review**: overlay indices or symbols, then select a period to inspect return, range, drawdown, and activity.
- **Add context**: use Market, Sectors, News, Company, and Dragon & Tiger List views for indices, sector rankings, capital-flow events, news, company profiles, fundamentals, and ownership data.
- **Build a watchlist**: save symbols, create or rename groups, sort, import, and open several at once. Watchlists stay in your current browser.

## Preview

Live natural-language example: DeepSeek screened the watchlist for an ABC **candidate** in Wolong Electric, checked the four 0/A/B/C anchors against candles, and used the plugin to draw them. This unedited full-page capture shows the conversation, application result, and visible chart together. The host interprets the pattern; a rules-based candidate is not a verified Elliott-wave conclusion.

![Full DSH Web page: DeepSeek checks four ABC candidate anchors for Wolong Electric while the daily chart displays the corresponding polyline and labels](docs/images/natural-language-abc-wolong-2026-10-27.png)

In the same chart, a follow-up natural-language request adds a descending channel. DeepSeek checks its three-anchor geometry and price deviations; the plugin applies it as a separate object while preserving the ABC labels. The lines are visible, but their trading relevance still requires independent judgment.

![Full DSH Web page: DeepSeek explains the descending channel's anchors and deviations while the daily chart shows both the channel and ABC labels](docs/images/natural-language-descending-channel-wolong-2026-10-27.png)

## Use with Codex

The Codex plugin is `ft-kline`, available from the **FTShare** marketplace (`ftshare`). Add the GitHub source once, install the plugin, and use the same source for updates. No ZIP download or source build is required. This is a project-maintained marketplace, not a listing in OpenAI's official public plugin directory.

### Install and verify

1. Install Git, Node.js **22.19+**, Python **3.11+**, and a Codex client supporting plugins. Enable Python Launcher on Windows; Git Bash and WSL are unnecessary.
2. Run these commands. The first adds the source and follows CI-validated `main`; the second installs and enables the plugin:

```bash
codex plugin marketplace add FTShare-Lab/dsh_kline --ref main
codex plugin add ft-kline@ftshare
```

3. Reopen Codex and ask for a daily chart and its data source. During first-time preparation, ask to check FT K-Line runtime status. Desktop users can expand the chart card, search symbols and use the drawing workbench; CLI returns data and analysis.

After adding the source, you can also reopen the desktop app and select **FTShare → FT K-Line** in the Plugins page. Inspect the source and available plugins with:

```bash
codex plugin marketplace list
codex plugin list --marketplace ftshare --available --json
```

### Updates and migration

Refresh the existing source, install its current plugin version, then reopen Codex:

```bash
codex plugin marketplace upgrade ftshare
codex plugin add ft-kline@ftshare
```

If you previously installed `ft-kline@ftshare-local` from a ZIP, disable that old installation in the Plugins page before enabling `ft-kline@ftshare`, so two sources do not expose duplicate tools. The GitHub source needs access to GitHub; first launch also downloads Python dependencies.

### Install a fixed release ZIP

To stay on a fixed release, download `ft-kline-v0.6.6.zip` and its SHA-256 from the [v0.6.6 release](https://github.com/FTShare-Lab/dsh_kline/releases/tag/v0.6.6), verify the hash, and extract to a permanent folder. Replace the quoted path below with that absolute folder path:

```bash
codex plugin marketplace add "/absolute/path/ft-kline-v0.6.6"
codex plugin add ft-kline@ftshare-local
```

Reopen Codex to use it. The ZIP source is `ftshare-local`, separate from the public GitHub source `ftshare`. DSH retains its `dsh-kline-v0.6.6.tgz` package and the installation method below.

### First launch and runtime modes

First use finds Python and installs dependencies automatically, which can take several minutes. The Node entry completes the handshake and exposes the **complete catalog on the first tools/list**, plus preloadable chart resources. It does not depend on catalog-change notifications. Check `ft_kline_runtime_status` while preparing. Ordinary calls wait briefly, then return `runtime_preparing` if necessary; rejected edits never execute later. Once ready, retry the original request without refreshing tools or reopening the chat. Logs are in `~/.cache/ft-kline/bootstrap.log` or `%LOCALAPPDATA%\ft-kline\bootstrap.log` on Windows.

Restart Codex once after upgrading from v0.6.1 to replace its previous status-only startup snapshot. Then request a daily chart directly. Runtime readiness, data delivery and a visibly rendered native chart are separate acceptance checks; a fallback visualization does not satisfy native-plugin acceptance.

Default `auto` mode checks the host's declared MCP Apps HTML capability. Supporting hosts get interactive charts and guarded edits; other hosts, including CLI, get structured data and analysis without chart resources or drawing writes. Advanced integrations can explicitly set `FT_KLINE_CLIENT=desktop` or `cli`.

Chart edits follow `get_chart_context → prepare_chart_edit → apply_chart_edit → get_chart_edit_status`. Server commits, UI receipts and visual verification remain separate.

### Reuse an FTShare key

Symbol discovery and quote access are separate. v0.6.6 improves public HK/US directories, common Chinese aliases and error messages without requiring a key. See the [key-less capability and evaluation notes](docs/anonymous-market-support.md); fixed release archives retain their release's behavior.

Credential priority is: **plugin-process `FTSHARE_API_KEY` → explicitly configured `FTSHARE_API_KEY_FILE` → temporary App-session key**. An export in an unrelated terminal is not automatically visible to the desktop app.

The selected file is reread before provider requests and is never modified or deleted by the plugin. Use JSON `{"version":1,"api_key":"your key"}`. macOS/Linux require owner-only permissions (`chmod 600`); symbolic links are rejected. Status reports only `environment`, `external_file`, `session` or `none`, never the key or path. Codex does not discover DSH credentials or scan `.env`, shell profiles, keychains or other apps; sharing a file requires explicitly configuring its path.

Without a key, supported A-share daily-history and index fallbacks remain available. Chart state, results, watchlists and App-entered keys stay in connection memory until the last view closes, disconnect, or 30 idle minutes. User-managed environment/file credentials are not deleted when a chart closes. DSH persistent watchlists are not inherited.

See the [v0.6.6 release notes](docs/release-notes-v0.6.6.md) and [acceptance checklist](docs/release-acceptance-v0.6.6.md) for verification and remaining manual desktop checks.

## Get started with DSH

v0.6.5 adds an optional chart-panel mounting interface for host developers, with external symbol and theme updates. Canvas and paper-trading panels require host integration; see the [embedding contract](docs/embedding.md).

### 1. Install and enable

Find `dsh_kline` in the DeepSeek Harness plugin marketplace. If the catalog has not refreshed yet, install directly from GitHub:

```bash
dsh plugin --profile web add github:FTShare-Lab/dsh_kline
```

The first launch prepares its runtime automatically. Later, update from the marketplace or Settings when a new version is available.

The plugin supports macOS, Linux, and native Windows. Install a working DSH Web host and Python 3.11 or newer first. On Windows, use the [python.org installer](https://www.python.org/downloads/windows/) with the Python Launcher enabled. Git Bash and WSL are not required. First-launch details are stored in `dsh_kline/bootstrap.log` under the user cache directory; the Windows default is `%LOCALAPPDATA%\dsh_kline\bootstrap.log`.

![Install and update dsh_kline from the plugin marketplace](docs/images/dsh-market.png)

### 2. Choose either entry point

**Ask AI** in a conversation, for example:

- `Show the K-line chart for Zijin Mining and its trend over the last month`
- `Show Tencent's daily chart and mark support and resistance`
- `Analyze NVIDIA's volume, MACD, and RSI over the past month`
- `What recent news and fundamentals should I know about this company?`
- `Draw a blue level at 1300 on the current chart, then change that object to green`
- `Propose three anchors for a descending channel; explain the deviation and wait for my confirmation`
- `Screen my watchlist for ABC candidates; verify one symbol's 0/A/B/C pivots on its daily chart before drawing, and tell me whether C is confirmed`

**Open the workspace directly**: click the K button on the right, or choose **非凸 K 线助手 / dsh_kline** from the `+` menu where workspace Tabs are available. Search by name or ticker; exchange suffixes are not required.

Both entry points can operate on the same new drawing objects in the active chart. In the chart toolbar, **Draw** opens the drawing workbench: choose a tool, click candles or enter parameters, preview, then confirm. Conversations retain separate chart states; watchlists remain user-level data.

## Using the chart

1. Search for a company or ticker at the top.
2. Pick a time range and candle timeframe. Intraday availability depends on the market and data entitlement.
3. Enable the indicators you need, then pan, zoom, or use the crosshair for detail.
4. Select **Key levels** for support and resistance, or **Draw** to choose a drawing tool, pick anchors or enter parameters, and save the preview. Manage your own price lines under **Levels**.
5. Click two candles in sequence to review return, range, drawdown, and trading activity for that interval.
6. Select the star beside a symbol to add it to a watchlist.

Where a **UI** menu is available, choose Automatic, Classic sidebar, or workspace Tab. Automatic uses the best interface your current Harness supports; when Tabs are unavailable, the regular K-line sidebar continues to work.

### Sidebar compatibility

DeepSeek Harness provides its own right sidebar, so **Better Sidebar is not required** to open the K-line sidebar. When a compatible Better Sidebar is installed, the plugin can also open the chart as a workspace Tab. This is an optional UI integration, not a requirement for quotes, indicators, or drawing. Use **UI** to choose Automatic, sidebar, or Tab; Automatic selects from the interface capabilities exposed by the current host. Installing Better Sidebar alone does not mean every version and layout has been validated.

## Quotes and data sources

FTShare is the default optional source. After you configure an API key, the plugin exposes the quote, intraday, news, and company-data capabilities available to your account. Availability differs by market and plan.

Only unadjusted (`none`) single-session one-minute requests for regular A-share stocks prefer FTShare's raw realtime feed. Forward/backward requests (including qfq/hfq) use history with the matching `adjust_kind`; failure never silently falls back to raw realtime rows. Indices, ETFs and multi-session history retain their applicable endpoints. Full-session returns and adjustment-isolated caching are unchanged; routing is not independent verification of vendor-adjusted prices.
Explicit source minute size survives ingestion, local redraw and workspace state. Missing/invalid metadata stays unknown; it is not inferred from timestamp spacing, UI labels or the previous symbol. Unconfirmed sources still cannot authorize guarded drawing.

The plugin reuses FTShare credentials in this order: an `FTSHARE_API_KEY` already injected into the current DSH service, an explicitly configured `FTSHARE_API_KEY_FILE`, a Key saved in the DSH FTShare settings, and a local credential previously saved by this plugin. If the key is already available to the process that starts DSH, it is used automatically. Installing the FTShare SDK alone, or storing a key in another app's private configuration, is not enough for the plugin to read it.

When the DSH FTShare settings plugin is installed, the host publishes its Key to the MCP server, which re-reads it before every request — so adding, rotating, or clearing the Key in the settings page needs no dsh restart. That Key belongs to the settings page; this plugin never displays or clears it.

For safety, the plugin never scans `.env` files, shell configuration, keychains, or other apps' configuration files, and never displays a key or path. **Settings → Data source** identifies the active source; use **Manage FTShare configuration** to paste and test a replacement key, either for the current session or saved locally for future launches.

Theme and language follow the DSH host by default. **Settings → Theme/Language** also offers manual choices and a way back to **Follow host (default)**.

[FTShare's free-plan endpoints](https://market.ft.tech/gateway/doc/p/pb8eizu3) still require a registered API key. Without a key, some historical daily A-share bars can use BaoStock and selected broad-market indices have another free fallback; intraday bars, other markets, and news still depend on source coverage and permissions. Existing valid OHLCV data, including rows supplied by the host, can still drive local indicators and drawing. The UI reports the applicable source or error when data is rate-limited, unavailable, or outside the account's entitlement.

## Frequently asked questions

**Why is an intraday chart unavailable?**
Intraday access depends on the symbol's market, your account plan, and the source's currently supported coverage. Test the connection in Data source first. Daily, weekly, and monthly views do not require the intraday entitlement, but individual-stock candles still need a working data source; FTShare's free plan requires an API key too.

**What if the first launch fails on Windows?**

Inspect `%LOCALAPPDATA%\dsh_kline\bootstrap.log`. From v0.6.4, dependency upgrades reuse a working venv; rebuilding also tries its recorded base interpreter and Desktop's bundled standard Python. Trimmed distributions lacking venv/ensurepip still need a standard Python 3.11+ installation. Check `py -3.11 --version` (newer versions work), or set `DSH_KLINE_PYTHON` to the full `python.exe` path before starting DSH. Correcting the configuration invalidates the old retry delay. Nested bundles no longer need a profile-root K-line package, but bundles pinning an older plugin must update it. DSH installation and Windows sandbox issues remain host-level concerns.

**Why do two conversations show different charts?**
This is intentional: each chart belongs to its conversation, so an analysis in one conversation cannot replace another's chart. Search or start a new analysis in the other conversation when needed.

**Why can data differ slightly from another platform?**
Quotes can be delayed and may differ with adjustment policy, exchange conventions, market-close state, and upstream services. Use appropriately licensed feeds for commercial, high-frequency, or latency-sensitive work.

## For AI and developers

### Drawing through chat and the workbench

On a source-checked current chart, the host can interpret a request and use the plugin's calculate → prepare → apply → verify flow. The workbench exposes the same protected objects for manual selection, preview, and editing. Selected families are horizontal levels, two-anchor trend segments, three-anchor finite parallel channels, rectangular ranges, two-anchor Fibonacci retracements, manually supplied or host-proposed-and-checked ABC anchors, and standalone SMA/EMA lines or BOLL three-line bands. Names, four colors, channel midlines, and rectangle fills are supported. The plugin draws ABC labels; **it does not automatically recognize Elliott waves**, and candidates are not definitive conclusions.

Try “draw a blue level at 31.2 called support”, “move support to 30.8; leave everything else”,
or “propose a descending channel with three anchors and explain deviations; wait for approval”.

The host interprets language, analyzes candles and selects anchors. The plugin observes,
measures, executes and reports; it does not embed another AI or replay predefined drawing skills.
Explicit parameters may execute directly; proposal-first requests must wait for approval.
Host explanations and professional anchor selection can be wrong and require user judgement.

Foundation scope and limitations:

- Daily/weekly paths are the main acceptance scope. Anchors must match actual loaded bars.
  The plugin does not guess missing dates, snap anchors or fetch extra candles to repair edits.
- Trend segments and channels are finite, with no automatic extension or logarithmic geometry.
  Channels and rectangles retain their creation interval.
- Guarded edits target stable IDs without resetting candles, indicators or the viewport.
  Manual drawings, automatic annotations and AI objects remain separate.
- Confirmed drawings can restore and be edited after browser refresh within the same host run.
  Conversations are isolated. Returning to a conversation restores its last confirmed drawing
  checkpoint, **not necessarily its last manually selected interval, range or viewport**.
- Workbench point selection and form editing are supported; AI mouse dragging, undo, cross-process old-chart editing and complete automatic failure
  recovery are not supported. Unknown outcomes stop automatic retries.
- **Clear drawings and annotations** asks for confirmation, then removes AI objects,
  analysis annotations, manual drawings, and custom levels for the current symbol and interval.
  Indicators and alerts remain. Request an exact AI target when you want to delete only one object.
- An object may be outside the visible time/price range. Object state and application receipts
  do not prove screen pixels, professional pattern quality or vendor quote correctness.
- Minute availability depends on source/permissions; not all markets, minute sizes or operation combinations are accepted. Channels, boxes and ABC labels are not automatically recognized professional patterns. Chan analysis is not included. The 201 TA-Lib functions are primarily read-only; only the selected SMA/EMA/BBANDS outputs have a guarded drawing conversion.

Host integration uses `get_chart_context → prepare_chart_edit → apply_chart_edit → get_chart_edit_status`.
Read fresh context after approval and verify against independently retained approved parameters.
A `context_ref` is not a `chart_session`. Read-only `preview_chart_channel` and `verify_chart_drawings`
measure geometry/check parameters; neither selects patterns or grants drawing permission.
Legacy per-family tools manipulate explicit snapshots, not the guarded live-chart workflow.

Run `pnpm build:sidebar` and `pnpm test` for the build and complete Node/Python regression suite.
See the [v0.5.0 candidate acceptance notes](docs/release-acceptance-v0.5.0.md) for scope, evidence, and remaining release gates. The full [function guide](docs/chart-functions.md) separates read-only calculations from drawable results.
First-time automatic dependency preparation needs network access and may take several minutes.

### Host-provided Python runtime

Ordinary installs default to `DSH_KLINE_RUNTIME_MODE=auto`, preserving existing Python/venv selection and dependency preparation. Desktop applications, containers, and other hosts can set these variables before starting DSH:

| Environment variable | Meaning |
| --- | --- |
| `DSH_KLINE_PACKAGE_ROOT` | Optional absolute plugin package directory; otherwise resolved beside the plugin module, including nested installs. |
| `DSH_KLINE_PYTHON` | Path to the Python interpreter provided by the host. |
| `DSH_KLINE_RUNTIME_MODE` | `auto` (default) or `external`. |

`external` requires Python 3.11+ with the required dependencies already available. It only validates and launches the service: no venv creation, dependency installation, or interpreter fallback. The host must repair failures. This mode rejects `DSH_KLINE_VENV`, `--prepare-project`, and `--bootstrap-runtime`. `DSH_KLINE_DEFER_BOOTSTRAP` does not trigger background installation in this mode.

`DSH_KLINE_PYTHON` must identify the executable file (`python.exe` on Windows), not its directory. Automatic preparation distinguishes `PYTHON_NOT_FOUND`, `PYTHON_VERSION_TOO_OLD`, `PYTHON_EXECUTION_FAILED`, `PYTHON_VENV_UNAVAILABLE`, `PYTHON_DEPENDENCY_INSTALL_FAILED`, and `PYTHON_IMPORT_CHECK_FAILED`; an unusable Windows Store redirector is `PYTHON_STORE_ALIAS`. Candidate paths and outcomes are logged locally, without keys or a dump of the parent environment.

In `external` mode, the host owns the interpreter, dependency search paths, and isolation settings (such as `PYTHONPATH`, `PYTHONNOUSERSITE`, or Windows embedded Python's `._pth`); no other interpreter is discovered. `auto` mode uses the bounded discovery and repair described above. Set `DSH_KLINE_CHART_PORT=0` for a dynamic port. The MCP patch explicitly forwards runtime variables without changes to DSH core.

## Updates and license

See [Releases](https://github.com/FTShare-Lab/dsh_kline/releases) for version history. This project is released under the [MIT License](LICENSE); frontend provenance is in [PROVENANCE.md](PROVENANCE.md).

Maintainers changing tools, annotations, resources or the App bridge must regenerate the packaged catalog with `python scripts/generate-codex-catalog.py`; `--check` and regression tests detect stale catalogs.

The public `marketplace/ft-kline/` snapshot is generated from the same Codex package allowlist. After editing source, plugin manifests or README files, run `pnpm sync:codex-marketplace` and commit the generated files. CI runs `pnpm verify:codex-marketplace` and independently starts the directory in Desktop and CLI modes. Do not edit generated files directly; see [marketplace maintenance](marketplace/README.md).
