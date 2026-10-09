import type { Answer } from '../api'

export default function AnswerCard({
  answer,
  question,
}: {
  answer: Answer
  question: string
}) {
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
        <h3>
          {answer.status === 'answered'
            ? 'Generated answer'
            : 'Insufficient evidence'}
        </h3>
        <span className="badge">
          {answer.status === 'answered'
            ? 'Check the sources'
            : 'No supported answer'}
        </span>
      </div>
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
            Retrieved evidence{' '}
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
