import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const toolbar = html.slice(html.indexOf('<div class="toolbar">'), html.indexOf('<section class="drawing-workbench"'))

test('six chart actions stay visible without overlapping drawing entrances', () => {
  const primary = toolbar.indexOf('class="toolbar-primary"')
  const drawing = toolbar.indexOf('id="drawingWorkbenchToggle"')
  const indicators = toolbar.indexOf('class="toolbar-indicators"')
  const tools = toolbar.indexOf('class="toolbar-tools"')
  const clear = toolbar.indexOf('id="clearBtn"')
  assert.ok(indicators >= 0 && indicators < primary && primary < drawing && drawing < tools && tools < clear)
  assert.match(toolbar, /id="indicatorPopover"[\s\S]*id="indMa"[\s\S]*id="indVwap"[\s\S]*id="indVol"[\s\S]*id="indMacd"[\s\S]*id="indKdj"[\s\S]*id="indBoll"/)
  assert.match(toolbar, /class="toolbar-tools"[\s\S]*id="levelMenuBtn"[\s\S]*id="alertMenuBtn"[\s\S]*id="compareMenuBtn"[\s\S]*id="clearBtn"/)
  assert.doesNotMatch(toolbar, /id="drawingMenuBtn"|id="keyLevelsBtn"|data-drawing-type=/)
  assert.match(toolbar, /id="indicatorSavedObjects"/)
  assert.doesNotMatch(toolbar, /id="toolbarMore"/)
})

test('narrow chart controls wrap instead of hiding buttons behind an invisible scrollbar', () => {
  assert.match(html, /\.toolbar-actions \{ display: flex; align-items: center; flex-wrap: wrap/)
  assert.match(html, /@container \(max-width: 760px\) \{[\s\S]*?\.timebar \{ position: relative; display: grid; grid-template-columns: minmax\(0, 1fr\) auto; overflow: visible; \}/)
  assert.match(html, /#rangeControls \{ grid-column: 1 \/ -1; \}[\s\S]*?#intervalControls \{ grid-column: 1; \}[\s\S]*?\.timebar-zoom \{ grid-column: 2;/)
  assert.doesNotMatch(html, /\.toolbar \{ flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; \}/)
  assert.match(html, /\.toolbar \.indicator-popover, \.toolbar \.alert-popover[\s\S]*left: 8px; right: auto; width: min\(336px, calc\(100% - 16px\)\)/)
  assert.match(html, /document\.querySelector\("\.toolbar-actions"\)\.addEventListener\("pointerdown"[\s\S]*!event\.target\.closest\("\.indicator-menu-wrap"\)/)
})

test('zoom follows interval controls and the drawing tool is highlighted only while open', () => {
  const interval = html.indexOf('id="intervalControls"')
  const zoom = html.indexOf('id="chartZoomOutBtn"')
  const toolbarStart = html.indexOf('<div class="toolbar">')
  assert.ok(interval >= 0 && interval < zoom && zoom < toolbarStart)
  assert.match(html, /#drawingWorkbenchToggle\[aria-expanded="true"\] \{ background: var\(--accent\)/)
  assert.match(html, /class="workbench-grid workbench-main-grid"/)
  assert.match(html, /class="workbench-controls"[\s\S]*id="workbenchAdvanced"[\s\S]*class="workbench-actions"/)
})
