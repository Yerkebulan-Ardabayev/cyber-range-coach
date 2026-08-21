import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, jsonBody } from '../api'
import { ArrowIcon, CheckIcon, StudioIcon } from '../icons'
import type { Draft, StudioSource } from '../types'
import { EmptyState, ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, formatDate, shortHash } from '../components/Common'

export function StudioPage() {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [selectedSources, setSelectedSources] = useState<number[]>([])
  const [editingDraft, setEditingDraft] = useState<number | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftJson, setDraftJson] = useState('')
  const sources = useQuery({ queryKey: ['studio-sources'], queryFn: () => api<StudioSource[]>('/api/v2/studio/sources') })
  const drafts = useQuery({ queryKey: ['studio-drafts'], queryFn: () => api<Draft[]>('/api/v2/studio/drafts') })
  const upload = useMutation({
    mutationFn: async () => { const form = new FormData(); if (!file) throw new Error('Выберите файл'); form.append('file', file); return api<StudioSource>('/api/v2/studio/import', { method: 'POST', body: form }) },
    onSuccess: (source) => { setFile(null); setSelectedSources([source.id]); void queryClient.invalidateQueries({ queryKey: ['studio-sources'] }) },
  })
  const createDraft = useMutation({
    mutationFn: () => api<Draft>('/api/v2/studio/drafts', { method: 'POST', ...jsonBody({ title, source_ids: selectedSources }) }),
    onSuccess: (draft) => {
      setTitle('')
      setEditingDraft(draft.id)
      setDraftTitle(draft.title)
      setDraftJson(JSON.stringify(draft.content, null, 2))
      void queryClient.invalidateQueries({ queryKey: ['studio-drafts'] })
    },
  })
  const saveDraft = useMutation({
    mutationFn: ({ id, title: nextTitle, content }: { id: number; title: string; content: string }) => {
      const parsed: unknown = JSON.parse(content)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Содержимое должно быть JSON-объектом')
      return api<Draft>(`/api/v2/studio/drafts/${id}`, { method: 'PUT', ...jsonBody({ title: nextTitle, content: parsed }) })
    },
    onSuccess: () => {
      setEditingDraft(null)
      void queryClient.invalidateQueries({ queryKey: ['studio-drafts'] })
    },
  })
  const validate = useMutation({
    mutationFn: (id: number) => api<Draft>(`/api/v2/studio/drafts/${id}/validate`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['studio-drafts'] }),
  })
  const publish = useMutation({
    mutationFn: (id: number) => api<Draft>(`/api/v2/studio/drafts/${id}/publish`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['studio-drafts'] }),
  })
  const openEditor = (draft: Draft) => {
    setEditingDraft(draft.id)
    setDraftTitle(draft.title)
    setDraftJson(JSON.stringify(draft.content, null, 2))
  }
  const error = sources.error ?? drafts.error ?? upload.error ?? createDraft.error ?? saveDraft.error ?? validate.error ?? publish.error
  const statusLabel = { draft: 'черновик', validated: 'проверено', published: 'опубликовано' } as const
  return (
    <div className="page">
      <PageHeader kicker="СТУДИЯ / СНИМКИ ИСТОЧНИКОВ" title="Новый урок начинается с проверяемого источника." lead="Файл копируется в снимок только для чтения, получает SHA-256 и адресные блоки. Академия обнаруживает изменение снимка, не редактирует пользовательский оригинал и публикует материал только по решению владельца." action={<StatusPill status="warning">ТОЛЬКО ВЛАДЕЛЕЦ</StatusPill>} />
      {error ? <ErrorNotice error={error} /> : null}
      <div className="studio-workbench">
        <section className="import-bay">
          <div className="import-bay__icon"><StudioIcon /></div><Eyebrow>01 / ИМПОРТ</Eyebrow><h2>DOCX, MD, TXT, LOG или изображение</h2><p>Максимум 25 МБ. Для PNG, JPEG и TIFF нужен локальный Tesseract.</p>
          <label className="file-drop"><input type="file" accept=".docx,.md,.txt,.log,.png,.jpg,.jpeg,.tif,.tiff" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><span>{file ? file.name : 'Выберите исходный файл'}</span><small>{file ? `${Math.ceil(file.size / 1024)} КБ` : 'оригинал останется неизменным'}</small></label>
          <button className="button button--primary" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? 'Хэшируем и извлекаем…' : 'Создать снимок'} <ArrowIcon /></button>
        </section>
        <section className="source-vault"><div className="section-title"><div><Eyebrow>02 / ХРАНИЛИЩЕ ИСТОЧНИКОВ</Eyebrow><h2>Проверяемые снимки</h2></div><span>{sources.data?.length ?? 0}</span></div>{sources.isPending ? <LoadingBlock /> : null}<div className="source-list">{sources.data?.map((source) => <label key={source.id} className={selectedSources.includes(source.id) ? 'selected' : ''}><input type="checkbox" checked={selectedSources.includes(source.id)} onChange={() => setSelectedSources((current) => current.includes(source.id) ? current.filter((id) => id !== source.id) : [...current, source.id])} /><span className="source-list__check"><CheckIcon /></span><div><strong>{source.original_name}</strong><small>{source.extractor} · {source.block_count} блоков · {formatDate(source.created_at)}</small><code>{shortHash(source.sha256)}</code></div></label>)}</div>{!sources.isPending && !sources.data?.length ? <EmptyState index="S0" title="Хранилище пусто" text="Первый импорт создаст снимок и адресные блоки источника." /> : null}</section>
      </div>
      <section className="draft-composer"><div><Eyebrow>03 / ЧЕРНОВИК</Eyebrow><h2>Черновик со ссылками на каждый блок</h2><p>Первая версия сохраняет полное покрытие источника. Затем владелец сокращает и перестраивает материал, не теряя адресов.</p></div><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Название будущего урока" /><button className="button button--ink" disabled={title.trim().length < 2 || !selectedSources.length || createDraft.isPending} onClick={() => createDraft.mutate()}>Создать черновик</button></section>
      <section className="draft-ledger">
        <div className="section-title"><div><Eyebrow>04 / ПРОВЕРКА И ПУБЛИКАЦИЯ</Eyebrow><h2>Публикуется только проверенный черновик</h2></div></div>
        <div className="draft-grid">{drafts.data?.map((draft) => <article key={draft.id}>
          <header><span>ЧЕРНОВИК #{draft.id}</span><StatusPill status={draft.status === 'published' ? 'ok' : draft.status === 'validated' ? 'neutral' : 'warning'}>{statusLabel[draft.status]}</StatusPill></header>
          <h3>{draft.title}</h3>
          <dl><div><dt>Источники</dt><dd>{draft.source_ids.length}</dd></div><div><dt>Блоки</dt><dd>{draft.covered_block_ids.length}</dd></div></dl>
          {draft.validation_report.valid === false ? <small className="draft-warning">Проверка покрытия требует исправлений.</small> : null}
          <div className="button-row">
            <button className="button button--quiet" disabled={draft.status === 'published'} onClick={() => openEditor(draft)}>Проверить JSON</button>
            <button className="button button--quiet" disabled={draft.status === 'published' || validate.isPending} onClick={() => validate.mutate(draft.id)}>Проверить</button>
            <button className="button button--primary" disabled={draft.status !== 'validated' || publish.isPending} onClick={() => publish.mutate(draft.id)}>Опубликовать</button>
          </div>
        </article>)}</div>
        {editingDraft !== null ? <div className="draft-editor">
          <div><Eyebrow>ПРОВЕРКА ВЛАДЕЛЬЦА / ЧЕРНОВИК #{editingDraft}</Eyebrow><h3>Проверьте текст и ссылки source_block_ids</h3><p>Сохранение возвращает статус в черновик. После него снова выполните проверку.</p></div>
          <label><span>Название</span><input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} /></label>
          <label><span>Содержимое JSON</span><textarea value={draftJson} onChange={(event) => setDraftJson(event.target.value)} rows={22} spellCheck={false} /></label>
          <div className="button-row"><button className="button button--quiet" onClick={() => setEditingDraft(null)}>Закрыть</button><button className="button button--primary" disabled={draftTitle.trim().length < 2 || saveDraft.isPending} onClick={() => saveDraft.mutate({ id: editingDraft, title: draftTitle, content: draftJson })}>{saveDraft.isPending ? 'Сохраняем…' : 'Сохранить проверку'}</button></div>
        </div> : null}
      </section>
    </div>
  )
}
