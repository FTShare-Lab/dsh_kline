import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPanelMounts } from '../src/client/host-panels.ts'

/** A slot registry stand-in: records injections and registrations like the host's. */
function fakeSlots() {
  const injected: string[] = []
  const registered: { name: string; component: unknown }[] = []
  const disposed: string[] = []
  const slots = {
    inject(name: string, factory: () => unknown) {
      injected.push(name)
      return factory()
    },
    register(options: { name: string }, component: unknown) {
      registered.push({ name: options.name, component })
      return () => { disposed.push(options.name) }
    },
  }
  return { slots, injected, registered, disposed }
}

test('a host that never mounts registers nothing', () => {
  const fake = fakeSlots()
  createPanelMounts(fake, () => ({ kind: 'chart' }))
  assert.deepEqual(fake.injected, [])
  assert.deepEqual(fake.registered, [])
})

test('mount fills exactly the seat the host declared and can be removed again', () => {
  const fake = fakeSlots()
  const panels = createPanelMounts(fake, (seat, chrome) => ({ seat, chrome }))
  const dispose = panels.mount('paperTrading.kline', { chrome: 'chart-search' })
  assert.deepEqual(fake.injected, ['paperTrading.kline'])
  assert.deepEqual(fake.registered, [
    { name: 'paperTrading.kline', component: { seat: 'paperTrading.kline', chrome: 'chart-search' } },
  ])
  dispose()
  assert.deepEqual(fake.disposed, ['paperTrading.kline'])
})

test('each seat gets its own body and the default chrome stays implicit', () => {
  const fake = fakeSlots()
  const panels = createPanelMounts(fake, (seat, chrome) => ({ seat, chrome }))
  panels.mount('first.panel')
  panels.mount('second.panel')
  assert.deepEqual(fake.injected, ['first.panel', 'second.panel'])
  assert.deepEqual(fake.registered.map(entry => entry.name), ['first.panel', 'second.panel'])
  assert.deepEqual(fake.registered.map(entry => (entry.component as { seat: string }).seat), ['first.panel', 'second.panel'])
  assert.equal((fake.registered[0].component as { chrome?: string }).chrome, undefined)
})
