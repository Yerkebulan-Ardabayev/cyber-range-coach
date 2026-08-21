import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { api, jsonBody } from '../api'
import { NoteIcon } from '../icons'
import type { Note, Principal } from '../types'
import { EmptyState, ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, formatDate } from '../components/Common'

export function NotesPage({ principal }: { principal: Principal }) {
  const queryClient = useQueryClient()
  const notes = useQuery({ queryKey: ['notes'], queryFn: () => api<Note[]>('/api/v2/notes') })
  const [selected, setSelected] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const dirty = useRef(false)
  const active = notes.data?.find((note) => note.id === selected) ?? null
  useEffect(() => {
    if (selected === null && notes.data?.length) setSelected(notes.data[0].id)
  }, [notes.data, selected])
  useEffect(() => {
    if (active) { setTitle(active.title); setBody(active.body); dirty.current = false }
  }, [active?.id])
  const save = useMutation({
    mutationFn: () => api<Note>(`/api/v2/notes/${selected}`, { method: 'PUT', ...jsonBody({ title, body, lesson_id: active?.lesson_id ?? null, run_id: active?.run_id ?? null }) }),
    onSuccess: (saved) => { dirty.current = false; queryClient.setQueryData<Note[]>(['notes'], (current) => current?.map((item) => item.id === saved.id ? saved : item) ?? [saved]) },
  })
  useEffect(() => {
    if (!dirty.current || principal.role === 'viewer' || selected === null || !title.trim() || !body.trim()) return
    const timeout = window.setTimeout(() => save.mutate(), 900)
    return () => window.clearTimeout(timeout)
  }, [title, body, selected, principal.role])
  const create = useMutation({
    mutationFn: () => api<Note>('/api/v2/notes', { method: 'POST', ...jsonBody({ title: 'Новая полевая заметка', body: '## Наблюдение\n\n', lesson_id: null, run_id: null }) }),
    onSuccess: (note) => { queryClient.setQueryData<Note[]>(['notes'], (current) => [note, ...(current ?? [])]); setSelected(note.id) },
  })
  return (
    <div className="page page--notes">
      <PageHeader kicker="ПОЛЕВЫЕ ЗАМЕТКИ" title="Собственная память, связанная с опытом." lead="Заметка не считается доказательством сама по себе. Она помогает сохранить цель, наблюдение, ограничение и следующий тест между сессиями." action={<StatusPill status={save.isPending ? 'warning' : 'ok'}>{save.isPending ? 'сохраняем' : 'автосохранение'}</StatusPill>} />
      {notes.isPending ? <LoadingBlock /> : null}
      {notes.error || save.error || create.error ? <ErrorNotice error={notes.error ?? save.error ?? create.error} /> : null}
      {!notes.isPending && !notes.data?.length && principal.role === 'viewer' ? <EmptyState index="N0" title="Заметок ещё нет" text="Создать первую заметку можно с Windows или Mac в роли operator." /> : null}
      <div className="notes-desk">
        <aside className="note-index">
          <div className="note-index__head"><Eyebrow>ИНДЕКС</Eyebrow>{principal.role !== 'viewer' ? <button onClick={() => create.mutate()}>+ новая</button> : null}</div>
          {notes.data?.map((note) => <button key={note.id} className={selected === note.id ? 'active' : ''} onClick={() => setSelected(note.id)}><span><NoteIcon /></span><div><strong>{note.title}</strong><small>{formatDate(note.updated_at)}</small></div>{note.source_v1_id ? <b>v1</b> : null}</button>)}
        </aside>
        <section className="note-paper">
          {active ? <><div className="note-paper__meta"><span>ЗАМЕТКА #{active.id}</span><span>{active.lesson_id ?? 'без урока'}</span><span>{active.source_v1_id ? `импорт v1 #${active.source_v1_id}` : 'создано в v2'}</span></div><input className="note-title" value={title} onChange={(event) => { dirty.current = true; setTitle(event.target.value) }} disabled={principal.role === 'viewer'} aria-label="Заголовок заметки" /><textarea value={body} onChange={(event) => { dirty.current = true; setBody(event.target.value) }} disabled={principal.role === 'viewer'} aria-label="Текст заметки" spellCheck /></> : <div className="note-paper__empty"><NoteIcon /><h2>Выберите запись в индексе</h2></div>}
        </section>
      </div>
    </div>
  )
}
