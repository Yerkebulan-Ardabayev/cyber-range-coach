import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

import {
  BookIcon,
  CompassIcon,
  EvidenceIcon,
  MenuIcon,
  NoteIcon,
  RepeatIcon,
  SettingsIcon,
  StudioIcon,
  TargetIcon,
  TerminalIcon,
} from '../icons'
import type { Principal } from '../types'
import { StatusPill } from './Common'

const navigation = [
  { to: '/', label: 'Сегодня', short: 'Сегодня', icon: CompassIcon },
  { to: '/learn', label: 'Академия', short: 'Учиться', icon: BookIcon },
  { to: '/range', label: 'Полигон', short: 'Полигон', icon: TargetIcon },
  { to: '/evidence', label: 'Доказательства', short: 'Факты', icon: EvidenceIcon },
  { to: '/reviews', label: 'Повторение', short: 'Повтор', icon: RepeatIcon },
  { to: '/notes', label: 'Полевые заметки', short: 'Заметки', icon: NoteIcon },
  { to: '/studio', label: 'Студия', short: 'Студия', icon: StudioIcon, ownerOnly: true },
  { to: '/settings', label: 'Система', short: 'Система', icon: SettingsIcon },
]

export function Layout({ principal, children }: { principal: Principal; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  const isLab = location.pathname.startsWith('/lab/')
  const items = navigation.filter((item) => !item.ownerOnly || principal.role === 'owner')
  return (
    <div className={`app-shell ${isLab ? 'app-shell--lab' : ''}`}>
      <aside className={`rail ${open ? 'rail--open' : ''}`}>
        <div className="brand-lockup">
          <span className="brand-mark"><TerminalIcon /></span>
          <div><strong>CYBER RANGE COACH</strong><span>учебная академия / v2</span></div>
        </div>
        <nav className="rail-nav" aria-label="Основная навигация">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} onClick={() => setOpen(false)}>
              <Icon /><span>{label}</span><b>↗</b>
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          <StatusPill status={principal.role === 'viewer' ? 'warning' : 'ok'}>{principal.role}</StatusPill>
          <p>{principal.local_owner ? 'локальный владелец' : 'привязанное устройство'}</p>
        </div>
      </aside>
      {open ? <button className="rail-scrim" aria-label="Закрыть меню" onClick={() => setOpen(false)} /> : null}
      <div className="app-body">
        <header className="topbar">
          <button className="icon-button menu-button" aria-label="Открыть меню" onClick={() => setOpen(true)}><MenuIcon /></button>
          <div className="topbar__route"><span>CRC // ЛОКАЛЬНАЯ АКАДЕМИЯ</span><strong>{isLab ? 'АКТИВНАЯ ЛАБОРАТОРИЯ' : 'ПОЛЕВОЙ ЖУРНАЛ'}</strong></div>
          <div className="topbar__right"><span className="connection-light" />ДОМАШНЯЯ СЕТЬ <kbd>⌘ K</kbd></div>
        </header>
        <main className="workspace">{children}</main>
      </div>
      {!isLab ? (
        <nav className="mobile-nav" aria-label="Мобильная навигация">
          {items.slice(0, 5).map(({ to, short, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'}><Icon /><span>{short}</span></NavLink>
          ))}
        </nav>
      ) : null}
    </div>
  )
}
