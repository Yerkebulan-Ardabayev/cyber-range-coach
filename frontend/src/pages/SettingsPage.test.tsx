import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SettingsPage } from './SettingsPage'

const json = (data: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }))

const linuxHost = {
  id: 1, name: 'WSL Ubuntu', host: '127.0.0.1', port: 22, relay_source_ip: '172.30.164.100', username: 'student', runner_username: 'range-runner',
  public_key: 'ssh-ed25519 AAAA', runner_public_key: 'ssh-ed25519 BBBB', host_key_fingerprint: 'SHA256:test', confirmed: true, confirmed_at: '2026-09-25T10:00:00Z',
}

afterEach(() => { vi.restoreAllMocks() })

describe('SettingsPage range-runner check', () => {
  it('shows the failure next to the button, not only at the top of the page', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      if (path.endsWith('/runner-check')) return json({ code: 'runner_unavailable', message: 'Ограниченная проверяющая учётная запись Linux VM недоступна.', details: {} }, 503)
      if (path.endsWith('/system/linux-host')) return json(linuxHost)
      if (path.endsWith('/system/network')) return json({ bind_host: '0.0.0.0', port: 8443, lan_mode: true, tls_enabled: true, academy_urls: [], interfaces: [] })
      if (path.endsWith('/system/preflight')) return json({ checks: [] })
      if (path.endsWith('/devices')) return json([])
      return json({})
    })
    render(<QueryClientProvider client={new QueryClient()}><SettingsPage principal={{ role: 'owner' } as never} /></QueryClientProvider>)
    const button = await screen.findByRole('button', { name: 'Проверить range-runner' })
    await vi.waitFor(() => expect(button).not.toBeDisabled())
    fireEvent.click(button)
    const row = button.parentElement as HTMLElement
    expect(await within(row).findByText('Ограниченная проверяющая учётная запись Linux VM недоступна.')).toBeInTheDocument()
  })
})
