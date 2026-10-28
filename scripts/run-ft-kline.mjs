#!/usr/bin/env node

// Codex Desktop entry point.  It shares only the dependency bootstrapper with
// the DSH package; the launched Python module and runtime/cache namespace are
// separate, and all DSH credential locators are removed before launch.
process.env.FT_KLINE_SERVER_ENTRY = 'codex_server.py'
process.env.FT_KLINE_CLIENT = 'desktop'
process.env.FT_KLINE_CODEX_MEMORY_ONLY = '1'
delete process.env.DSH_KLINE_SETTINGS_KEY_FILE
delete process.env.DSH_KLINE_HOST_PID
delete process.env.DSH_KLINE_ADAPTER
delete process.env.DSH_KLINE_DEFER_BOOTSTRAP

const { main } = await import('./run-dsh-kline.mjs')
try { process.exitCode = await main(process.argv.slice(2)) }
catch (error) { process.stderr.write(`[ft-kline] ${error instanceof Error ? error.message : String(error)}\n`); process.exitCode = 1 }
