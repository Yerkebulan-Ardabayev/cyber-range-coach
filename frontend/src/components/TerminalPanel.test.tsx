import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TerminalPanel } from './TerminalPanel'

describe('TerminalPanel safety', () => {
  it('never opens an interactive terminal for viewer', () => {
    render(<TerminalPanel runId={7} role="viewer" transcript="$ pwd\n/home/student" />)
    expect(screen.getByText('ТОЛЬКО ЧТЕНИЕ')).toBeInTheDocument()
    expect(screen.getByText(/\/home\/student/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Интерактивный терминал Linux VM')).not.toBeInTheDocument()
  })
})
