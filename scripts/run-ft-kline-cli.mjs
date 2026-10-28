#!/usr/bin/env node

// Deliberately separate CLI entry point: it starts the analysis-only Codex
// server and therefore cannot register the MCP App resource or drawing tools.
process.env.FT_KLINE_SERVER_ENTRY = 'codex_server.py'
process.env.FT_KLINE_CLIENT = 'cli'
process.env.FT_KLINE_CODEX_MEMORY_ONLY = '1'
delete process.env.DSH_KLINE_SETTINGS_KEY_FILE
delete process.env.DSH_KLINE_HOST_PID
delete process.env.DSH_KLINE_ADAPTER
delete process.env.DSH_KLINE_DEFER_BOOTSTRAP

const { main } = await import('./run-dsh-kline.mjs')
try { process.exitCode = await main(process.argv.slice(2)) }
catch (error) { process.stderr.write(`[ft-kline-cli] ${error instanceof Error ? error.message : String(error)}\n`); process.exitCode = 1 }
