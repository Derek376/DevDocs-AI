import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  indexDocument,
  listDocuments,
  messageFor,
  PAGE_SIZE,
  uploadDocument,
} from '../api'
import type { Document } from '../api'

export default function DocumentPanel() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [page, setPage] = useState(0)
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [actionError, setActionError] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [indexed, setIndexed] = useState<Record<string, number>>({})
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    listDocuments(page, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setDocuments(items)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setListError(messageFor(error))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [page, revision])

  function refresh(nextPage = page) {
    setLoading(true)
    setListError('')
    setPage(nextPage)
    setRevision((value) => value + 1)
  }

  async function embed(document: Document) {
    setProgress(`Indexing ${document.filename} for search…`)
    const result = await indexDocument(document.id)
    setIndexed((previous) => ({
      ...previous,
      [document.id]: result.embedded_chunk_count,
    }))
    setProgress(
      `${document.filename}: ${result.embedded_chunk_count} chunks indexed. Ready for questions.`,
    )
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || busy) return
    setActionError('')
    if (!/\.(txt|md|pdf)$/i.test(file.name)) {
      setActionError('Choose a .txt, .md or PDF file.')
      return
    }
    if (file.size === 0 || file.size > 10 * 1024 * 1024) {
      setActionError(
        'Choose a non-empty file up to 10 MiB. The backend also validates uploads.',
      )
      return
    }
    setBusy(true)
    setProgress(`Uploading and extracting ${file.name}…`)
    let saved: Document | undefined
    try {
      saved = await uploadDocument(file)
      setFile(null)
      if (fileInput.current) fileInput.current.value = ''
      refresh(0)
      await embed(saved)
    } catch (error) {
      setActionError(
        saved
          ? `Document saved, but indexing failed: ${messageFor(error)} Use “Index for search” to retry without uploading again.`
          : messageFor(error),
      )
      setProgress('')
    } finally {
      setBusy(false)
    }
  }

  async function retryIndex(document: Document) {
    if (busy) return
    setBusy(true)
    setActionError('')
    try {
      await embed(document)
    } catch (error) {
      setActionError(messageFor(error))
      setProgress('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="panel documents-panel"
      aria-labelledby="documents-title"
    >
      <div className="section-heading">
        <span className="step">01</span>
        <div>
          <h2 id="documents-title">Your documents</h2>
          <p>Build the evidence collection.</p>
        </div>
      </div>
      <form onSubmit={upload} className="upload-form" aria-busy={busy}>
        <label htmlFor="document-file">Choose documentation</label>
        <input
          ref={fileInput}
          id="document-file"
          type="file"
          accept=".txt,.md,.pdf"
          disabled={busy}
          aria-describedby="upload-help"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <p id="upload-help" className="muted">
          TXT, Markdown or text-based PDF · up to 10 MiB
        </p>
        <button type="submit" disabled={!file || busy}>
          {busy ? 'Working…' : 'Upload and index'}
        </button>
      </form>
      <p role="status" className="progress">
        {progress}
      </p>
      {actionError && (
        <p role="alert" className="error">
          {actionError}
        </p>
      )}
      <div className="list-heading">
        <h3>Document library</h3>
        <button
          className="text-button"
          onClick={() => refresh()}
          disabled={loading}
        >
          Refresh
        </button>
      </div>
      <p className="muted">
        Upload saves the text; indexing makes it searchable. Indexing badges
        reflect this browser session only. Existing documents may already be
        indexed.
      </p>
      {loading ? (
        <p role="status">Loading documents…</p>
      ) : listError ? (
        <div>
          <p role="alert" className="error">
            {listError}
          </p>
          <button className="secondary" onClick={() => refresh()}>
            Retry loading documents
          </button>
        </div>
      ) : documents.length === 0 ? (
        <div className="empty-state">
          {page === 0
            ? 'Your collection starts here. Upload your first document above.'
            : 'No documents on this page. Return to the previous page.'}
        </div>
      ) : (
        <ul className="document-list">
          {documents.map((document) => (
            <li key={document.id}>
              <strong className="filename">{document.filename}</strong>
              <p className="muted">
                {document.chunk_count} chunks ·{' '}
                {(document.size_bytes / 1024).toFixed(1)} KiB ·{' '}
                {document.status === 'ready' ? 'Text ready' : document.status}
              </p>
              {indexed[document.id] !== undefined && (
                <p className="badge">
                  Indexed this session · {indexed[document.id]} chunks
                </p>
              )}
              <button
                className="secondary small"
                disabled={busy || document.status !== 'ready'}
                onClick={() => void retryIndex(document)}
                aria-label={`Index for search: ${document.filename}`}
              >
                Index for search
              </button>
            </li>
          ))}
        </ul>
      )}
      <nav aria-label="Document pages" className="pagination">
        <button
          className="text-button"
          disabled={page === 0 || loading}
          onClick={() => refresh(page - 1)}
        >
          Previous
        </button>
        <span>Page {page + 1}</span>
        <button
          className="text-button"
          disabled={loading || !!listError || documents.length < PAGE_SIZE}
          onClick={() => refresh(page + 1)}
        >
          Next
        </button>
      </nav>
    </section>
  )
}
