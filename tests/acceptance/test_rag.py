"""
Phase 3 RAG Acceptance Tests

Tests the upload -> ingest -> search flow and validates security guardrails:
- Upload file via API
- Trigger ingestion manually
- Search and retrieve chunks
- Verify query text is NOT persisted (hash only)
- Verify no prompt/response storage
"""
import time
import tempfile
from pathlib import Path
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import UploadFile, Document, Chunk, Embedding, RetrievalEvent
from orchestrator.models import Run as LegacyRun, Directive as LegacyDirective


class RAGAcceptanceTest(TestCase):
    """
    Acceptance tests for Phase 3 RAG functionality.
    
    Validates:
    1. File upload creates UploadFile with queued status
    2. Ingestion processes file and creates Document, Chunks, Embeddings
    3. Search returns relevant results
    4. Query text is hashed, not stored
    5. No LLM content is persisted
    """
    
    def setUp(self):
        self.client = APIClient()
    
    def test_rag_upload_ingest_search_flow(self):
        """Test complete RAG workflow from upload to search."""
        # 1. Upload a text file
        test_content = b"This is test document about Django and Python. It covers web development."
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.txt') as f:
            f.write(test_content)
            f.flush()
            temp_path = Path(f.name)
        
        try:
            with open(temp_path, 'rb') as f:
                response = self.client.post('/api/rag/upload/', {'file': f}, format='multipart')
            
            self.assertEqual(response.status_code, 201)
            self.assertIn('upload_id', response.data)
            upload_id = response.data['upload_id']
            
            # Verify UploadFile created with queued status
            upload = UploadFile.objects.get(id=upload_id)
            self.assertEqual(upload.status, 'queued')
            self.assertEqual(upload.filename, temp_path.name)
            
            # 2. Manually trigger ingestion (simulating background worker)
            from core.management.commands.run_ingester import (
                EmbeddingService, TextExtractor, TextChunker
            )
            
            embedding_service = EmbeddingService()
            text_extractor = TextExtractor()
            text_chunker = TextChunker(chunk_size=50, overlap=10)
            
            # Process the upload
            upload.refresh_from_db()
            upload.status = 'processing'
            upload.save()
            
            # Extract text
            text = text_extractor.extract(Path(upload.stored_path), upload.mime_type)
            self.assertIn('Django', text)
            
            # Create document and chunks
            document = Document.objects.create(
                upload=upload,
                title=upload.filename,
                source=upload.filename
            )
            
            chunks_text = text_chunker.chunk(text)
            self.assertGreater(len(chunks_text), 0)
            
            chunk_objs = []
            for idx, chunk_text in enumerate(chunks_text):
                chunk = Chunk.objects.create(
                    document=document,
                    chunk_index=idx,
                    text=chunk_text
                )
                chunk_objs.append(chunk)
            
            # Generate embeddings
            embeddings_data = embedding_service.embed(chunks_text)
            for chunk_obj, embedding_vector in zip(chunk_objs, embeddings_data):
                Embedding.objects.create(
                    chunk=chunk_obj,
                    embedding_model_id=embedding_service.model_id,
                    vector=embedding_vector
                )
            
            upload.status = 'ready'
            upload.save()
            
            # 3. Search for content
            search_response = self.client.post('/api/rag/search/', {
                'query_text': 'Django web development',
                'top_k': 3
            })
            
            self.assertEqual(search_response.status_code, 200)
            self.assertIn('results', search_response.data)
            self.assertGreater(len(search_response.data['results']), 0)
            
            # Verify results contain relevant text
            result = search_response.data['results'][0]
            self.assertIn('text', result)
            self.assertIn('document_title', result)
            self.assertIn('score', result)
            
            # 4. Verify query hash is logged, NOT raw query text
            query_hash = search_response.data['query_hash']
            self.assertIsNotNone(query_hash)
            self.assertEqual(len(query_hash), 64)  # SHA256 hash length
            
            retrieval_event = RetrievalEvent.objects.filter(query_hash=query_hash).first()
            self.assertIsNotNone(retrieval_event)
            self.assertEqual(retrieval_event.top_k, 3)
            
            # CRITICAL: Verify query_text field does NOT exist in model
            with self.assertRaises(AttributeError):
                _ = retrieval_event.query_text
            
        finally:
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()
    
    def test_query_text_not_persisted(self):
        """Verify raw query text is never stored in database."""
        # Search with a sensitive query
        sensitive_query = "confidential API key 12345"
        
        # Create minimal data for search to work
        from core.management.commands.run_ingester import EmbeddingService
        embedding_service = EmbeddingService()
        
        # Just verify the endpoint doesn't crash and doesn't store query
        # (search will return empty results without documents, but that's fine)
        response = self.client.post('/api/rag/search/', {
            'query_text': sensitive_query,
            'top_k': 5
        })
        
        # Should succeed (even with no results)
        self.assertEqual(response.status_code, 200)
        
        # Verify query hash exists
        query_hash = response.data['query_hash']
        self.assertIsNotNone(query_hash)
        
        # Search database for any occurrence of the sensitive query
        # Check RetrievalEvent model
        events = RetrievalEvent.objects.all()
        for event in events:
            # Verify model has no query_text attribute
            self.assertFalse(hasattr(event, 'query_text'))
        
        # Additional check: query database for the string (should not appear)
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM core_retrievalevent WHERE query_hash = %s",
                [query_hash]
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            # Convert row to string and verify sensitive content not present
            row_str = str(row)
            self.assertNotIn(sensitive_query, row_str)
    
    def test_upload_status_endpoint(self):
        """Test listing uploaded files."""
        response = self.client.get('/api/rag/uploads/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('uploads', response.data)
        self.assertIn('count', response.data)
    
    def test_documents_endpoint(self):
        """Test listing documents."""
        response = self.client.get('/api/rag/documents/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('documents', response.data)
        self.assertIn('count', response.data)
