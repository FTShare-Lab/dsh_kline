#!/usr/bin/env node

// Codex-compatible stdio entry point.  It reuses the same managed Python
// runtime/bootstrap as the DSH launcher, but disables DSH chart-session
// publishing and sidebar-specific instructions.
process.env.DSH_KLINE_ADAPTER = 'codex'
// Codex's MCP bootstrap awaits this process; DSH's reconnect strategy is not used.
delete process.env.DSH_KLINE_DEFER_BOOTSTRAP

const { main } = await import('./run-dsh-kline.mjs')
try {
  process.exitCode = await main(process.argv.slice(2))
} catch (error) {
  process.stderr.write(`[dsh_kline] ${error instanceof Error ? error.message : String(error)}\n`)
  process.exitCode = 1
}
