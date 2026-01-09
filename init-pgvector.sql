-- Phase 3: Enable pgvector extension for RAG vector search
-- This script runs automatically on first database initialization
-- For existing databases, run manually: docker-compose exec db psql -U cyberbrain_user -d cyberbrain_db -f /docker-entrypoint-initdb.d/init-pgvector.sql

-- Note: pgvector extension must be available in the Postgres image
-- postgres:16-alpine doesn't include pgvector by default
-- For now, this serves as documentation; actual vector storage uses JSONField
-- In production, switch to postgres image with pgvector or install it manually

-- CREATE EXTENSION IF NOT EXISTS vector;
