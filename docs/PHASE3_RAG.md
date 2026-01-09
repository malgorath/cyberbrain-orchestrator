# Phase 3: RAG (Retrieval-Augmented Generation)

## Overview
Phase 3 adds local-only RAG capabilities for ingesting documents and retrieving relevant chunks to augment LLM context.

**Security Guardrails:**
- Local-only embedding models (sentence-transformers)
- Query text is HASHED, never stored
- Token counts only for LLM calls (no prompt/response storage)
- Privacy-first design

## Architecture

### Models (core/models.py)
- **UploadFile**: Tracks uploaded files and ingestion status (queued→processing→ready/failed)
- **Document**: Extracted document from upload
- **Chunk**: Text chunks for embedding (500 words with 50-word overlap)
- **Embedding**: Vector embeddings (using local model)
- **RetrievalEvent**: Logs retrieval queries with SHA256 hash only (no raw text)

### Services
- **Ingester** (run_ingester): Background worker that processes queued uploads
- **RAG API** (orchestrator/rag_views.py): Upload, search, status endpoints

## API Endpoints

### Upload File
```bash
curl -X POST http://localhost:9595/api/rag/upload/ \
  -F "file=@document.pdf"
```

Response:
```json
{
  "upload_id": 1,
  "filename": "document.pdf",
  "status": "queued",
  "message": "File queued for ingestion"
}
```

### Check Upload Status
```bash
curl http://localhost:9595/api/rag/uploads/
```

Response:
```json
{
  "uploads": [
    {
      "id": 1,
      "filename": "document.pdf",
      "status": "ready",
      "uploaded_at": "2026-01-09T00:00:00Z",
      "processed_at": "2026-01-09T00:01:30Z"
    }
  ],
  "count": 1
}
```

### Search Documents
```bash
curl -X POST http://localhost:9595/api/rag/search/ \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "Django deployment",
    "top_k": 5
  }'
```

Response:
```json
{
  "results": [
    {
      "chunk_id": 123,
      "text": "Django can be deployed using...",
      "document_title": "django-guide.pdf",
      "score": 0.87
    }
  ],
  "query_hash": "a1b2c3d4...",
  "count": 5
}
```

### List Documents
```bash
curl http://localhost:9595/api/rag/documents/
```

## Docker Compose

The ingester runs as a separate service:

```yaml
ingester:
  build: .
  command: python manage.py run_ingester --interval=10
  volumes:
    - ./uploads:/uploads
  depends_on:
    - db
    - web
```

Start services:
```bash
docker-compose up -d
docker-compose logs -f ingester
```

## Supported File Types

- **Text**: .txt, .md
- **JSON**: .json
- **PDF**: .pdf (using pypdf)
- **Word**: .docx (using python-docx)

Images store metadata only (no OCR by default).

## Ingestion Pipeline

1. **Upload**: File uploaded via API → UploadFile created with status='queued'
2. **Extraction**: Ingester picks up queued file → extracts text
3. **Chunking**: Text split into 500-word chunks with 50-word overlap
4. **Embedding**: Local sentence-transformers model generates vectors
5. **Storage**: Embeddings stored in Postgres (JSONField for now; pgvector later)
6. **Status**: UploadFile marked as 'ready' or 'failed'

## Search Algorithm

1. Query text → local embedding model → query vector
2. Compute cosine similarity with all chunk embeddings
3. Sort by score descending
4. Return top_k results

**Note**: Current implementation uses in-memory cosine similarity. In production with pgvector, use vector similarity operators for efficient search.

## Security Guardrails

### Query Privacy
```python
# CORRECT: Hash query, do NOT store raw text
query_hash = hashlib.sha256(query_text.encode('utf-8')).hexdigest()
RetrievalEvent.objects.create(
    query_hash=query_hash,  # Hash only
    top_k=5,
    results_count=len(results)
)

# WRONG: Never do this
# RetrievalEvent.objects.create(query_text=query_text)  # ❌ PROHIBITED
```

### RetrievalEvent Model
```python
class RetrievalEvent(models.Model):
    query_hash = models.CharField(max_length=64)  # SHA256 hash
    top_k = models.IntegerField()
    results_count = models.IntegerField()
    # WARNING: Do NOT add query_text field
```

## Testing

Run acceptance tests:
```bash
python manage.py test tests.acceptance.test_rag --settings=cyberbrain_orchestrator.test_settings
```

Tests verify:
1. Upload → ingest → search flow
2. Query text is hashed, not stored
3. No prompt/response content persisted
4. Token counts only for LLM calls

## Troubleshooting

### Ingester Not Processing Files
```bash
# Check ingester logs
docker-compose logs -f ingester

# Verify upload status
curl http://localhost:9595/api/rag/uploads/
```

### Embedding Model Download
On first run, sentence-transformers downloads the model (~80MB). Check logs:
```bash
docker-compose logs ingester | grep "Loading embedding model"
```

### File Not Found Errors
Ensure `UPLOADS_DIR` is mounted correctly in docker-compose:
```yaml
volumes:
  - ${UPLOADS_DIR:-./uploads}:/uploads
```

## Future Enhancements (Not in Phase 3)

- pgvector for efficient similarity search
- OCR for images
- Multi-modal embeddings
- Hybrid search (keyword + vector)
- RAG integration with task execution (use_rag flag)

## References

- Models: [core/models.py](../core/models.py) (lines 707+)
- API: [orchestrator/rag_views.py](../orchestrator/rag_views.py)
- Ingester: [core/management/commands/run_ingester.py](../core/management/commands/run_ingester.py)
- Tests: [tests/acceptance/test_rag.py](../tests/acceptance/test_rag.py)
