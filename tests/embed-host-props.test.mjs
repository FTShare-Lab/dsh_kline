import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import * as embed from '../src/client/embed.ts'

const source = readFileSync(new URL('../src/client/KlineContent.tsx', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
} }).outputText

// Execute the real component and its dependency-driven effects without a DOM
// renderer. Only the chart mount and React hook scheduling are substituted;
// prop-to-bridge calls and identity comparisons come from production code.
function hostHarness() {
  const slots = [], effects = [], opens = [], themes = []
  let cursor = 0, dirty = false, mounts = 0, disposals = 0, currentSymbol = ''
  const api = {
    ready: Promise.resolve(), currentSymbol: () => currentSymbol,
    openSymbol: async (symbol, name) => { opens.push({ symbol, name }); currentSymbol = symbol },
    setTheme: theme => themes.push(theme),
  }
  const react = {
    useContext: () => ({}),
    useRef(value) { return slots[cursor++] ??= { current: value } },
    useState(initial) {
      const index = cursor++
      slots[index] ??= { value: initial }
      return [slots[index].value, value => {
        if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true }
      }]
    },
    useEffect(callback, dependencies) {
      const index = cursor++, previous = slots[index]
      if (!previous || dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))) {
        effects.push(() => {
          previous?.cleanup?.()
          slots[index] = { dependencies, cleanup: callback() }
        })
      }
    },
  }
  const exports = {}
  runInNewContext(compiled, {
    exports,
    window: { klinecharts: { init() {} } },
    require(id) {
      if (id === 'react') return react
      if (id === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }) }
      if (id === './embed') return embed
      if (id === './mode-preferences' || id === './ui-onboarding') return {}
      assert.equal(id, './generated-view')
      return { mountKlineView(_root, _payload, dependencies) {
        mounts++
        dependencies.onReady(api)
        return () => { disposals++ }
      } }
    },
  })
  const element = { shadowRoot: {} }
  const onIdentity = () => {}
  return {
    opens, themes,
    get mounts() { return mounts }, get disposals() { return disposals },
    async render(props) {
      for (let attempt = 0; attempt < 10; attempt++) {
        cursor = 0; dirty = false
        const tree = exports.StandaloneKlineApp({ conversationId: 'panel', embedded: true, onIdentity, ...props })
        tree.props.ref.current = element
        while (effects.length) effects.shift()()
        await Promise.resolve()
        await Promise.resolve()
        if (!dirty) return
      }
      assert.fail('host effects failed to settle')
    },
    unmount() { for (const slot of slots) slot?.cleanup?.() },
  }
}

test('host prop changes open different markets and ticker prefixes without remounting', async () => {
  const host = hostHarness()
  try {
    for (const symbol of ['000001.XSHG', '000001.XSHE', 'V.US', 'VZ.US']) await host.render({ symbol })
    assert.deepEqual(host.opens.map(call => call.symbol), ['000001.XSHG', '000001.XSHE', 'V.US', 'VZ.US'])
    await host.render({ symbol: 'VZ.NYSE' })
    assert.equal(host.opens.length, 4, 'equivalent host round trips must not reopen the chart')
    assert.equal(host.mounts, 1)
  } finally { host.unmount() }
  assert.equal(host.disposals, 1)
})

test('removing a pinned host theme restores host mode without remounting', async () => {
  const host = hostHarness()
  try {
    await host.render({ theme: 'dark' })
    await host.render({})
    await host.render({ theme: 'light' })
    await host.render({ theme: undefined })
    assert.deepEqual(host.themes, ['dark', 'host', 'light', 'host'])
    assert.equal(host.mounts, 1)
  } finally { host.unmount() }
})

test('the runtime releases its pinned palette and follows later host theme changes', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const current = html.slice(html.indexOf('function currentTheme('), html.indexOf('function applyTheme('))
  const setter = html.slice(html.indexOf('function setHostTheme('), html.indexOf('function syncThemeToggle('))
  const state = { hostThemeOverride: 'dark', userThemeOverride: null, lastChartPayload: null,
    documentTheme: 'light', applyTheme() {} }
  const runtime = runInNewContext(current + setter + '; ({ currentTheme, setHostTheme })',
    { ...state, hostTheme: () => state.documentTheme })
  assert.equal(runtime.currentTheme(), 'dark')
  runtime.setHostTheme('host')
  assert.equal(runtime.currentTheme(), 'light')
  state.documentTheme = 'dark'
  assert.equal(runtime.currentTheme(), 'dark')
})
