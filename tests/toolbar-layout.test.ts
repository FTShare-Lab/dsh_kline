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
  assert.ok(indicators >= 0 && indicators < primary && primary < drawing && drawing < tools)
  assert.match(toolbar, /id="indicatorPopover"[\s\S]*id="indMa"[\s\S]*id="indVwap"[\s\S]*id="indVol"[\s\S]*id="indMacd"[\s\S]*id="indKdj"[\s\S]*id="indBoll"/)
  assert.match(toolbar, /class="toolbar-tools"[\s\S]*id="levelMenuBtn"[\s\S]*id="alertMenuBtn"[\s\S]*id="compareMenuBtn"/)
  assert.doesNotMatch(toolbar, /id="clearBtn"/)
  assert.match(html, /id="drawingWorkbench"[\s\S]*id="clearBtn"/)
  assert.doesNotMatch(toolbar, /id="drawingMenuBtn"|id="keyLevelsBtn"|data-drawing-type=/)
  assert.match(toolbar, /id="indicatorSavedObjects"/)
  assert.doesNotMatch(toolbar, /id="toolbarMore"/)
})

test('narrow chart controls stay on one row and use accessible overflow menus', () => {
  assert.match(html, /\.toolbar-actions \{ display: flex; align-items: center; flex-wrap: nowrap/)
  assert.match(html, /\.timebar \{ position: relative; display: flex; align-items: center/)
  for (const id of ['timebarOverflow', 'toolbarOverflow', 'workbenchOverflow'])
    assert.match(html, new RegExp(`id="${id}"[\\s\\S]*?aria-expanded="false"[\\s\\S]*?class="overflow-panel"`))
  assert.match(html, /function makeOverflowRow\([\s\S]*?marker\.after\(item\)[\s\S]*?panel\.appendChild\(item\)/)
  assert.match(html, /new ResizeObserver\(queueOverflowLayout\)/)
  assert.match(toolbar, /id="compareMenuBtn"[\s\S]*?id="toolbarOverflow"[\s\S]*?class="toolbar-zoom"[\s\S]*?id="chartZoomOutBtn"[\s\S]*?id="chartZoomInBtn"/)
})

test('zoom follows chart actions and the drawing tool is highlighted only while open', () => {
  const interval = html.indexOf('id="intervalControls"')
  const zoom = html.indexOf('id="chartZoomOutBtn"')
  const toolbarStart = html.indexOf('<div class="toolbar">')
  const workbenchStart = html.indexOf('<section class="drawing-workbench"')
  assert.ok(interval >= 0 && interval < toolbarStart && toolbarStart < zoom && zoom < workbenchStart)
  assert.match(html, /#drawingWorkbenchToggle\[aria-expanded="true"\] \{ background: var\(--accent\)/)
  assert.match(html, /class="workbench-grid workbench-main-grid"/)
  assert.match(html, /id="workbenchToolRow"[\s\S]*id="workbenchType"[\s\S]*class="workbench-actions"[\s\S]*id="workbenchCandidateBtn"[\s\S]*id="workbenchPick"[\s\S]*id="workbenchMoreButton"[\s\S]*id="clearBtn"/)
  assert.match(html, /\.timebar \.btn, \.toolbar-actions \.btn, \.workbench-tool-row \.btn, \.overflow-panel \.btn \{ height: 28px/)
})
