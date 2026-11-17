import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { whenLaidOut } from '../src/client/layout-ready.ts'

/** A layout host whose box the test moves, plus an observer it can fire. */
function layoutHost(initial = { width: 0, height: 0 }) {
  const element = { clientWidth: initial.width, clientHeight: initial.height } as unknown as HTMLElement
  const callbacks: Array<() => void> = []
  let disconnected = 0
  class FakeResizeObserver {
    constructor(callback: () => void) { callbacks.push(callback) }
    observe() {}
    disconnect() { disconnected += 1 }
  }
  const previous = (globalThis as { ResizeObserver?: unknown }).ResizeObserver
  ;(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver
  return {
    element,
    resize(width: number, height: number) { element.clientWidth = width; element.clientHeight = height },
    fire() { for (const callback of callbacks) callback() },
    get disconnected() { return disconnected },
    restore() { (globalThis as { ResizeObserver?: unknown }).ResizeObserver = previous },
  }
}

test('a container that is already laid out mounts immediately', () => {
  const host = layoutHost({ width: 864, height: 1042 })
  try {
    let mounts = 0
    whenLaidOut(host.element, () => { mounts += 1 })
    assert.equal(mounts, 1)
    assert.equal(host.disconnected, 0)
  } finally { host.restore() }
})

test('a zero-sized pane waits for its first real box and mounts once', () => {
  const host = layoutHost()
  try {
    let mounts = 0
    whenLaidOut(host.element, () => { mounts += 1 })
    host.fire()
    assert.equal(mounts, 0, 'a still-collapsed pane must not initialize the chart')
    host.resize(720, 900)
    host.fire()
    assert.equal(mounts, 1)
    assert.equal(host.disconnected, 1, 'the observer stops after the first real box')
    host.fire()
    assert.equal(mounts, 1, 'later observer callbacks cannot mount twice')
  } finally { host.restore() }
})

test('cancelling before layout never mounts and stops observing', () => {
  const host = layoutHost()
  try {
    let mounts = 0
    const cancel = whenLaidOut(host.element, () => { mounts += 1 })
    cancel()
    host.resize(600, 400)
    host.fire()
    assert.equal(mounts, 0)
    assert.equal(host.disconnected, 1)
  } finally { host.restore() }
})

test('an unobservable host keeps the previous synchronous mount', () => {
  const element = {} as HTMLElement
  let mounts = 0
  whenLaidOut(element, () => { mounts += 1 })
  assert.equal(mounts, 1)
})

test('a runtime without ResizeObserver still opens the chart instead of hanging', () => {
  const previous = (globalThis as { ResizeObserver?: unknown }).ResizeObserver
  ;(globalThis as { ResizeObserver?: unknown }).ResizeObserver = undefined
  try {
    const element = { clientWidth: 0, clientHeight: 0 } as unknown as HTMLElement
    let mounts = 0
    whenLaidOut(element, () => { mounts += 1 })
    assert.equal(mounts, 1)
  } finally { (globalThis as { ResizeObserver?: unknown }).ResizeObserver = previous }
})

test('both chart apps wait for layout before initializing the view', () => {
  const source = readFileSync(new URL('../src/client/KlineContent.tsx', import.meta.url), 'utf8')
  assert.equal((source.match(/cancelLayout = whenLaidOut\(/g) ?? []).length, 2, 'native tab and standalone panel share the gate')
})
