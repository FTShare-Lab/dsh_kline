import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readHostOptions, setHostOptions, subscribeHostOptions } from '../src/client/host-options.ts'

test('no host service means no options and therefore the upstream defaults', () => {
  setHostOptions(undefined)
  assert.equal(readHostOptions(), undefined)
})

test('only the options this build understands take effect', () => {
  setHostOptions({ entry: 'tab', onboarding: 'off' })
  assert.deepEqual(readHostOptions(), { entry: 'tab', onboarding: 'off' })
  setHostOptions({ entry: 'tab' })
  assert.deepEqual(readHostOptions(), { entry: 'tab' })
  setHostOptions({ onboarding: 'off' })
  assert.deepEqual(readHostOptions(), { onboarding: 'off' })
  // A newer or malformed host must not put the chart in a half-configured state.
  setHostOptions({ entry: 'window', onboarding: 'maybe', theme: 'pink' })
  assert.equal(readHostOptions(), undefined)
  setHostOptions({ entry: 'tab', onboarding: 'on' })
  assert.deepEqual(readHostOptions(), { entry: 'tab' })
})

test('subscribers hear every change, including a withdrawal', () => {
  const seen: unknown[] = []
  const stop = subscribeHostOptions(() => seen.push(readHostOptions()))
  setHostOptions({ entry: 'tab' })
  setHostOptions(undefined)
  stop()
  setHostOptions({ onboarding: 'off' })
  assert.deepEqual(seen, [{ entry: 'tab' }, undefined])
})
