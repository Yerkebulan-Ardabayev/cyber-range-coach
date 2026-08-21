import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { api, jsonBody } from '../api'
import { TerminalIcon } from '../icons'
import { ErrorNotice, Eyebrow } from './Common'

export function PairingView() {
  const queryClient = useQueryClient()
  const [search] = useSearchParams()
  const [token, setToken] = useState(search.get('pairToken') ?? '')
  const [name, setName] = useState('Моё устройство')
  const [fingerprint, setFingerprint] = useState('')
  const pair = useMutation({
    mutationFn: () => api('/api/v2/devices/pair', {
      method: 'POST',
      ...jsonBody({ token, device_name: name, confirmed_fingerprint: fingerprint }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['principal'] }),
  })
  return (
    <main className="pairing-screen">
      <section className="pairing-card">
        <div className="pairing-card__mark"><TerminalIcon /></div>
        <Eyebrow>ЗАЩИЩЁННАЯ ПРИВЯЗКА</Eyebrow>
        <h1>Это устройство ещё не знает академию.</h1>
        <p>На Windows откройте «Система», создайте одноразовый код и вручную перенесите оттуда fingerprint сертификата. QR содержит только token. Код действует 10 минут и сгорает после первого использования.</p>
        <form onSubmit={(event) => { event.preventDefault(); pair.mutate() }}>
          <label>Название устройства<input value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" /></label>
          <label>Одноразовый token<input value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" spellCheck={false} /></label>
          <label>Fingerprint сертификата<textarea value={fingerprint} onChange={(event) => setFingerprint(event.target.value)} rows={3} spellCheck={false} /></label>
          {pair.error ? <ErrorNotice error={pair.error} /> : null}
          <button className="button button--primary" disabled={pair.isPending || token.length < 20 || fingerprint.length < 3}>
            {pair.isPending ? 'Проверяем…' : 'Привязать устройство'}
          </button>
        </form>
      </section>
    </main>
  )
}
