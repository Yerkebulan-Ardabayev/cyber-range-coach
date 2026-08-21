import { expect, test, type Page } from '@playwright/test'

const widths = [360, 390, 480, 768, 1024, 1366, 1440, 1920, 2560]

async function mockAcademy(page: Page) {
  await page.route('**/api/v2/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const bodies: Record<string, unknown> = {
      '/api/v2/devices/me': { role: 'owner', device_id: null, local_owner: true },
      '/api/v2/lab-runs': [],
      '/api/v2/reviews': [],
      '/api/v2/evidence': [],
      '/api/v2/sessions': [],
      '/api/v2/curriculum': { tracks: [], lessons: [] },
    }
    const key = path === '/api/v2/lab-runs' ? path : path
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(bodies[key] ?? []),
    })
  })
}

async function mockSavedSession(page: Page) {
  await page.route('**/api/v2/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path === '/api/v2/devices/me') {
      body = { role: 'owner', device_id: null, local_owner: true }
    } else if (path === '/api/v2/sessions') {
      body = [{ id: 7, duration_minutes: 45, lesson_ids: ['linux-navigation-pwd'], status: 'planned', current_lesson_id: null, created_at: '2026-08-20T00:00:00Z', started_at: null, completed_at: null }]
    } else if (path === '/api/v2/curriculum') {
      body = { tracks: [], lessons: [{ id: 'linux-navigation-pwd', order: 20, title: 'Где я нахожусь в Linux', summary: 'Ориентация перед действием', estimated_minutes: 15, skill_id: 'linux-navigation', stage: 'guided', target_tags: [], requires_target: false }] }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function mockNotes(page: Page) {
  await page.route('**/api/v2/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path === '/api/v2/devices/me') {
      body = { role: 'owner', device_id: null, local_owner: true }
    } else if (path === '/api/v2/notes' || path === '/api/v2/notes/1') {
      const requestBody = route.request().method() === 'PUT' ? route.request().postDataJSON() as Record<string, unknown> : null
      body = path.endsWith('/1')
        ? { id: 1, title: requestBody?.title, body: requestBody?.body, lesson_id: null, run_id: null, source_v1_id: null, source_hash: null, created_at: '2026-08-20T00:00:00Z', updated_at: '2026-08-20T00:01:00Z' }
        : [{ id: 1, title: 'Проверка autosave', body: 'Исходный текст', lesson_id: null, run_id: null, source_v1_id: null, source_hash: null, created_at: '2026-08-20T00:00:00Z', updated_at: '2026-08-20T00:00:00Z' }]
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function mockLab(page: Page) {
  await page.addInitScript(() => {
    class AcademyTestWebSocket extends EventTarget {
      static readonly OPEN = 1
      static readonly CLOSED = 3
      readyState = AcademyTestWebSocket.OPEN

      constructor(url: string) {
        super()
        void url
        window.setTimeout(() => this.dispatchEvent(new Event('open')), 0)
      }

      send() {}

      close() {
        this.readyState = AcademyTestWebSocket.CLOSED
        this.dispatchEvent(new Event('close'))
      }
    }
    Object.defineProperty(window, 'WebSocket', { configurable: true, value: AcademyTestWebSocket })
  })
  await page.route('**/api/v2/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path === '/api/v2/devices/me') {
      body = { role: 'owner', device_id: null, local_owner: true }
    } else if (path === '/api/v2/lab-runs/1') {
      body = {
        id: 1, session_id: 1, lesson_id: 'linux-navigation-pwd', skill_id: 'linux-navigation',
        target_id: null, target_fingerprint: null, status: 'active', prediction: 'Увижу абсолютный путь',
        explanation: null, tutor_feedback_at: null, tutor_question: null, tutor_explanation: null,
        correction: null, transcript: '$ pwd\n/home/student\n', terminal_inputs: ['pwd'], grader_status: null,
        grader_report: {}, relay_port: null, created_at: '2026-08-20T00:00:00Z', stopped_at: null,
      }
    } else if (path === '/api/v2/lab-runs/1/lesson') {
      body = {
        id: 'linux-navigation-pwd', order: 20, title: 'Где я нахожусь в Linux',
        summary: 'Ориентация перед действием', estimated_minutes: 15, skill_id: 'linux-navigation',
        stage: 'guided', target_tags: [], requires_target: false,
        term: { name: 'абсолютный путь', definition: 'Полный адрес от корня.' },
        worked_example: 'pwd', prediction_question: 'Что увидим?', command: 'pwd',
        rendered_command: 'pwd', variables: {}, command_explanation: ['Команда ничего не меняет.'],
        explanation_prompt: 'Что доказал вывод?', review_question: 'Какая команда показывает каталог?',
      }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function mockStudio(page: Page) {
  await page.route('**/api/v2/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path === '/api/v2/devices/me') {
      body = { role: 'owner', device_id: null, local_owner: true }
    } else if (path === '/api/v2/studio/sources') {
      body = [{
        id: 1, original_name: 'lesson.md', stored_name: 'snapshot.md', media_type: 'text/markdown',
        sha256: 'a'.repeat(64), size_bytes: 1200, extractor: 'markdown', immutable_ok: true,
        created_at: '2026-08-20T00:00:00Z', block_count: 1,
      }]
    } else if (path === '/api/v2/studio/drafts') {
      body = [{
        id: 1, title: 'Факт, гипотеза и доказательство', source_ids: [1], covered_block_ids: [1],
        content: { title: 'Факт, гипотеза и доказательство', objectives: ['Различать факт и гипотезу'], sections: [{ heading: 'Факт', body: 'Наблюдаемое состояние.', source_block_ids: [1] }] },
        status: 'draft', validation_report: {}, created_at: '2026-08-20T00:00:00Z', published_at: null,
      }]
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

for (const width of widths) {
  test(`responsive academy shell at ${width}px`, async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    await page.setViewportSize({ width, height: width <= 480 ? 800 : 900 })
    await mockAcademy(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('heading', { name: 'Учимся доказывать, а не угадывать.' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

    const actionBoxes = await page.locator('button:visible, a.button:visible, .mobile-nav a:visible').evaluateAll((items) =>
      items.map((item) => {
        const box = item.getBoundingClientRect()
        return { width: box.width, height: box.height, text: item.textContent?.trim() ?? '' }
      }),
    )
    for (const box of actionBoxes) {
      expect(box.height, `${box.text} must be at least 44px high`).toBeGreaterThanOrEqual(43.5)
      expect(box.width, `${box.text} must be at least 44px wide`).toBeGreaterThanOrEqual(43.5)
    }

    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => ['A', 'BUTTON', 'INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName ?? ''))).toBe(true)
    expect(consoleErrors).toEqual([])
  })
}

for (const viewport of [{ width: 360, height: 800 }, { width: 768, height: 900 }]) {
  test(`terminal becomes transcript at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await mockLab(page)
    await page.goto('/lab/1')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('ТОЛЬКО ЧТЕНИЕ')).toBeVisible()
    await expect(page.getByText(/\/home\/student/)).toBeVisible()
    await expect(page.getByLabel('Интерактивный терминал Linux VM')).toHaveCount(0)
  })
}

test('terminal fits again after a desktop resize', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 })
  await mockLab(page)
  await page.goto('/lab/1')
  await page.waitForLoadState('networkidle')
  const terminal = page.getByLabel('Интерактивный терминал Linux VM')
  await expect(terminal).toBeVisible()
  const before = await terminal.boundingBox()
  await page.setViewportSize({ width: 1920, height: 1000 })
  await expect.poll(async () => (await terminal.boundingBox())?.width ?? 0).toBeGreaterThan(before?.width ?? 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('saved learning session survives a page reload', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 })
  await mockSavedSession(page)
  await page.goto('/')
  await expect(page.getByText('СОХРАНЁННЫЙ МАРШРУТ #7')).toBeVisible()
  await page.reload()
  await expect(page.getByText('СОХРАНЁННЫЙ МАРШРУТ #7')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Продолжить Где я нахожусь в Linux' })).toHaveAttribute('href', '/lesson/linux-navigation-pwd?sessionId=7')
})

test('field note is autosaved after editing', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await mockNotes(page)
  const saved = page.waitForRequest((request) => request.method() === 'PUT' && new URL(request.url()).pathname === '/api/v2/notes/1')
  await page.goto('/notes')
  const editor = page.getByLabel('Текст заметки')
  await expect(editor).toHaveValue('Исходный текст')
  await editor.fill('Сохранённое наблюдение')
  const request = await saved
  expect(request.postDataJSON()).toMatchObject({ body: 'Сохранённое наблюдение' })
})

for (const viewport of [{ width: 360, height: 900 }, { width: 1024, height: 900 }]) {
  test(`Studio review editor fits at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await mockStudio(page)
    await page.goto('/studio')
    await page.getByRole('button', { name: 'Проверить JSON' }).click()
    await expect(page.getByLabel('Содержимое JSON')).toBeVisible()
    const overflow = await page.locator('body *').evaluateAll((items) => items.map((item) => {
      const box = item.getBoundingClientRect()
      return { tag: item.tagName, className: item.getAttribute('class') ?? '', right: box.right, left: box.left }
    }).filter((item) => item.right > window.innerWidth + 0.5))
    expect(overflow).toEqual([])
    if (viewport.width === 360) await page.screenshot({ path: 'test-results/studio-review-360.png', fullPage: true })
  })
}
