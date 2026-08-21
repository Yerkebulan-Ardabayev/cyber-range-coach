import { spawn } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import net from 'node:net'

function reserveAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      if (!address || typeof address === 'string') {
        server.close(() => reject(new Error('Не удалось выбрать порт для Playwright.')))
        return
      }
      server.close((error) => error ? reject(error) : resolve(address.port))
    })
  })
}

const port = await reserveAvailablePort()
const ownsOutputDirectory = !process.env.CRC_E2E_OUTPUT_DIR
const outputDirectory = process.env.CRC_E2E_OUTPUT_DIR
  ?? await mkdtemp(join(tmpdir(), 'cyber-range-coach-playwright.'))
const executable = process.platform === 'win32' ? 'npx.cmd' : 'npx'
const child = spawn(executable, ['playwright', 'test', ...process.argv.slice(2)], {
  env: {
    ...process.env,
    CRC_E2E_OUTPUT_DIR: outputDirectory,
    CRC_E2E_PORT: String(port),
  },
  stdio: 'inherit',
})

const exitCode = await new Promise((resolve, reject) => {
  child.once('error', reject)
  child.once('exit', (code) => resolve(code ?? 1))
})

if (ownsOutputDirectory && exitCode === 0) {
  await rm(outputDirectory, { recursive: true, force: true })
}

process.exitCode = exitCode
