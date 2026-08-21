import { useEffect, useRef, useState } from 'react'

import type { Role } from '../types'
import { StatusPill } from './Common'

export function TerminalPanel({ runId, role, transcript }: { runId: number; role: Role; transcript: string }) {
  const host = useRef<HTMLDivElement>(null)
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 767px)').matches)
  const [portraitTablet, setPortraitTablet] = useState(() => window.matchMedia('(min-width: 768px) and (max-width: 1023px) and (orientation: portrait)').matches)
  const interactive = role !== 'viewer' && !compact && !portraitTablet

  useEffect(() => {
    const mobile = window.matchMedia('(max-width: 767px)')
    const tablet = window.matchMedia('(min-width: 768px) and (max-width: 1023px) and (orientation: portrait)')
    const update = () => { setCompact(mobile.matches); setPortraitTablet(tablet.matches) }
    mobile.addEventListener('change', update)
    tablet.addEventListener('change', update)
    return () => { mobile.removeEventListener('change', update); tablet.removeEventListener('change', update) }
  }, [])

  useEffect(() => {
    if (!interactive || !host.current) return
    let disposed = false
    let release = () => undefined
    const container = host.current
    void Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]).then(([xterm, addon]) => {
      if (disposed) return
      const terminal = new xterm.Terminal({
        cursorBlink: true,
        convertEol: true,
        fontFamily: 'Iosevka, monospace',
        fontSize: 14,
        lineHeight: 1.25,
        scrollback: 5000,
        theme: {
          background: '#07100f',
          foreground: '#d9e4d5',
          cursor: '#ffcb68',
          selectionBackground: '#48645d88',
          black: '#07100f',
          red: '#ef7d6d',
          green: '#8fcf9a',
          yellow: '#ffcb68',
          blue: '#85b7cf',
          magenta: '#c9a7d8',
          cyan: '#78c8bd',
          white: '#e8eee5',
        },
      })
      const fit = new addon.FitAddon()
      terminal.loadAddon(fit)
      terminal.open(container)
      fit.fit()
      let socket: WebSocket | null = null
      let retry = 0
      let exited = false
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const connect = () => {
        socket = new WebSocket(`${protocol}//${window.location.host}/api/v2/terminal/${runId}`)
        socket.addEventListener('open', () => {
          retry = 0
          terminal.writeln('\x1b[38;2;120;200;189m[наставник] SSH-канал готов\x1b[0m')
          socket?.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
        })
        socket.addEventListener('message', (event) => {
          const message = JSON.parse(String(event.data)) as { type: string; data?: string; message?: string; reconnectable?: boolean }
          if (message.type === 'output' && message.data) terminal.write(message.data)
          if (message.type === 'transcript' && message.data) { terminal.clear(); terminal.write(message.data) }
          if (message.type === 'error') terminal.writeln(`\r\n\x1b[31m[наставник] ${message.message ?? 'ошибка терминала'}\x1b[0m`)
          if (message.type === 'exit') { exited = true; terminal.writeln('\r\n\x1b[33m[наставник] терминал закрыт\x1b[0m') }
        })
        socket.addEventListener('close', () => {
          if (!disposed && !exited && retry < 3) {
            retry += 1
            window.setTimeout(connect, 750 * retry)
          }
        })
      }
      connect()
      const dataSubscription = terminal.onData((data) => {
        if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data }))
      })
      const observer = new ResizeObserver(() => {
        fit.fit()
        if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
      })
      observer.observe(container)
      release = () => {
        observer.disconnect()
        dataSubscription.dispose()
        socket?.close()
        terminal.dispose()
      }
    })
    return () => {
      disposed = true
      release()
    }
  }, [interactive, runId])

  if (!interactive) {
    return (
      <div className="terminal-readonly">
        <div className="terminal-readonly__head"><StatusPill status="warning">ТОЛЬКО ЧТЕНИЕ</StatusPill><span>{role === 'viewer' ? 'Роль viewer не вводит команды' : 'Поверните планшет или откройте с ноутбука'}</span></div>
        <pre>{transcript || 'Журнал терминала появится после выполнения команды на полном экране.'}</pre>
      </div>
    )
  }
  return <div className="terminal-host" ref={host} aria-label="Интерактивный терминал Linux VM" />
}
