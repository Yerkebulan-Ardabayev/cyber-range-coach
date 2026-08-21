import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { api, ApiError } from './api'
import { Layout } from './components/Layout'
import { LoadingBlock } from './components/Common'
import { PairingView } from './components/PairingView'
import { EvidencePage } from './pages/EvidencePage'
import { LabPage } from './pages/LabPage'
import { LearnPage } from './pages/LearnPage'
import { LessonPage } from './pages/LessonPage'
import { NotesPage } from './pages/NotesPage'
import { RangePage } from './pages/RangePage'
import { ReviewsPage } from './pages/ReviewsPage'
import { SettingsPage } from './pages/SettingsPage'
import { StudioPage } from './pages/StudioPage'
import { TodayPage } from './pages/TodayPage'
import type { Principal } from './types'

export function App() {
  const principal = useQuery({
    queryKey: ['principal'],
    queryFn: () => api<Principal>('/api/v2/devices/me'),
    retry: false,
  })
  if (principal.isPending) return <div className="boot-screen"><LoadingBlock label="Открываем локальный журнал" /></div>
  if (principal.error instanceof ApiError && principal.error.status === 401) return <PairingView />
  if (!principal.data) return <PairingView />
  return (
    <Layout principal={principal.data}>
      <Routes>
        <Route path="/" element={<TodayPage principal={principal.data} />} />
        <Route path="/learn" element={<LearnPage principal={principal.data} />} />
        <Route path="/lesson/:lessonId" element={<LessonPage principal={principal.data} />} />
        <Route path="/lab/:runId" element={<LabPage principal={principal.data} />} />
        <Route path="/range" element={<RangePage principal={principal.data} />} />
        <Route path="/evidence" element={<EvidencePage />} />
        <Route path="/reviews" element={<ReviewsPage />} />
        <Route path="/notes" element={<NotesPage principal={principal.data} />} />
        <Route path="/studio" element={principal.data.role === 'owner' ? <StudioPage /> : <Navigate to="/" replace />} />
        <Route path="/settings" element={<SettingsPage principal={principal.data} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
