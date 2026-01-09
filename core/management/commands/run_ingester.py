"""
Phase 3 RAG Ingestion Pipeline

Polls UploadFile rows with status='queued' and processes them:
1. Extract text from supported formats (txt, md, json, pdf, docx)
2. Chunk the text
3. Generate embeddings using local model
4. Store in Postgres
5. Mark upload ready/failed

Usage: python manage.py run_ingester
"""
import time
import logging
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from core.models import UploadFile, Document, Chunk, Embedding

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Local embedding model service."""
    def __init__(self, model_id='sentence-transformers/all-MiniLM-L6-v2'):
        self.model_id = model_id
        self._model = None
    
    def _load_model(self):
        """Lazy load the embedding model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {self.model_id}")
                self._model = SentenceTransformer(self.model_id)
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load embedding model: {e}")
                raise
        return self._model
    
    def embed(self, texts):
        """Generate embeddings for a list of texts."""
        model = self._load_model()
        embeddings = model.encode(texts, show_progress_bar=False)
        # Convert numpy arrays to lists for JSON storage
        return [emb.tolist() for emb in embeddings]


class TextExtractor:
    """Extract text from various file formats."""
    
    @staticmethod
    def extract(file_path: Path, mime_type: str) -> str:
        """Extract text from a file based on MIME type."""
        if mime_type == 'text/plain' or file_path.suffix in ['.txt', '.md']:
            return TextExtractor._extract_text(file_path)
        elif mime_type == 'application/json' or file_path.suffix == '.json':
            return TextExtractor._extract_json(file_path)
        elif mime_type == 'application/pdf' or file_path.suffix == '.pdf':
            return TextExtractor._extract_pdf(file_path)
        elif mime_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'] or file_path.suffix == '.docx':
            return TextExtractor._extract_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {mime_type}")
    
    @staticmethod
    def _extract_text(file_path: Path) -> str:
        """Extract from plain text file."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    @staticmethod
    def _extract_json(file_path: Path) -> str:
        """Extract from JSON file (convert to readable text)."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return json.dumps(data, indent=2)
    
    @staticmethod
    def _extract_pdf(file_path: Path) -> str:
        """Extract text from PDF."""
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            text_parts = []
            for page in reader.pages:
                text_parts.append(page.extract_text())
            return '\n\n'.join(text_parts)
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return ""
    
    @staticmethod
    def _extract_docx(file_path: Path) -> str:
        """Extract text from DOCX."""
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            return '\n\n'.join([para.text for para in doc.paragraphs if para.text])
        except Exception as e:
            logger.warning(f"DOCX extraction failed: {e}")
            return ""


class TextChunker:
    """Chunk text into manageable pieces for embedding."""
    
    def __init__(self, chunk_size=500, overlap=50):
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def chunk(self, text: str) -> list:
        """Split text into overlapping chunks."""
        if not text:
            return []
        
        chunks = []
        words = text.split()
        
        i = 0
        while i < len(words):
            end = min(i + self.chunk_size, len(words))
            chunk_text = ' '.join(words[i:end])
            if chunk_text.strip():
                chunks.append(chunk_text.strip())
            i += (self.chunk_size - self.overlap)
            if i >= len(words):
                break
        
        return chunks


class Command(BaseCommand):
    help = 'Run the Phase 3 RAG ingestion pipeline'
    
    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=10, help='Polling interval seconds')
        parser.add_argument('--batch-size', type=int, default=5, help='Max uploads to process per tick')
    
    def handle(self, *args, **options):
        interval = options['interval']
        batch_size = options['batch_size']
        
        self.stdout.write(self.style.SUCCESS(f'RAG Ingester starting (interval={interval}s)...'))
        
        embedding_service = EmbeddingService()
        text_extractor = TextExtractor()
        text_chunker = TextChunker()
        
        while True:
            try:
                self._tick(embedding_service, text_extractor, text_chunker, batch_size)
            except Exception as e:
                logger.error(f"Ingester tick error: {e}", exc_info=True)
            time.sleep(interval)
    
    def _tick(self, embedding_service, text_extractor, text_chunker, batch_size):
        """Process one batch of queued uploads."""
        uploads = UploadFile.objects.filter(status='queued').order_by('uploaded_at')[:batch_size]
        
        for upload in uploads:
            logger.info(f"Processing upload: {upload.filename}")
            try:
                with transaction.atomic():
                    # Mark as processing
                    upload.status = 'processing'
                    upload.save(update_fields=['status'])
                
                # Extract text
                file_path = Path(upload.stored_path)
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found: {upload.stored_path}")
                
                text = text_extractor.extract(file_path, upload.mime_type)
                if not text.strip():
                    raise ValueError("No text content extracted")
                
                # Create document
                with transaction.atomic():
                    document = Document.objects.create(
                        upload=upload,
                        title=upload.filename,
                        source=upload.filename
                    )
                    
                    # Chunk text
                    chunks_text = text_chunker.chunk(text)
                    if not chunks_text:
                        raise ValueError("No chunks generated")
                    
                    logger.info(f"Generated {len(chunks_text)} chunks for {upload.filename}")
                    
                    # Create chunk objects
                    chunk_objs = []
                    for idx, chunk_text in enumerate(chunks_text):
                        chunk_objs.append(Chunk(
                            document=document,
                            chunk_index=idx,
                            text=chunk_text
                        ))
                    Chunk.objects.bulk_create(chunk_objs)
                    
                    # Generate embeddings
                    embeddings_data = embedding_service.embed(chunks_text)
                    
                    # Create embedding objects
                    embedding_objs = []
                    for chunk_obj, embedding_vector in zip(chunk_objs, embeddings_data):
                        embedding_objs.append(Embedding(
                            chunk=chunk_obj,
                            embedding_model_id=embedding_service.model_id,
                            vector=embedding_vector
                        ))
                    Embedding.objects.bulk_create(embedding_objs)
                    
                    # Mark as ready
                    upload.status = 'ready'
                    upload.processed_at = timezone.now()
                    upload.error_message = ''
                    upload.save(update_fields=['status', 'processed_at', 'error_message'])
                
                logger.info(f"Successfully processed: {upload.filename}")
                
            except Exception as e:
                logger.error(f"Failed to process {upload.filename}: {e}", exc_info=True)
                upload.status = 'failed'
                upload.error_message = str(e)[:1000]
                upload.processed_at = timezone.now()
                upload.save(update_fields=['status', 'error_message', 'processed_at'])
