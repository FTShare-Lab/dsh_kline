import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPanelMountRegistry, createPanelMounts } from '../src/client/host-panels.ts'

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

function connectedPanels() {
  const fake = fakeSlots()
  const panels = createPanelMountRegistry()
  const disconnect = panels.connect(createPanelMounts(fake, (seat, chrome) => ({ seat, chrome })))
  return { ...fake, panels, disconnect }
}

test('an old cleanup cannot remove a reopened chart on the same seat', () => {
  const { panels, registered, disposed } = connectedPanels()
  const closeOld = panels.mount('paper.kline')
  closeOld()
  const closeNew = panels.mount('paper.kline')
  closeOld()
  assert.equal(registered.length, 2)
  assert.deepEqual(disposed, ['paper.kline'])
  closeNew()
  closeNew()
  assert.deepEqual(disposed, ['paper.kline', 'paper.kline'])
})

test('callers sharing one seat release only their own lease', () => {
  const { panels, registered, disposed } = connectedPanels()
  const first = panels.mount('paper.kline')
  const second = panels.mount('paper.kline', { chrome: 'chart-search' })
  assert.equal(registered.length, 1)
  first()
  first()
  assert.deepEqual(disposed, [])
  second()
  assert.deepEqual(disposed, ['paper.kline'])
})

test('releasing one seat does not affect another seat', () => {
  const { panels, disposed } = connectedPanels()
  const first = panels.mount('first.panel')
  const second = panels.mount('second.panel')
  first()
  assert.deepEqual(disposed, ['first.panel'])
  second()
  assert.deepEqual(disposed, ['first.panel', 'second.panel'])
})

test('requests wait for slot services, but canceled requests never register', () => {
  const fake = fakeSlots()
  const panels = createPanelMountRegistry()
  const cancel = panels.mount('closed.panel')
  cancel()
  const close = panels.mount('open.panel', { chrome: 'chart' })
  assert.deepEqual(fake.registered, [])
  const disconnect = panels.connect(createPanelMounts(fake, (seat, chrome) => ({ seat, chrome })))
  assert.deepEqual(fake.registered.map(entry => entry.name), ['open.panel'])
  assert.deepEqual(fake.registered[0].component, { seat: 'open.panel', chrome: 'chart' })
  close()
  disconnect()
  assert.deepEqual(fake.disposed, ['open.panel'])
})

test('service replacement preserves requests and old cleanup cannot detach the new service', () => {
  const first = fakeSlots(), second = fakeSlots(), third = fakeSlots()
  const panels = createPanelMountRegistry()
  const close = panels.mount('paper.kline')
  const detachFirst = panels.connect(createPanelMounts(first, () => ({})))
  const detachSecond = panels.connect(createPanelMounts(second, () => ({})))
  detachFirst()
  assert.deepEqual(first.disposed, ['paper.kline'])
  assert.deepEqual(second.disposed, [])
  close()
  detachSecond()
  panels.connect(createPanelMounts(third, () => ({})))
  assert.deepEqual(second.disposed, ['paper.kline'])
  assert.deepEqual(third.registered, [])
})

test('conflicting chrome cannot silently replace or retain a caller lease', () => {
  const { panels, registered, disposed } = connectedPanels()
  const close = panels.mount('paper.kline', { chrome: 'chart' })
  assert.throws(() => panels.mount('paper.kline', { chrome: 'full' }), /different chrome/)
  assert.equal(registered.length, 1)
  close()
  assert.deepEqual(disposed, ['paper.kline'])
  const closeNew = panels.mount('paper.kline', { chrome: 'full' })
  assert.equal(registered.length, 2)
  close()
  assert.equal(disposed.length, 1)
  closeNew()
})

test('a failed mount does not poison the seat or keep a phantom request', () => {
  const panels = createPanelMountRegistry()
  let fail = true, mounts = 0, closes = 0
  panels.connect({ mount() { if (fail) throw Error('not available'); mounts++; return () => { closes++ } } })
  assert.throws(() => panels.mount('paper.kline'), /not available/)
  fail = false
  const close = panels.mount('paper.kline')
  assert.equal(mounts, 1)
  close()
  assert.equal(closes, 1)
})

test('failed service attachment rolls back mounted seats and can be retried', () => {
  const panels = createPanelMountRegistry()
  const closeFirst = panels.mount('first.panel'), closeSecond = panels.mount('second.panel')
  const disposed: string[] = []
  assert.throws(() => panels.connect({ mount(seat) {
    if (seat === 'second.panel') throw Error('occupied')
    return () => { disposed.push(seat) }
  } }), /occupied/)
  assert.deepEqual(disposed, ['first.panel'])
  const fake = fakeSlots()
  panels.connect(createPanelMounts(fake, () => ({})))
  assert.deepEqual(fake.registered.map(entry => entry.name), ['first.panel', 'second.panel'])
  closeFirst()
  closeSecond()
  assert.deepEqual(fake.disposed, ['first.panel', 'second.panel'])
})

test('one failing teardown still releases all seats and disconnects the old service', () => {
  const panels = createPanelMountRegistry()
  panels.mount('first.panel')
  panels.mount('second.panel')
  const disposed: string[] = []
  const detach = panels.connect({ mount(seat) { return () => {
    disposed.push(seat)
    if (seat === 'first.panel') throw Error('teardown failed')
  } } })
  assert.throws(detach, AggregateError)
  assert.deepEqual(disposed, ['first.panel', 'second.panel'])
  detach()
  const fake = fakeSlots()
  panels.connect(createPanelMounts(fake, () => ({})))
  assert.equal(fake.registered.length, 2)
})
