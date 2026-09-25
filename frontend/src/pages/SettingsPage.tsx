import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { useEffect, useMemo, useState } from 'react'

import { api, jsonBody } from '../api'
import { CheckIcon, SettingsIcon } from '../icons'
import type { Device, LinuxHost, PairingCreated, Preflight, Principal, WslUbuntuPrepare } from '../types'
import { ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, formatDate } from '../components/Common'
import { canCreatePairing, missingRunnerTools, preferredPairingOrigin, type RunnerToolsEvidence } from '../settings'

interface NetworkInterface { address: string; private: boolean; loopback: boolean }
interface NetworkInfo { bind_host: string; port: number; lan_mode: boolean; tls_enabled: boolean; academy_urls: string[]; interfaces: NetworkInterface[] }
interface LinuxProbe { host_id: number; tcp_reachable: boolean; ssh_authenticated: boolean; fingerprint: string | null; host_key: string | null; detail: string }

export function SettingsPage({ principal }: { principal: Principal }) {
  const owner = principal.role === 'owner'
  const queryClient = useQueryClient()
  const network = useQuery({ queryKey: ['network'], queryFn: () => api<NetworkInfo>('/api/v2/system/network') })
  const preflight = useQuery({ queryKey: ['preflight'], queryFn: () => api<Preflight>('/api/v2/system/preflight'), enabled: owner })
  const linux = useQuery({ queryKey: ['linux-host'], queryFn: () => api<LinuxHost | null>('/api/v2/system/linux-host'), enabled: owner })
  const devices = useQuery({ queryKey: ['devices'], queryFn: () => api<Device[]>('/api/v2/devices'), enabled: owner })
  const wslPreset = { name: 'WSL Ubuntu', host: '127.0.0.1', port: 22, relay_source_ip: '', username: 'student', runner_username: 'range-runner' }
  const [linuxForm, setLinuxForm] = useState(wslPreset)
  const [fingerprint, setFingerprint] = useState('')
  const [pairRole, setPairRole] = useState<'operator' | 'viewer'>('viewer')
  useEffect(() => { if (linux.data) setLinuxForm({ name: linux.data.name, host: linux.data.host, port: linux.data.port, relay_source_ip: linux.data.relay_source_ip ?? '', username: linux.data.username, runner_username: linux.data.runner_username }) }, [linux.data])
  const configure = useMutation({
    mutationFn: () => api<LinuxHost>('/api/v2/system/linux-host', { method: 'POST', ...jsonBody({ ...linuxForm, relay_source_ip: linuxForm.relay_source_ip || null }) }),
    onSuccess: (value) => queryClient.setQueryData(['linux-host'], value),
  })
  const prepareWsl = useMutation({
    mutationFn: async () => {
      const profile = await api<LinuxHost>('/api/v2/system/linux-host', { method: 'POST', ...jsonBody({ ...wslPreset, relay_source_ip: null }) })
      queryClient.setQueryData(['linux-host'], profile)
      setLinuxForm(wslPreset)
      return api<WslUbuntuPrepare>(`/api/v2/system/linux-host/${profile.id}/wsl-ubuntu/prepare`, { method: 'POST' })
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['preflight'] }) },
  })
  const probe = useMutation({
    mutationFn: () => api<LinuxProbe>(`/api/v2/system/linux-host/${linux.data?.id}/probe`, { method: 'POST' }),
    onSuccess: (value) => setFingerprint(value.fingerprint ?? ''),
  })
  const confirm = useMutation({
    mutationFn: () => api<LinuxHost>(`/api/v2/system/linux-host/${linux.data?.id}/confirm`, { method: 'POST', ...jsonBody({ fingerprint }) }),
    onSuccess: (value) => { queryClient.setQueryData(['linux-host'], value); void queryClient.invalidateQueries({ queryKey: ['preflight'] }) },
  })
  const runnerCheck = useMutation({
    mutationFn: () => api<RunnerToolsEvidence>(`/api/v2/system/linux-host/${linux.data?.id}/runner-check`, { method: 'POST' }),
  })
  const pairing = useMutation({ mutationFn: () => api<PairingCreated>('/api/v2/devices/pairing-codes', { method: 'POST', ...jsonBody({ role: pairRole }) }) })
  const revoke = useMutation({
    mutationFn: (id: number) => api<Device>(`/api/v2/devices/${id}/revoke`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['devices'] }),
  })
  const pairingOrigin = preferredPairingOrigin(network.data?.academy_urls)
  const pairingReady = canCreatePairing(pairingOrigin, preflight.data?.ready === true, network.data?.lan_mode === true, network.data?.tls_enabled === true)
  const pairingUrl = useMemo(() => pairing.data && pairingOrigin && pairingReady ? `${pairingOrigin}/?pairToken=${encodeURIComponent(pairing.data.token)}` : '', [pairing.data, pairingOrigin, pairingReady])
  const missingTools = missingRunnerTools(runnerCheck.data)
  const error = network.error ?? preflight.error ?? linux.error ?? devices.error ?? configure.error ?? prepareWsl.error ?? probe.error ?? confirm.error ?? runnerCheck.error ?? pairing.error ?? revoke.error
  if (!owner) return <div className="page"><PageHeader kicker="ПРОФИЛЬ УСТРОЙСТВА" title="Системные изменения принадлежат владельцу Windows." lead="Это устройство может читать состояние, но не меняет Linux VM, профили Docker, сертификаты, Firewall или роли привязки." action={<StatusPill status="warning">{principal.role}</StatusPill>} /><section className="paper-card"><Eyebrow>ТЕКУЩЕЕ УСТРОЙСТВО</Eyebrow><h2>{principal.role}</h2><p>{principal.local_owner ? 'Локальный владелец Windows.' : 'Привязанное устройство домашней сети.'}</p><dl className="fact-list"><div><dt>Режим LAN</dt><dd>{network.data?.lan_mode ? 'включён' : 'выключен'}</dd></div><div><dt>TLS</dt><dd>{network.data?.tls_enabled ? 'включён' : 'выключен'}</dd></div></dl></section></div>
  const relayHost = network.data?.interfaces.find((item) => item.private && !item.loopback && !item.address.includes(':'))?.address ?? '<WINDOWS_PRIVATE_IP>'
  const bootstrapCommand = linux.data ? `sudo bash bootstrap-linux.sh --student-user '${linux.data.username}' --runner-user '${linux.data.runner_username}' --student-key '${linux.data.public_key}' --runner-key '${linux.data.runner_public_key}' --relay-host '${relayHost}'` : ''
  return (
    <div className="page">
      <PageHeader kicker="СИСТЕМА / КОНСОЛЬ ВЛАДЕЛЬЦА" title="Сначала доказать маршрут, потом открыть лабораторию." lead="Этот раздел читает состояние и готовит явные шаги. Он не устанавливает OpenSSH, не меняет Firewall и не трогает Docker без отдельного действия владельца." action={<StatusPill status={preflight.data?.ready ? 'ok' : 'warning'}>{preflight.data?.ready ? 'ГОТОВО' : 'ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА'}</StatusPill>} />
      {error ? <ErrorNotice error={error} /> : null}
      {preflight.isPending ? <LoadingBlock label="Выполняем предварительную проверку без изменений" /> : null}
      <section className="system-grid">{preflight.data?.checks.map((check, index) => <article key={check.id} className={`system-check system-check--${check.status}`}><span>{String(index + 1).padStart(2, '0')}</span><div><Eyebrow>{{ ok: 'ГОТОВО', warning: 'ВНИМАНИЕ', blocked: 'БЛОКИРОВАНО', unavailable: 'НЕДОСТУПНО' }[check.status]}</Eyebrow><h2>{check.title}</h2><p>{check.detail}</p>{check.action ? <small>{check.action}</small> : null}</div>{check.status === 'ok' ? <CheckIcon /> : <b>!</b>}</article>)}</section>
      <section className="settings-section">
        <div className="settings-section__intro"><span><SettingsIcon /></span><div><Eyebrow>LINUX VM / SSH</Eyebrow><h2>Две роли, один подтверждённый ключ сервера</h2><p>`student` получает интерактивный терминал. `range-runner` выполняет только разрешённые проверки и не должен получать обычный shell.</p></div></div>
        <div className="linux-setup">
          <div className="setup-step"><span>1</span><div><h3>Готовый профиль WSL Ubuntu</h3><p>Основной вариант использует `127.0.0.1:22`, `student` и `range-runner`. Мастер создаёт два SSH-ключа, помещает проверяемые скрипты внутрь Ubuntu и устанавливает только отсутствующие учебные пакеты. Docker Desktop, контейнеры, images и volumes не изменяются.</p><div className="button-row"><button className="button button--primary" disabled={prepareWsl.isPending} onClick={() => prepareWsl.mutate()}>{prepareWsl.isPending ? 'Подготавливаем WSL Ubuntu…' : 'Подготовить WSL Ubuntu'}</button><button className="button button--quiet" onClick={() => setLinuxForm(wslPreset)}>Заполнить WSL-профиль</button></div>{prepareWsl.data ? <><StatusPill status={prepareWsl.data.status === 'ready_for_probe' ? 'ok' : prepareWsl.data.status === 'sudo_password_required' ? 'warning' : 'blocked'}>{prepareWsl.data.detail}</StatusPill>{prepareWsl.data.relay_source_ip ? <small>Текущий WSL source IP для Relay: {prepareWsl.data.relay_source_ip}</small> : null}{prepareWsl.data.sudo_command ? <label>Выполнить внутри Ubuntu и ввести свой sudo-пароль<textarea readOnly value={prepareWsl.data.sudo_command} rows={9} /></label> : null}</> : null}<h3>Другой Linux-хост</h3><p>Если SSH использует hostname, укажите отдельный фактический IPv4-адрес Linux VM для allowlist Training Relay.</p><div className="form-grid"><label>IP или имя SSH-хоста<input value={linuxForm.host} onChange={(event) => setLinuxForm({ ...linuxForm, host: event.target.value })} placeholder="linux-vm.local" /></label><label>Порт SSH<input type="number" value={linuxForm.port} onChange={(event) => setLinuxForm({ ...linuxForm, port: Number(event.target.value) })} /></label><label>IP источника Relay<input value={linuxForm.relay_source_ip} onChange={(event) => setLinuxForm({ ...linuxForm, relay_source_ip: event.target.value })} placeholder="192.168.x.x" /></label><label>Учебный пользователь<input value={linuxForm.username} onChange={(event) => setLinuxForm({ ...linuxForm, username: event.target.value })} /></label><label>Проверяющий пользователь<input value={linuxForm.runner_username} onChange={(event) => setLinuxForm({ ...linuxForm, runner_username: event.target.value })} /></label></div><button className="button button--ink" disabled={!linuxForm.host || configure.isPending} onClick={() => configure.mutate()}>Создать новые ключи</button></div></div>
          <div className={`setup-step ${linux.data ? '' : 'setup-step--locked'}`}><span>2</span><div><h3>Настроить две роли внутри Linux</h3><p>Если WSL запросил sudo-пароль, это пароль вашего обычного пользователя Ubuntu. Он вводится только в Ubuntu, академия его не видит и не сохраняет. Для отдельной VM скачайте скрипты, проверьте их и выполните команду вручную.</p>{linux.data ? <><div className="button-row"><a className="button button--quiet" href="/api/v2/system/linux-bootstrap/bootstrap-wsl-ubuntu.sh">bootstrap-wsl-ubuntu.sh</a><a className="button button--quiet" href="/api/v2/system/linux-bootstrap/bootstrap-linux.sh">bootstrap-linux.sh</a><a className="button button--quiet" href="/api/v2/system/linux-bootstrap/crc-range-check">crc-range-check</a></div><label>Команда для отдельной Linux VM<textarea readOnly value={bootstrapCommand} rows={8} /></label></> : null}</div></div>
          <div className={`setup-step ${linux.data ? '' : 'setup-step--locked'}`}><span>3</span><div><h3>Проверка SSH и сверка отпечатка</h3><p>Первая проверка использует аутентификацию по ключу, но ещё не доверяет ключу сервера. Сравните отпечаток с выводом команды, которую покажет проверка: она называет тип ключа сервера и файл для сверки внутри Linux.</p><div className="button-row"><button className="button button--quiet" disabled={!linux.data || probe.isPending} onClick={() => probe.mutate()}>Проверить SSH</button>{probe.data ? <StatusPill status={probe.data.ssh_authenticated ? 'ok' : 'blocked'}>{probe.data.detail}</StatusPill> : null}{probe.error ? <ErrorNotice error={probe.error} /> : null}</div><label>Подтверждаемый отпечаток<input value={fingerprint} onChange={(event) => setFingerprint(event.target.value)} spellCheck={false} /></label><div className="button-row"><button className="button button--primary" disabled={!linux.data || !fingerprint || confirm.isPending} onClick={() => confirm.mutate()}>Подтвердить отпечаток</button><button className="button button--quiet" disabled={!linux.data?.confirmed || runnerCheck.isPending} onClick={() => runnerCheck.mutate()}>Проверить range-runner</button>{runnerCheck.data ? <StatusPill status={missingTools.length === 0 ? 'ok' : 'blocked'}>{missingTools.length === 0 ? 'все инструменты доступны' : `не хватает: ${missingTools.join(', ')}`}</StatusPill> : null}{runnerCheck.error ? <ErrorNotice error={runnerCheck.error} /> : null}</div></div></div>
        </div>
      </section>
      <section className="settings-split">
        <div className="pairing-console"><Eyebrow>ПРИВЯЗКА УСТРОЙСТВА</Eyebrow><h2>Mac или телефон</h2><div className="segmented"><button className={pairRole === 'viewer' ? 'active' : ''} onClick={() => setPairRole('viewer')}>чтение</button><button className={pairRole === 'operator' ? 'active' : ''} onClick={() => setPairRole('operator')}>оператор</button></div><button className="button button--primary" disabled={!pairingReady || pairing.isPending} onClick={() => pairing.mutate()}>Создать токен на 10 минут</button>{!pairingReady ? <p>QR недоступен до полного HTTPS preflight: нужны LAN mode, TLS, адрес домашней сети, сертификат с актуальным SAN и активный профиль Private.</p> : null}{pairing.data && pairingUrl ? <div className="pairing-ticket"><QRCodeSVG value={pairingUrl} size={180} bgColor="#f3ead2" fgColor="#101716" level="M" /><div><small>Одноразовый токен (есть в QR)</small><code>{pairing.data.token}</code><small>Отпечаток сертификата (сверить вручную, в QR его нет)</small><code>{pairing.data.certificate_fingerprint}</code><span>до {formatDate(pairing.data.expires_at)}</span></div></div> : null}<a className="quiet-link" href="/api/v2/system/ca-certificate">Скачать публичный CA-сертификат</a></div>
        <div className="network-console"><Eyebrow>ДОМАШНЯЯ СЕТЬ</Eyebrow><h2>Адреса академии</h2>{network.data?.academy_urls.map((url) => <code key={url}>{url}</code>)}<dl className="fact-list"><div><dt>Привязка</dt><dd>{network.data?.bind_host}:{network.data?.port}</dd></div><div><dt>TLS</dt><dd>{network.data?.tls_enabled ? 'включён' : 'выключен'}</dd></div><div><dt>LAN</dt><dd>{network.data?.lan_mode ? 'включён' : 'выключен'}</dd></div></dl><p>Публичный профиль, UPnP и перенаправление портов приложением не включаются.</p></div>
      </section>
      <section className="settings-split">
        <div className="device-ledger"><div className="section-title"><div><Eyebrow>ПРИВЯЗАННЫЕ УСТРОЙСТВА</Eyebrow><h2>Доступ можно отозвать</h2></div><span>{devices.data?.length ?? 0}</span></div>{devices.data?.map((device) => <article key={device.id}><div><strong>{device.name}</strong><span>{{ owner: 'владелец', operator: 'оператор', viewer: 'чтение' }[device.role]} · {formatDate(device.last_seen_at)}</span></div><StatusPill status={device.revoked_at ? 'blocked' : 'ok'}>{device.revoked_at ? 'отозвано' : 'активно'}</StatusPill>{!device.revoked_at ? <button onClick={() => revoke.mutate(device.id)}>отозвать</button> : null}</article>)}</div>
        <div className="ai-console"><Eyebrow>МЕТОДИЧЕСКИЙ НАСТАВНИК</Eyebrow><h2>Подсказки работают локально</h2><p>Windows-релиз использует подготовленные сократические подсказки. Внешние Codex CLI и Claude Code отключены: текущая Windows-модель изоляции не доказывает отсутствие чтения других локальных файлов.</p><StatusPill status="neutral">ВНЕШНИЙ AI ОТКЛЮЧЁН</StatusPill></div>
      </section>
    </div>
  )
}
