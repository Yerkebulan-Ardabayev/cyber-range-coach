import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Layout } from './Layout'

describe('Layout roles', () => {
  it('shows Studio only to the owner', () => {
    const { rerender } = render(
      <MemoryRouter>
        <Layout principal={{ role: 'viewer', device_id: 1, local_owner: false }}>
          <p>content</p>
        </Layout>
      </MemoryRouter>,
    )
    expect(screen.queryByRole('link', { name: /Студия/ })).not.toBeInTheDocument()

    rerender(
      <MemoryRouter>
        <Layout principal={{ role: 'owner', device_id: null, local_owner: true }}>
          <p>content</p>
        </Layout>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /Студия/ })).toBeInTheDocument()
  })
})
