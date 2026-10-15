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
        <h1>
          <a className="brand" href="/" aria-label="DevDocs AI home">
            DevDocs <span>AI</span>
          </a>
        </h1>
        <p>Documentation workspace</p>
      </header>
      <main id="main-content">
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
        Local document collection · Each question is independent.
      </footer>
    </div>
  )
}
