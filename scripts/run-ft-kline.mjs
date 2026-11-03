#!/usr/bin/env node

// Codex Desktop entry point.  It shares only the dependency bootstrapper with
// the DSH package; the launched Python module and runtime/cache namespace are
// separate, and all DSH credential locators are removed before launch.
import { readFileSync } from 'node:fs'

process.env.FT_KLINE_VERSION = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')).version
process.env.FT_KLINE_SERVER_ENTRY = 'codex_server.py'
process.env.FT_KLINE_CLIENT ||= 'auto'
process.env.FT_KLINE_CODEX_MEMORY_ONLY = '1'
delete process.env.DSH_KLINE_SETTINGS_KEY_FILE
delete process.env.DSH_KLINE_HOST_PID
delete process.env.DSH_KLINE_ADAPTER
delete process.env.DSH_KLINE_DEFER_BOOTSTRAP

if (process.argv.slice(2).some(arg => ['--prepare-project', '--bootstrap-runtime'].includes(arg))) {
  const { main } = await import('./run-dsh-kline.mjs')
  try { process.exitCode = await main(process.argv.slice(2)) }
  catch (error) { process.stderr.write(`[ft-kline] ${error instanceof Error ? error.message : String(error)}\n`); process.exitCode = 1 }
} else {
  const { fileURLToPath } = await import('node:url')
  const { serve } = await import('./codex-bootstrap.mjs')
  serve({ args: [fileURLToPath(new URL('./run-dsh-kline.mjs', import.meta.url))] })
}
