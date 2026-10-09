import { useState } from 'react'
import type { FormEvent } from 'react'
import { askQuestion, messageFor } from '../api'
import type { Answer, Document, MediaType, RetrievalOptions } from '../api'
import AnswerCard from './AnswerCard'

export default function QuestionPanel({
  selectedDocument,
  onClearDocument,
}: {
  selectedDocument: Document | null
  onClearDocument: () => void
}) {
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [topK, setTopK] = useState('')
  const [mediaType, setMediaType] = useState<MediaType | ''>('')
  const [submittedScope, setSubmittedScope] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = question.trim()
    const count = topK === '' ? undefined : Number(topK)
    if (
      !trimmed ||
      trimmed.length > 2000 ||
      busy ||
      (count !== undefined &&
        (!Number.isInteger(count) || count < 1 || count > 20))
    )
      return
    const options: RetrievalOptions = {}
    if (count !== undefined) options.top_k = count
    if (selectedDocument) options.document_ids = [selectedDocument.id]
    if (mediaType) options.media_type = mediaType
    setBusy(true)
    setError('')
    setAnswer(null)
    setSubmittedQuestion(trimmed)
    setSubmittedScope(
      `${selectedDocument?.filename ?? 'All documents'} · ${mediaType ? { 'text/plain': 'Text', 'text/markdown': 'Markdown', 'application/pdf': 'PDF' }[mediaType] : 'All formats'}`,
    )
    try {
      setAnswer(await askQuestion(trimmed, options))
    } catch (error) {
      setError(messageFor(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel question-panel" aria-labelledby="questions-title">
      <div className="section-heading">
        <span className="step">02</span>
        <div>
          <h2 id="questions-title">Ask your documentation</h2>
          <p>From a question to the source.</p>
        </div>
      </div>
      <form onSubmit={submit} aria-busy={busy}>
        <div className="search-scope">
          <p className="muted">
            Search scope:{' '}
            <strong>{selectedDocument?.filename ?? 'All documents'}</strong>
          </p>
          {selectedDocument && (
            <button
              type="button"
              className="text-button"
              onClick={onClearDocument}
              disabled={busy}
            >
              Search all documents
            </button>
          )}
        </div>
        <div className="retrieval-controls">
          <div>
            <label htmlFor="top-k">Maximum source chunks</label>
            <input
              id="top-k"
              type="number"
              min={1}
              max={20}
              step={1}
              value={topK}
              onChange={(event) => setTopK(event.target.value)}
              disabled={busy}
              placeholder="Server default"
              aria-describedby="retrieval-help"
            />
          </div>
          <div>
            <label htmlFor="media-type">Document format</label>
            <select
              id="media-type"
              value={mediaType}
              onChange={(event) =>
                setMediaType(event.target.value as MediaType | '')
              }
              disabled={busy}
            >
              <option value="">All formats</option>
              <option value="text/plain">Text</option>
              <option value="text/markdown">Markdown</option>
              <option value="application/pdf">PDF</option>
            </select>
          </div>
        </div>
        <p id="retrieval-help" className="muted">
          Use 1–20 chunks, or leave blank for the server default. More sources
          can also add noise. Document and format filters apply together.
        </p>
        <label htmlFor="question">Your question</label>
        <textarea
          id="question"
          rows={4}
          maxLength={2000}
          value={question}
          disabled={busy}
          onChange={(event) => setQuestion(event.target.value)}
          aria-describedby="question-help"
          placeholder="How do I roll back a database transaction?"
        />
        <div className="question-actions">
          <p id="question-help" className="muted">
            Each question searches indexed documents in the selected scope.
            <br />
            No conversation memory · {question.length}/2000
          </p>
          <button type="submit" disabled={!question.trim() || busy}>
            {busy ? 'Finding an answer…' : 'Ask question ↗'}
          </button>
        </div>
      </form>
      {busy && (
        <p role="status" className="progress">
          Retrieving passages and drafting an answer. Generation may take a
          moment…
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error} You can submit your question again.
        </p>
      )}
      {answer ? (
        <div>
          <p className="muted">Scope used for this answer: {submittedScope}</p>
          <AnswerCard answer={answer} question={submittedQuestion} />
        </div>
      ) : (
        !busy &&
        !error && (
          <div className="answer-placeholder">
            <span className="placeholder-mark" aria-hidden="true">
              ↳
            </span>
            <h3>Answers with a trail to follow</h3>
            <p>
              Upload and index a document, then ask about it.
              <br />
              The generated answer and cited passages will appear here.
            </p>
          </div>
        )
      )}
    </section>
  )
}
