import { useState } from 'react'
import type { FormEvent } from 'react'
import { askQuestion, messageFor } from '../api'
import type { Answer } from '../api'
import AnswerCard from './AnswerCard'

export default function QuestionPanel() {
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || trimmed.length > 2000 || busy) return
    setBusy(true)
    setError('')
    setAnswer(null)
    setSubmittedQuestion(trimmed)
    try {
      setAnswer(await askQuestion(trimmed))
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
            Each question searches the indexed collection.
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
          Retrieving passages and drafting an answer. Local models may take a
          moment…
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error} You can submit your question again.
        </p>
      )}
      {answer ? (
        <AnswerCard answer={answer} question={submittedQuestion} />
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
