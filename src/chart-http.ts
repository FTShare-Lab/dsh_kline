import { request } from 'node:http'

export class ChartHttpError extends Error {
  readonly reason: 'timeout' | 'unreachable' | 'too_large' | 'invalid_url'
  constructor(reason: ChartHttpError['reason']) {
    super(reason)
    this.reason = reason
  }
}

/** Private loopback transport. Avoid the host's bundled fetch/Undici socket QoS path. */
export function requestChartHttp(input: string | URL, options: {
  method?: 'GET' | 'POST'
  headers?: Record<string, string>
  body?: string
  timeoutMs: number
  maxBytes: number
}): Promise<{ status: number; body: Buffer }> {
  const url = new URL(input)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || url.username || url.password)
    return Promise.reject(new ChartHttpError('invalid_url'))
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (error?: Error, result?: { status: number; body: Buffer }) => {
      if (settled) return
      settled = true
      clearTimeout(deadline)
      if (error) reject(error)
      else resolve(result!)
    }
    const upstream = request(url, { method: options.method || 'GET', headers: options.headers, agent: false }, response => {
      const chunks: Buffer[] = []
      let size = 0
      response.on('error', () => finish(new ChartHttpError('unreachable')))
      response.on('aborted', () => finish(new ChartHttpError('unreachable')))
      response.on('data', (chunk: Buffer) => {
        size += chunk.length
        if (size > options.maxBytes) {
          finish(new ChartHttpError('too_large'))
          upstream.destroy()
          response.destroy()
          return
        }
        chunks.push(chunk)
      })
      response.on('end', () => finish(undefined, { status: response.statusCode || 502, body: Buffer.concat(chunks) }))
    })
    const deadline = setTimeout(() => {
      finish(new ChartHttpError('timeout'))
      upstream.destroy()
    }, options.timeoutMs)
    deadline.unref()
    upstream.on('error', () => finish(new ChartHttpError('unreachable')))
    upstream.end(options.body)
  })
}
