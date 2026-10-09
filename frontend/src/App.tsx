import { useState } from 'react'
import type { Document } from './api'
import DocumentPanel from './components/DocumentPanel'
import QuestionPanel from './components/QuestionPanel'

export default function App() {
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(
    null,
  )
  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="DevDocs AI home">
          <span className="brand-icon" aria-hidden="true">
            D
          </span>{' '}
          DevDocs <span className="brand-ai">AI</span>
        </a>
        <span className="header-note">Your docs. Inspectable answers.</span>
      </header>
      <main>
        <section className="intro" aria-labelledby="page-title">
          <p className="eyebrow">DOCUMENTATION WORKSPACE</p>
          <h1 id="page-title">
            Find the answer.
            <br />
            <span>Follow the evidence.</span>
          </h1>
          <p>
            Bring your technical documentation, ask a question, and check the
            passages behind the answer.
          </p>
        </section>
        <div className="workspace">
          <DocumentPanel
            selectedDocumentId={selectedDocument?.id}
            onSelectDocument={setSelectedDocument}
          />
          <QuestionPanel
            selectedDocument={selectedDocument}
            onClearDocument={() => setSelectedDocument(null)}
          />
        </div>
      </main>
      <footer>
        Local, shared document collection · Each question is independent ·
        Always check the cited evidence.
      </footer>
    </div>
  )
}
