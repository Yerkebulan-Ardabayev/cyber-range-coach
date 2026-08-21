import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from './api'

describe('api client', () => {
  afterEach(() => {
    document.cookie = 'crc_csrf=; Max-Age=0; Path=/'
    vi.unstubAllGlobals()
  })

  it('adds the CSRF token to mutating same-origin requests', async () => {
    document.cookie = 'crc_csrf=known-token; Path=/'
    const fetchMock = vi.fn((_path: string, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('known-token')
      expect(init?.credentials).toBe('same-origin')
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(api('/api/v2/notes', { method: 'POST', body: '{}' })).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('does not add CSRF to read-only requests', async () => {
    document.cookie = 'crc_csrf=known-token; Path=/'
    const fetchMock = vi.fn((_path: string, init?: RequestInit) => {
      expect(new Headers(init?.headers).has('X-CSRF-Token')).toBe(false)
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    await api('/api/v2/notes')
  })
})
