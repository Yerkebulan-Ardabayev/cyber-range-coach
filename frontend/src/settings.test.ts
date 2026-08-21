import { describe, expect, it } from 'vitest'

import { canCreatePairing, missingRunnerTools, preferredPairingOrigin } from './settings'

describe('Settings safety helpers', () => {
  it('never builds a device QR from loopback', () => {
    expect(preferredPairingOrigin(['https://127.0.0.1:8443'])).toBeNull()
    expect(preferredPairingOrigin(['https://127.0.0.1:8443', 'https://192.168.1.20:8443'])).toBe('https://192.168.1.20:8443')
  })

  it('blocks runner readiness when a required tool is false or omitted', () => {
    const missing = missingRunnerTools({ protocol: 'crc-range-check/v1', check: 'tools', tools: { curl: true, nmap: false } })
    expect(missing).toContain('nmap')
    expect(missing).toContain('less')
  })

  it('blocks pairing until LAN, TLS and the full preflight are ready', () => {
    const origin = 'https://192.168.1.20:8443'
    expect(canCreatePairing(origin, false, true, true)).toBe(false)
    expect(canCreatePairing(origin, true, false, true)).toBe(false)
    expect(canCreatePairing(origin, true, true, false)).toBe(false)
    expect(canCreatePairing(origin, true, true, true)).toBe(true)
  })
})
