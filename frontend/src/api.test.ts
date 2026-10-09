import { afterEach, describe, expect, it, vi } from 'vitest'
import { askQuestion, listDocuments, uploadDocument } from './api'

const fetchMock = vi.fn<typeof fetch>()
afterEach(() => fetchMock.mockReset())

function respond(body: unknown, status = 200) {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockResolvedValue(new Response(JSON.stringify(body), { status }))
}

describe('API boundaries', () => {
  it('sends the question through the same-origin proxy', async () => {
    respond({ answer: 'Use ROLLBACK.', citations: [], status: 'answered' })
    await askQuestion('How do I undo changes?')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/questions',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ question: 'How do I undo changes?' }),
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })

  it('uploads multipart data without overriding its boundary', async () => {
    respond({ id: 'doc-1' }, 201)
    const file = new File(['Documentation'], 'guide.md')
    await uploadDocument(file)
    const [path, options] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/documents')
    expect((options?.body as FormData).get('file')).toEqual(file)
    expect(options?.headers).toBeUndefined()
  })

  it.each([
    [{ detail: 'The model is unavailable.' }, 'The model is unavailable.'],
    [{ detail: [{ msg: 'Question is too long.' }] }, 'Question is too long.'],
    [
      { detail: [{ unexpected: true }] },
      'Request failed (502). Please try again.',
    ],
  ])('exposes useful backend errors safely: %j', async (body, message) => {
    respond(body, 502)
    await expect(askQuestion('question')).rejects.toThrow(message)
  })

  it('handles non-JSON proxy errors', async () => {
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockResolvedValue(new Response('Bad Gateway', { status: 502 }))
    await expect(askQuestion('question')).rejects.toThrow(
      'Request failed (502)',
    )
  })

  it('translates network failure into an actionable message', async () => {
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(askQuestion('question')).rejects.toThrow(
      'Check that the backend is running',
    )
  })

  it('preserves cancellation and passes pagination to the server', async () => {
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const error = new DOMException('Cancelled', 'AbortError')
    fetchMock.mockRejectedValue(error)
    await expect(listDocuments(2, controller.signal)).rejects.toBe(error)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/documents?limit=20&offset=40',
      { signal: controller.signal },
    )
  })
})

it('sends retrieval options with the question', async () => {
  respond({ answer: '', citations: [], status: 'insufficient_evidence' })
  await askQuestion('Question', {
    top_k: 3,
    document_ids: ['doc-1'],
    media_type: 'application/pdf',
  })
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/questions',
    expect.objectContaining({
      body: JSON.stringify({
        question: 'Question',
        top_k: 3,
        document_ids: ['doc-1'],
        media_type: 'application/pdf',
      }),
    }),
  )
})
