import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as api from './api'
import type { Answer, Document } from './api'

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  indexDocument: vi.fn(),
  askQuestion: vi.fn(),
}))

const document: Document = {
  id: 'doc-1',
  filename: 'transactions.md',
  media_type: 'text/markdown',
  size_bytes: 200,
  status: 'ready',
  chunk_count: 1,
  created_at: '2026-10-08T12:00:00Z',
  updated_at: '2026-10-08T12:00:00Z',
}
const result: Answer = {
  answer: 'Use ROLLBACK to undo the transaction. [S1]',
  status: 'answered',
  embedding_model: 'embeddinggemma',
  llm_model: 'llama3.2:1b',
  citations: [
    {
      label: 'S1',
      chunk_id: 'chunk-1',
      document_id: document.id,
      filename: document.filename,
      position: 0,
      source_page: 2,
      text: 'ROLLBACK discards all changes in the current transaction.',
      similarity: 0.8,
      truncated: false,
    },
  ],
}

beforeEach(() => {
  vi.mocked(api.listDocuments).mockReset().mockResolvedValue([])
  vi.mocked(api.uploadDocument).mockReset().mockResolvedValue(document)
  vi.mocked(api.indexDocument).mockReset().mockResolvedValue({
    document_id: document.id,
    embedded_chunk_count: 1,
    dimensions: 768,
    model: 'embeddinggemma',
  })
  vi.mocked(api.askQuestion).mockReset().mockResolvedValue(result)
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  })
})

describe('documentation workspace', () => {
  it('shows an empty library and prevents empty submissions', async () => {
    render(<App />)
    expect(
      await screen.findByText(/Upload your first document/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Upload and index' }),
    ).toBeDisabled()
    expect(screen.getByRole('button', { name: /Ask question/ })).toBeDisabled()
  })

  it('uploads then indexes and reports searchable chunks', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText(/Upload your first document/)
    vi.mocked(api.listDocuments).mockResolvedValue([document])
    const file = new File(['ROLLBACK discards changes.'], 'transactions.md')
    await user.upload(screen.getByLabelText('Choose documentation'), file)
    await user.click(screen.getByRole('button', { name: 'Upload and index' }))
    expect(await screen.findByText(/Indexed this session/)).toBeInTheDocument()
    expect(api.uploadDocument).toHaveBeenCalledWith(file)
    expect(api.indexDocument).toHaveBeenCalledWith(document.id)
    expect(
      screen.getByText(/1 chunks indexed. Ready for questions/),
    ).toBeInTheDocument()
  })

  it('retains a saved document after indexing fails and retries without re-uploading', async () => {
    const user = userEvent.setup()
    vi.mocked(api.indexDocument).mockRejectedValueOnce(
      new Error('Embedding provider unavailable.'),
    )
    render(<App />)
    await screen.findByText(/Upload your first document/)
    vi.mocked(api.listDocuments).mockResolvedValue([document])
    await user.upload(
      screen.getByLabelText('Choose documentation'),
      new File(['Docs'], 'transactions.md'),
    )
    await user.click(screen.getByRole('button', { name: 'Upload and index' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Document saved, but indexing failed',
    )
    await user.click(
      await screen.findByRole('button', {
        name: 'Index for search: transactions.md',
      }),
    )
    expect(await screen.findByText(/Indexed this session/)).toBeInTheDocument()
    expect(api.uploadDocument).toHaveBeenCalledTimes(1)
    expect(api.indexDocument).toHaveBeenCalledTimes(2)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not assume pre-existing documents have been indexed', async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([document])
    render(<App />)
    expect(await screen.findByText('transactions.md')).toBeInTheDocument()
    expect(screen.getByText(/Text ready/)).toBeInTheDocument()
    expect(screen.queryByText(/Indexed this session/)).not.toBeInTheDocument()
  })

  it('rejects unsupported and oversized uploads before making a request', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<App />)
    await user.upload(
      screen.getByLabelText('Choose documentation'),
      new File(['bad'], 'bad.exe'),
    )
    await user.click(screen.getByRole('button', { name: 'Upload and index' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Choose a .txt, .md or PDF file',
    )
    const big = new File(['x'], 'big.txt')
    Object.defineProperty(big, 'size', { value: 10 * 1024 * 1024 + 1 })
    await user.upload(screen.getByLabelText('Choose documentation'), big)
    await user.click(screen.getByRole('button', { name: 'Upload and index' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('up to 10 MiB')
    expect(api.uploadDocument).not.toHaveBeenCalled()
  })

  it('shows upload rejection without attempting indexing', async () => {
    const user = userEvent.setup()
    vi.mocked(api.uploadDocument).mockRejectedValueOnce(
      new Error('PDF contains no extractable text.'),
    )
    render(<App />)
    await user.upload(
      screen.getByLabelText('Choose documentation'),
      new File(['bad PDF'], 'scanned.pdf'),
    )
    await user.click(screen.getByRole('button', { name: 'Upload and index' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'PDF contains no extractable text',
    )
    expect(api.indexDocument).not.toHaveBeenCalled()
    expect(
      screen.getByRole('button', { name: 'Upload and index' }),
    ).toBeEnabled()
  })

  it('recovers from a library load failure', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listDocuments).mockRejectedValueOnce(
      new Error('Database unavailable.'),
    )
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Database unavailable',
    )
    await user.click(
      screen.getByRole('button', { name: 'Retry loading documents' }),
    )
    expect(
      await screen.findByText(/Upload your first document/),
    ).toBeInTheDocument()
  })

  it('paginates a full library and cancels the previous list request', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listDocuments)
      .mockResolvedValueOnce(
        Array.from({ length: api.PAGE_SIZE }, (_, index) => ({
          ...document,
          id: `doc-${index}`,
        })),
      )
      .mockResolvedValueOnce([])
    render(<App />)
    await screen.findAllByText('transactions.md')
    const firstSignal = vi.mocked(api.listDocuments).mock.calls[0][1]
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(
      await screen.findByText(/No documents on this page/),
    ).toBeInTheDocument()
    expect(api.listDocuments).toHaveBeenLastCalledWith(
      1,
      expect.any(AbortSignal),
    )
    expect(firstSignal?.aborted).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Previous' }))
    expect(
      await screen.findByText(/Upload your first document/),
    ).toBeInTheDocument()
  })

  it('shows pending state, trims the question and opens the cited evidence', async () => {
    const user = userEvent.setup()
    let resolve!: (answer: Answer) => void
    vi.mocked(api.askQuestion).mockReturnValueOnce(
      new Promise((done) => {
        resolve = done
      }),
    )
    render(<App />)
    await user.type(
      screen.getByLabelText('Your question'),
      '  How do I undo changes?  ',
    )
    await user.click(screen.getByRole('button', { name: /Ask question/ }))
    expect(
      screen.getByText(/Retrieving passages and drafting/),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Your question')).toBeDisabled()
    await act(async () => resolve(result))
    expect(api.askQuestion).toHaveBeenCalledWith('How do I undo changes?', {})
    const evidence = screen.getByText(result.citations[0].text)
    const details = evidence.closest('details')!
    expect(details.open).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Show source S1' }))
    expect(details.open).toBe(true)
    expect(within(details).getByText('Chunk 1 · Page 2')).toBeInTheDocument()
    expect(details.querySelector('summary')).toHaveFocus()
  })

  it('renders insufficient evidence without inventing source links', async () => {
    const user = userEvent.setup()
    vi.mocked(api.askQuestion).mockResolvedValueOnce({
      ...result,
      answer: 'I do not have enough documentation to answer.',
      status: 'insufficient_evidence',
      citations: [],
    })
    render(<App />)
    await user.type(screen.getByLabelText('Your question'), 'Unknown question')
    await user.click(screen.getByRole('button', { name: /Ask question/ }))
    expect(
      await screen.findByRole('heading', { name: 'Insufficient evidence' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: /Retrieved evidence/ }),
    ).not.toBeInTheDocument()
  })

  it('allows a question retry after a provider error', async () => {
    const user = userEvent.setup()
    vi.mocked(api.askQuestion).mockRejectedValueOnce(
      new Error('LLM unavailable.'),
    )
    render(<App />)
    await user.type(
      screen.getByLabelText('Your question'),
      'How do I undo changes?',
    )
    await user.click(screen.getByRole('button', { name: /Ask question/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'LLM unavailable',
    )
    await user.click(screen.getByRole('button', { name: /Ask question/ }))
    expect(
      await screen.findByRole('heading', { name: 'Generated answer' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders model and source HTML as text rather than executing it', async () => {
    vi.mocked(api.askQuestion).mockResolvedValueOnce({
      ...result,
      answer: '<img src=x onerror=alert(1)> [S1]',
      citations: [
        {
          ...result.citations[0],
          text: '<script>alert(1)</script>',
          truncated: true,
        },
      ],
    })
    render(<App />)
    fireEvent.change(screen.getByLabelText('Your question'), {
      target: { value: 'Question' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Ask question/ }))
    await waitFor(() =>
      expect(screen.getByText(/<img src=x/)).toBeInTheDocument(),
    )
    expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument()
    expect(
      screen.getByText('Excerpt shortened during context selection.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('article').querySelector('img, script')).toBeNull()
  })
})

it('selects a document and format for questions, then restores server defaults', async () => {
  const user = userEvent.setup()
  vi.mocked(api.listDocuments).mockResolvedValue([document])
  render(<App />)
  await user.click(
    await screen.findByRole('button', {
      name: 'Use for questions: transactions.md',
    }),
  )
  await user.type(screen.getByLabelText('Maximum source chunks'), '3')
  await user.selectOptions(
    screen.getByLabelText('Document format'),
    'text/markdown',
  )
  await user.type(
    screen.getByLabelText('Your question'),
    'How do I undo changes?',
  )
  await user.click(screen.getByRole('button', { name: /Ask question/ }))
  await screen.findByRole('heading', { name: 'Generated answer' })
  expect(api.askQuestion).toHaveBeenLastCalledWith('How do I undo changes?', {
    top_k: 3,
    document_ids: [document.id],
    media_type: 'text/markdown',
  })
  expect(
    screen.getByText('Scope used for this answer: transactions.md · Markdown'),
  ).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Search all documents' }))
  await user.clear(screen.getByLabelText('Maximum source chunks'))
  await user.selectOptions(screen.getByLabelText('Document format'), '')
  await user.click(screen.getByRole('button', { name: /Ask question/ }))
  await screen.findByRole('heading', { name: 'Generated answer' })
  expect(api.askQuestion).toHaveBeenLastCalledWith('How do I undo changes?', {})
})

it('keeps the scope of a displayed answer when the next question scope changes', async () => {
  const user = userEvent.setup()
  vi.mocked(api.listDocuments).mockResolvedValue([
    document,
    { ...document, id: 'doc-2', filename: 'other.md' },
  ])
  render(<App />)
  await user.click(
    await screen.findByRole('button', {
      name: 'Use for questions: transactions.md',
    }),
  )
  await user.type(
    screen.getByLabelText('Your question'),
    'How do I undo changes?',
  )
  await user.click(screen.getByRole('button', { name: /Ask question/ }))
  await screen.findByRole('heading', { name: 'Generated answer' })
  await user.click(
    screen.getByRole('button', { name: 'Use for questions: other.md' }),
  )
  expect(
    screen.getByText(
      'Scope used for this answer: transactions.md · All formats',
    ),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: 'Use for questions: other.md' }),
  ).toHaveAttribute('aria-pressed', 'true')
})
