# AtlasDocs uploads — version 2

In AtlasDocs version 2, the maximum upload size is 10 MiB.
Version 2 accepts UTF-8 TXT, Markdown, and text-based PDF files.
Scanned PDFs are unsupported because version 2 has no OCR.
Oversized uploads return HTTP 413. Unsupported file formats return HTTP 415.
These rules apply only to version 2.
