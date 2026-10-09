export interface Document {
  id: string
  filename: string
  media_type: string
  size_bytes: number
  status: 'processing' | 'ready' | 'failed'
  created_at: string
  updated_at: string
  chunk_count: number
}

export interface IndexResult {
  document_id: string
  embedded_chunk_count: number
  model: string
  dimensions: number
}

export interface Citation {
  label: string
  chunk_id: string
  document_id: string
  filename: string
  position: number
  source_page: number | null
  text: string
  similarity: number
  truncated: boolean
}

export interface Answer {
  answer: string
  status: 'answered' | 'insufficient_evidence'
  citations: Citation[]
  llm_model: string
  embedding_model: string
}

// Treat error responses as untrusted input; FastAPI detail can be text or a list.
function errorDetail(body: unknown): string | undefined {
  if (!body || typeof body !== 'object' || !('detail' in body)) return
  const detail = body.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item: unknown) =>
      item &&
      typeof item === 'object' &&
      'msg' in item &&
      typeof item.msg === 'string'
        ? [item.msg]
        : [],
    )
    return messages.length ? messages.join(' ') : undefined
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, init)
  } catch (error) {
    if (
      error &&
      typeof error === 'object' &&
      'name' in error &&
      error.name === 'AbortError'
    )
      throw error
    throw new Error(
      'Cannot reach the API. Check that the backend is running and try again.',
      { cause: error },
    )
  }
  const body: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    const requestId = response.headers.get('X-Request-ID')
    const reference = requestId && /^[a-f0-9]{32}$/.test(requestId)
      ? ` Reference: ${requestId}.`
      : ''
    throw new Error(
      (errorDetail(body) ??
        `Request failed (${response.status}). Please try again.`) + reference,
    )
  }
  if (body === undefined)
    throw new Error(
      'The API returned an unreadable response. Please try again.',
    )
  // Types mirror the backend contract; they do not perform runtime schema validation.
  return body as T
}

export const PAGE_SIZE = 20

export function listDocuments(
  page: number,
  signal?: AbortSignal,
): Promise<Document[]> {
  return request(`/documents?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`, {
    signal,
  })
}

export function uploadDocument(file: File): Promise<Document> {
  const body = new FormData()
  body.append('file', file)
  // The browser supplies the multipart boundary; do not set Content-Type manually.
  return request('/documents', { method: 'POST', body })
}

export function indexDocument(id: string): Promise<IndexResult> {
  return request(`/documents/${encodeURIComponent(id)}/index`, {
    method: 'POST',
  })
}

export type MediaType = 'text/plain' | 'text/markdown' | 'application/pdf'

export interface RetrievalOptions {
  top_k?: number
  document_ids?: string[]
  media_type?: MediaType
}

export function askQuestion(
  question: string,
  options: RetrievalOptions = {},
): Promise<Answer> {
  return request('/questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, ...options }),
  })
}

export function messageFor(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'Something went wrong. Please try again.'
}
