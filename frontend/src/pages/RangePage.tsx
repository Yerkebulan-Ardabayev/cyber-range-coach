import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, jsonBody } from '../api'
import { ArrowIcon, CheckIcon, TargetIcon } from '../icons'
import type { DiscoveredTarget, Preflight, Principal, PublishedPort, Target, TargetVerification } from '../types'
import { EmptyState, ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, formatDate, shortHash } from '../components/Common'

const targetTags = ['web', 'authentication', 'access-control']
const targetTagLabels: Record<string, string> = { web: 'веб', authentication: 'аутентификация', 'access-control': 'контроль доступа' }
const containerStateLabels: Record<string, string> = { running: 'работает', exited: 'остановлен', created: 'создан', restarting: 'перезапускается' }
const exposureLabels: Record<string, string> = { loopback: 'только Windows', lan: 'локальная сеть', unknown: 'неизвестно' }

function DiscoveryCard({ item }: { item: DiscoveredTarget }) {
  const queryClient = useQueryClient()
  const firstTcp = item.ports.find((port) => port.protocol === 'tcp') ?? null
  const [selected, setSelected] = useState<PublishedPort | null>(firstTcp)
  const [tags, setTags] = useState<string[]>(item.detected_kind === 'generic' ? ['web'] : targetTags)
  const add = useMutation({
    mutationFn: () => api<Target>('/api/v2/targets', {
      method: 'POST',
      ...jsonBody({ container_id: item.container_id, container_port: selected?.container_port, protocol: 'tcp', display_name: item.name, allowed_curriculum_tags: tags }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['targets'] }),
  })
  return (
    <article className="discovery-card">
      <div className="discovery-card__head"><span className={`container-kind container-kind--${item.detected_kind}`}><TargetIcon /></span><div><Eyebrow>{item.detected_kind === 'generic' ? 'ОБЫЧНАЯ ЦЕЛЬ' : item.detected_kind.replace('_', ' ')}</Eyebrow><h3>{item.name}</h3><p>{item.image}</p></div><StatusPill status={item.state === 'running' ? 'ok' : 'blocked'}>{containerStateLabels[item.state] ?? item.state}</StatusPill></div>
      <div className="port-list">
        {item.ports.length ? item.ports.map((port) => <button key={`${port.container_port}-${port.host_port}`} className={selected?.host_port === port.host_port ? 'active' : ''} onClick={() => setSelected(port)}><strong>{port.host_ip}:{port.host_port}</strong><span>→ {port.container_port}/{port.protocol}</span><small>{exposureLabels[port.exposure]}</small></button>) : <p>Нет опубликованных портов.</p>}
      </div>
      {item.warnings.map((warning) => <p className="inline-warning" key={warning}>{warning}</p>)}
      <div className="tag-picker"><span>Разрешить уроки:</span>{targetTags.map((tag) => <label key={tag}><input type="checkbox" checked={tags.includes(tag)} onChange={() => setTags((current) => current.includes(tag) ? current.filter((value) => value !== tag) : [...current, tag])} />{targetTagLabels[tag]}</label>)}</div>
      {add.error ? <ErrorNotice error={add.error} /> : null}
      <button className="button button--ink" disabled={!selected || add.isPending} onClick={() => add.mutate()}>{add.isPending ? 'Сверяем Docker inspect…' : 'Подтвердить профиль'} <ArrowIcon /></button>
    </article>
  )
}

function RegisteredTarget({ target, owner }: { target: Target; owner: boolean }) {
  const verify = useMutation({ mutationFn: () => api<TargetVerification>(`/api/v2/targets/${target.id}/verify`, { method: 'POST' }) })
  return (
    <article className="registered-target">
      <div className="registered-target__status"><span className="connection-light" /><strong>{target.display_name}</strong></div>
      <dl><div><dt>Адрес на Windows</dt><dd>{target.host_endpoint}</dd></div><div><dt>Отпечаток цели</dt><dd><code>{shortHash(target.fingerprint)}</code></dd></div><div><dt>Последняя проверка</dt><dd>{formatDate(target.last_verified_at)}</dd></div><div><dt>Политика сброса</dt><dd>{target.reset_policy === 'manual' ? 'вручную владельцем' : target.reset_policy}</dd></div></dl>
      <div className="tag-row">{target.allowed_curriculum_tags.map((tag) => <span key={tag}>{targetTagLabels[tag] ?? tag}</span>)}</div>
      {target.exposure_warnings.map((warning) => <p className="inline-warning" key={warning}>{warning}</p>)}
      {owner ? <button className="button button--quiet" onClick={() => verify.mutate()} disabled={verify.isPending}>Проверить без изменения</button> : null}
      {verify.error ? <ErrorNotice error={verify.error} /> : null}
      {verify.data ? <div className={`verification-result ${verify.data.reachable ? 'ok' : 'bad'}`}><strong>{verify.data.reachable ? 'Доступна' : 'Недоступна'}</strong><span>{verify.data.detail}</span>{verify.data.http_response_received ? <small>HTTP {verify.data.http_status}</small> : <small>HTTP-ответ не получен</small>}</div> : null}
    </article>
  )
}

export function RangePage({ principal }: { principal: Principal }) {
  const owner = principal.role === 'owner'
  const targets = useQuery({ queryKey: ['targets'], queryFn: () => api<Target[]>('/api/v2/targets') })
  const preflight = useQuery({ queryKey: ['preflight'], queryFn: () => api<Preflight>('/api/v2/system/preflight'), enabled: owner })
  const discovery = useQuery({ queryKey: ['docker-discovery'], queryFn: () => api<DiscoveredTarget[]>('/api/v2/targets/discover'), enabled: false })
  return (
    <div className="page">
      <PageHeader kicker="УПРАВЛЕНИЕ ПОЛИГОНОМ / СНАЧАЛА ПРОЧИТАЙТЕ" title="Ваши контейнеры остаются вашими." lead="Академия читает метаданные Docker, создаёт подтверждённый профиль и не запускает, не останавливает и не пересоздаёт пользовательские контейнеры." action={<StatusPill status={targets.data?.length ? 'ok' : 'warning'}>{targets.data?.length ?? 0} целей</StatusPill>} />
      {owner && preflight.data ? <section className="preflight-ribbon">{preflight.data.checks.slice(0, 5).map((check) => <div key={check.id} className={`preflight-mini preflight-mini--${check.status}`}><span>{check.status === 'ok' ? <CheckIcon /> : '!'}</span><div><strong>{check.title}</strong><small>{check.detail}</small></div></div>)}</section> : null}
      <section className="section-block">
        <div className="section-title"><div><Eyebrow>ПОДТВЕРЖДЁННЫЕ ПРОФИЛИ</Eyebrow><h2>Цели, которые разрешено подставлять в урок</h2></div>{owner ? <button className="button button--primary" onClick={() => discovery.refetch()} disabled={discovery.isFetching}>{discovery.isFetching ? 'Читаем Docker…' : 'Обнаружить контейнеры'}</button> : null}</div>
        {targets.isPending ? <LoadingBlock /> : null}
        {targets.error ? <ErrorNotice error={targets.error} /> : null}
        <div className="registered-grid">{targets.data?.map((target) => <RegisteredTarget key={target.id} target={target} owner={owner} />)}</div>
        {!targets.isPending && !targets.data?.length ? <EmptyState index="00" title="Пока нет подтверждённых целей" text={owner ? 'Запустите read-only discovery. Docker Compose и volumes не изменятся.' : 'Владелец Windows ещё не подтвердил ни один контейнер.'} /> : null}
      </section>
      {owner && (discovery.data || discovery.error) ? <section className="section-block section-block--dark"><div className="section-title"><div><Eyebrow>ПОИСК DOCKER-ЦЕЛЕЙ</Eyebrow><h2>Найдено в текущем контексте Windows</h2></div><span>docker ps + inspect</span></div>{discovery.error ? <ErrorNotice error={discovery.error} /> : null}<div className="discovery-grid">{discovery.data?.map((item) => <DiscoveryCard key={item.container_id} item={item} />)}</div></section> : null}
    </div>
  )
}
