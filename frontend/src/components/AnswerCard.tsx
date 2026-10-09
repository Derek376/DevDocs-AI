import type { Answer } from '../api'

export default function AnswerCard({
  answer,
  question,
}: {
  answer: Answer
  question: string
}) {
  const labels = {
    answered: { title: 'Generated answer', badge: 'Check the sources' },
    insufficient_evidence: { title: 'Insufficient evidence', badge: 'No supported answer' },
    metadata: { title: 'Document metadata', badge: 'Verified database fields' },
    selection_required: { title: 'Select a document', badge: 'Selection required' },
  }[answer.status]

  function showSource(label: string) {
    const source = document.getElementById(`source-${label}`)
    if (source instanceof HTMLDetailsElement) {
      source.open = true
      source.querySelector('summary')?.focus()
      source.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }

  return (
    <article className="answer-card" aria-label="Answer result">
      <p className="eyebrow">YOU ASKED</p>
      <p className="asked-question">{question}</p>
      <div className="answer-heading">
        <h3>{labels.title}</h3>
        <span className="badge">{labels.badge}</span>
      </div>
      {answer.tool && <p className="muted">
        Action used: {{
          retrieve_documentation: 'Search documentation',
          inspect_document_metadata: 'Inspect document metadata',
          summarize_document: 'Summarize document',
        }[answer.tool]}
      </p>}
      {answer.context_truncated && <p role="status" className="muted">
        Partial summary: only the first document excerpts fit the summary limit.
      </p>}
      {answer.status === 'metadata' && answer.document && <dl className="document-metadata">
        <dt>Filename</dt><dd>{answer.document.filename}</dd>
        <dt>Format</dt><dd>{answer.document.media_type}</dd>
        <dt>Size in bytes</dt><dd>{answer.document.size_bytes}</dd>
        <dt>Text status</dt><dd>{answer.document.status}</dd>
        <dt>Chunk count</dt><dd>{answer.document.chunk_count}</dd>
        <dt>Uploaded</dt><dd>{new Date(answer.document.created_at).toLocaleString()}</dd>
        <dt>Updated</dt><dd>{new Date(answer.document.updated_at).toLocaleString()}</dd>
      </dl>}
      <p className="answer-text">
        {answer.answer.split(/(\[S\d+\])/g).map((part, index) => {
          const label = part.slice(1, -1)
          return /^\[S\d+\]$/.test(part) &&
            answer.citations.some((citation) => citation.label === label) ? (
            <button
              key={index}
              className="citation-link"
              onClick={() => showSource(label)}
              aria-label={`Show source ${label}`}
            >
              {part}
            </button>
          ) : (
            part
          )
        })}
      </p>
      {answer.citations.length > 0 && (
        <section className="sources" aria-labelledby="sources-title">
          <h3 id="sources-title">
            {answer.tool === 'summarize_document' ? 'Document excerpts' : 'Retrieved evidence'}{' '}
            <span className="source-count">{answer.citations.length}</span>
          </h3>
          <p className="muted">
            These are document excerpts. Compare them with the generated claims;
            a citation alone does not prove correctness.
          </p>
          {answer.citations.map((source) => (
            <details id={`source-${source.label}`} key={source.chunk_id}>
              <summary>
                <span className="source-label">[{source.label}]</span>{' '}
                {source.filename}
                <span className="source-location">
                  Chunk {source.position + 1}
                  {source.source_page !== null &&
                    ` · Page ${source.source_page}`}
                </span>
              </summary>
              {source.truncated && (
                <p className="muted">
                  Excerpt shortened during context selection.
                </p>
              )}
              <blockquote>{source.text}</blockquote>
            </details>
          ))}
        </section>
      )}
    </article>
  )
}
