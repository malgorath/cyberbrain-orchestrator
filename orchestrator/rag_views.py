"""
Phase 3: RAG API Views

Endpoints for RAG operations:
- POST /api/rag/search - Search for relevant chunks
- GET /api/rag/uploads - List uploaded files
- POST /api/rag/uploads - Upload a new file
- GET /api/rag/documents - List documents

SECURITY GUARDRAIL: Query text is hashed, not stored.
"""
import hashlib
import logging
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser

from core.models import UploadFile, Document, Chunk, Embedding, RetrievalEvent
from orchestrator.models import Run as LegacyRun

logger = logging.getLogger(__name__)


def compute_query_hash(query_text: str) -> str:
    """Compute SHA256 hash of query text for privacy-preserving logging."""
    return hashlib.sha256(query_text.encode('utf-8')).hexdigest()


def compute_file_hash(file_content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(file_content).hexdigest()


def cosine_similarity(vec1, vec2):
    """Compute cosine similarity between two vectors."""
    import numpy as np
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))


class RAGViewSet(viewsets.ViewSet):
    """
    Phase 3: RAG operations viewset.
    
    Provides search, upload, and document listing.
    """
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    
    @action(detail=False, methods=['post'], url_path='search')
    def search(self, request):
        """
        POST /api/rag/search
        
        Search for relevant document chunks.
        Input: { "query_text": str, "top_k": int (optional, default=5), "run_id": int (optional) }
        Output: { "results": [{"chunk_id", "text", "document_title", "score"}], "query_hash": str }
        
        SECURITY GUARDRAIL: query_text is NOT persisted; only hash is logged.
        """
        query_text = request.data.get('query_text', '').strip()
        top_k = request.data.get('top_k', 5)
        run_id = request.data.get('run_id')
        
        if not query_text:
            return Response({'error': 'query_text is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Hash query for logging (do NOT store raw query)
            query_hash = compute_query_hash(query_text)
            
            # Generate query embedding
            from core.management.commands.run_ingester import EmbeddingService
            embedding_service = EmbeddingService()
            query_embedding = embedding_service.embed([query_text])[0]
            
            # Retrieve all embeddings and compute similarities
            # Note: In production with pgvector, use vector similarity operator
            embeddings = Embedding.objects.select_related('chunk__document').all()
            
            results = []
            for emb in embeddings:
                score = cosine_similarity(query_embedding, emb.vector)
                results.append({
                    'chunk_id': emb.chunk_id,
                    'text': emb.chunk.text[:500],  # Truncate for response
                    'document_id': emb.chunk.document_id,
                    'document_title': emb.chunk.document.title,
                    'score': score
                })
            
            # Sort by score descending and take top_k
            results.sort(key=lambda x: x['score'], reverse=True)
            results = results[:top_k]
            
            # Log retrieval event (hash only, NO raw query)
            run_obj = None
            if run_id:
                run_obj = LegacyRun.objects.filter(id=run_id).first()
            
            RetrievalEvent.objects.create(
                run=run_obj,
                query_hash=query_hash,
                top_k=top_k,
                results_count=len(results)
            )
            
            return Response({
                'results': results,
                'query_hash': query_hash,
                'count': len(results)
            })
            
        except Exception as e:
            logger.error(f"RAG search error: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='uploads')
    def list_uploads(self, request):
        """
        GET /api/rag/uploads
        
        List all uploaded files with their ingestion status.
        """
        uploads = UploadFile.objects.all().order_by('-uploaded_at')
        data = [{
            'id': u.id,
            'filename': u.filename,
            'mime_type': u.mime_type,
            'size_bytes': u.size_bytes,
            'status': u.status,
            'uploaded_at': u.uploaded_at.isoformat(),
            'processed_at': u.processed_at.isoformat() if u.processed_at else None,
            'error_message': u.error_message if u.status == 'failed' else ''
        } for u in uploads]
        
        return Response({'uploads': data, 'count': len(data)})
    
    @action(detail=False, methods=['post'], url_path='upload')
    def upload_file(self, request):
        """
        POST /api/rag/upload
        
        Upload a file for RAG ingestion.
        Expects multipart/form-data with 'file' field.
        """
        if 'file' not in request.FILES:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        uploaded_file = request.FILES['file']
        
        try:
            # Read file content
            file_content = uploaded_file.read()
            file_hash = compute_file_hash(file_content)
            
            # Check for duplicate
            existing = UploadFile.objects.filter(sha256=file_hash).first()
            if existing:
                return Response({
                    'message': 'File already uploaded',
                    'upload_id': existing.id,
                    'status': existing.status
                }, status=status.HTTP_200_OK)
            
            # Determine MIME type
            mime_type = uploaded_file.content_type or 'application/octet-stream'
            
            # Save file to disk
            uploads_dir = Path(settings.BASE_DIR) / 'uploads'
            uploads_dir.mkdir(exist_ok=True)
            
            file_path = uploads_dir / f"{file_hash}_{uploaded_file.name}"
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            # Create UploadFile record
            upload = UploadFile.objects.create(
                filename=uploaded_file.name,
                mime_type=mime_type,
                size_bytes=len(file_content),
                sha256=file_hash,
                stored_path=str(file_path),
                status='queued'
            )
            
            logger.info(f"File uploaded: {upload.filename} (ID: {upload.id})")
            
            return Response({
                'upload_id': upload.id,
                'filename': upload.filename,
                'status': upload.status,
                'message': 'File queued for ingestion'
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Upload error: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='documents')
    def list_documents(self, request):
        """
        GET /api/rag/documents
        
        List all ingested documents.
        """
        documents = Document.objects.select_related('upload').all().order_by('-created_at')
        data = [{
            'id': d.id,
            'title': d.title,
            'source': d.source,
            'upload_id': d.upload_id,
            'upload_filename': d.upload.filename,
            'upload_status': d.upload.status,
            'chunk_count': d.chunks.count(),
            'created_at': d.created_at.isoformat()
        } for d in documents]
        
        return Response({'documents': data, 'count': len(data)})
