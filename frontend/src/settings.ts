export interface RunnerToolsEvidence {
  protocol: string
  check: string
  tools: Record<string, boolean>
}

const requiredTools = [
  'awk', 'base64', 'bash', 'cat', 'curl', 'find', 'getent', 'grep', 'id', 'ip', 'install', 'less',
  'ls', 'mktemp', 'nc', 'nmap', 'pwd', 'rm', 'sort', 'stat', 'tail', 'timeout', 'touch', 'tr',
]

export function missingRunnerTools(evidence: RunnerToolsEvidence | undefined): string[] {
  if (!evidence || evidence.protocol !== 'crc-range-check/v1' || evidence.check !== 'tools') return [...requiredTools]
  return requiredTools.filter((tool) => evidence.tools[tool] !== true)
}

export function preferredPairingOrigin(urls: string[] | undefined): string | null {
  for (const value of urls ?? []) {
    try {
      const url = new URL(value)
      if (!['127.0.0.1', 'localhost', '::1', '[::1]'].includes(url.hostname)) return url.origin
    } catch {
      // Ignore an invalid server-provided candidate and keep looking.
    }
  }
  return null
}

export function canCreatePairing(
  origin: string | null,
  preflightReady: boolean,
  lanMode: boolean,
  tlsEnabled: boolean,
): boolean {
  return Boolean(origin && preflightReady && lanMode && tlsEnabled)
}
