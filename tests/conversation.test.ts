import { test } from 'node:test'
import assert from 'node:assert/strict'
import { latestChart, latestChartFromEvents, chartStorageKey } from '../src/client/conversation.ts'

const a = 'a'.repeat(32), b = 'b'.repeat(32)
const result = (token: string, time: number, extra = {}) => ({
  kind: 'tool-result', call: { name: 'mcp__dsh-kline__analyze_kline' }, callTime: time,
  content: [{ type: 'text', text: 'analyze_kline ok · ' + JSON.stringify({chart_session: token}) }], ...extra,
})
test('different conversation results never share a chart', () => {
  assert.equal(latestChart([result(a, 1)])?.session, a)
  assert.equal(latestChart([result(b, 2)])?.session, b)
  assert.equal(latestChart([]), undefined)
  assert.notEqual(chartStorageKey('A'), chartStorageKey('B'))
})
test('older call finishing late cannot replace newer call', () => {
  assert.equal(latestChart([result(b, 2), result(a, 1)])?.session, b)
})
test('nested Code Mode tool results remain attached to owner', () => {
  assert.equal(latestChart([{kind: 'tool-result', subCalls: [result(a, 1)]}])?.session, a)
})
test('user prose, other plugins and errors cannot claim a chart', () => {
  assert.equal(latestChart([result(a, 1, {kind: 'user-message'})]), undefined)
  assert.equal(latestChart([result(a, 1, {call: {name: 'other_tool'}})]), undefined)
  assert.equal(latestChart([result(a, 1, {isError: true})]), undefined)
})
test('external rows summaries carry their chart reference', () => {
  assert.equal(latestChart([result(a, 1, {call:{name:'mcp__dsh-kline__analyze_kline_rows'}, content:[{type:'text', text:`analyze_kline_rows ok · chart_session=${a}`} ]})])?.session, a)
})

const event = (type: string, time: number, data: unknown) => ({ type: 'event', event: { type, time, data } })
const callEvent = (id: string, time: number, name = 'mcp__dsh-kline__analyze_kline') => event('tool/call', time, {callId: id, name})
const resultEvent = (id: string, token: string, time: number, isError = false) => event('tool/result', time, {
  message: {role: 'user', content: [{type: 'tool-result', toolCallId: id, isError, content: result(token, time).content}]},
})
test('Harness 0.1.2 event windows select only their owning chart', () => {
  assert.equal(latestChartFromEvents([callEvent('A', 1), resultEvent('A', a, 3)])?.session, a)
  assert.equal(latestChartFromEvents([callEvent('B', 2), resultEvent('B', b, 4)])?.session, b)
  assert.equal(latestChartFromEvents([]), undefined)
})
test('Harness 0.1.2 orders charts by invocation, not result arrival', () => {
  assert.deepEqual(latestChartFromEvents([callEvent('A', 1), callEvent('B', 2), resultEvent('B', b, 3), resultEvent('A', a, 4)]), {session: b, order: 2})
})
test('Harness 0.1.2 ignores errors, orphan results, prose and compact assistant chunks', () => {
  assert.equal(latestChartFromEvents([resultEvent('missing', a, 1)]), undefined)
  assert.equal(latestChartFromEvents([callEvent('A', 1), resultEvent('A', a, 2, true)]), undefined)
  assert.equal(latestChartFromEvents([callEvent('A', 1, 'other_tool'), resultEvent('A', a, 2)]), undefined)
  assert.equal(latestChartFromEvents([event('user/message', 1, {message: {content: result(a, 1).content}})]), undefined)
  assert.equal(latestChartFromEvents([{type:'chunks', event: result(a, 1)}]), undefined)
})
test('Harness 0.1.2 supports PTC nested dispatch and external rows', () => {
  const data = {rootCallId:'root', parentCallId:'root', subCallId:'root:code:1', name:'mcp__dsh-kline__analyze_kline_rows'}
  const start = event('tool/code-dispatch-start', 2, data)
  const end = event('tool/code-dispatch', 4, {...data, isError:false, content:[{type:'text', text:`chart_session=${a}`}]})
  assert.deepEqual(latestChartFromEvents([callEvent('root', 1, 'run_code'), start, end]), {session:a, order:2})
  assert.equal(latestChartFromEvents([end]), undefined)
  assert.equal(latestChartFromEvents([start, event('tool/code-dispatch', 4, {...end.event.data as object, isError:true})]), undefined)
})
