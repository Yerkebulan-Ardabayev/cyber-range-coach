import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RangePage } from './RangePage'

const json = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }))

const registered = {
  id: 7, display_name: 'juice-shop', provider: 'docker_desktop', container_reference: 'c-juice', container_port: 3000,
  image_digest: 'sha256:aa', host_endpoint: 'http://127.0.0.1:3000/', health_check: {}, reset_policy: 'external',
  fingerprint: 'ff', allowed_curriculum_tags: ['web'], exposure_warnings: [], approved_at: '2026-09-25T10:00:00Z', last_verified_at: null,
}
const container = (id: string, name: string) => ({
  container_id: id, name, image: `${name}:latest`, image_digest: 'sha256:aa', state: 'running', health: null, started_at: null,
  ports: [{ host_ip: '0.0.0.0', host_port: id === 'c-juice' ? 3000 : 8080, container_port: id === 'c-juice' ? 3000 : 8080, protocol: 'tcp', exposure: 'lan', loopback_endpoint: 'http://127.0.0.1/' }],
  detected_kind: 'generic', warnings: [],
})

afterEach(() => { vi.restoreAllMocks() })

describe('RangePage discovery', () => {
  it('does not offer to confirm a container that is already a target', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      if (path.endsWith('/targets/discover')) return json([container('c-juice', 'juice-shop'), container('c-goat', 'webgoat')])
      if (path.endsWith('/targets')) return json([registered])
      return json({ checks: [] })
    })
    render(<QueryClientProvider client={new QueryClient()}><RangePage principal={{ role: 'owner' } as never} /></QueryClientProvider>)
    await screen.findByText('http://127.0.0.1:3000/')
    fireEvent.click(screen.getByRole('button', { name: 'Обнаружить контейнеры' }))
    await screen.findByText('Уже подтверждена')
    expect(screen.getAllByRole('button', { name: /Подтвердить профиль/ })).toHaveLength(1)
  })
})
