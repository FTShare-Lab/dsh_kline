import { access, readFile } from 'node:fs/promises'
import { constants } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const requiredFiles = [
  'lib/index.js',
  'lib/chart-context.js',
  'lib/chart-observation.js',
  'lib/chart-applications.js',
  'lib/chart-sources.js',
  'lib/chart-source-status.js',
  'lib/drawing-feedback.js',
  'lib/ftshare-settings-bridge.js',
  'lib/client.js',
  'lib/client/chart-context.js',
  'lib/client/chart-apply.js',
  'tools/chart_context.py',
  'tools/chart_edits.py',
  'tools/chart_applications.py',
  'tools/chart_sources.py',
  'tools/chart_source_status.py',
  'tools/drawing_feedback.py',
  'tools/chart_measurements.py',
  'lib/client/ClassicShell.js',
  'lib/client/BetterSidebarTab.js',
  'lib/client/KlineContent.js',
  'lib/client/sidebar-integration.js',
  'view/vendor/klinecharts.min.js',
  'config/basic-symbols.json',
]

for (const relativePath of requiredFiles) {
  await access(`${root}/${relativePath}`, constants.R_OK)
}

const client = await readFile(`${root}/lib/client.js`, 'utf8')
for (const marker of [
  '/dsh-kline/vendor/klinecharts.min.js',
  'client_dependency',
  'dependencies.klinecharts',
  'ftshare-kline:chart',
  'dsh-kline:display-mode:v1',
]) {
  if (!client.includes(marker)) {
    throw new Error(`built client is missing required marker: ${marker}`)
  }
}

console.log('DSH K-line package artifacts verified')
