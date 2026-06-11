# Knowledge Base

Place PDF documents here to be ingested into the ChromaDB vector store.

## How to ingest a PDF

Use the admin API endpoint:

```
POST /api/admin/knowledge/ingest
Content-Type: multipart/form-data
file: <your_pdf_file>
```

Requires admin authentication (httpOnly cookie).

## Supported formats
- PDF (`.pdf`) — text extracted via PyMuPDF
- The built-in TMA knowledge base is always available as a fallback (keyword search)

## Built-in topics
- Service restart procedures
- Incident management (RG2)
- Database troubleshooting
- Performance diagnostics
- Deployment procedures
- Security best practices
- Monitoring & alerting
