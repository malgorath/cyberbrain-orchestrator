"""
Phase 3: Enable pgvector extension and convert Embedding.vector to VectorField.

This migration:
1. Enables the pgvector extension in PostgreSQL
2. Updates Embedding.vector from JSONField to pgvector VectorField (384 dimensions)

Note: Requires PostgreSQL with pgvector extension installed.
For development without pgvector (SQLite), this migration is safely skipped.
"""
from django.db import migrations, connection
from django.contrib.postgres.operations import CreateExtension


def check_pgvector_available(apps, schema_editor):
    """Check if pgvector extension is available (Postgres only)."""
    # Skip check for SQLite (test databases)
    if connection.vendor != 'postgresql':
        return
    
    db_alias = schema_editor.connection.alias
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_available_extensions WHERE name='vector'")
        result = cursor.fetchone()
        if not result:
            raise RuntimeError(
                "pgvector extension is not available. "
                "Install it with: apt-get install postgresql-15-pgvector (or your PG version)"
            )


def enable_pgvector_forward(apps, schema_editor):
    """Enable pgvector extension (Postgres only)."""
    if connection.vendor != 'postgresql':
        return
    
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")


def enable_pgvector_reverse(apps, schema_editor):
    """Disable pgvector extension (Postgres only)."""
    if connection.vendor != 'postgresql':
        return
    
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP EXTENSION IF EXISTS vector")


def convert_to_vector_forward(apps, schema_editor):
    """Convert Embedding.vector from JSONField to vector(384) (Postgres only)."""
    if connection.vendor != 'postgresql':
        return
    
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            ALTER TABLE core_embedding ADD COLUMN vector_new vector(384);
            UPDATE core_embedding SET vector_new = 
                CASE 
                    WHEN jsonb_typeof(vector) = 'array' THEN 
                        (SELECT array_agg(value::float) FROM jsonb_array_elements_text(vector) value)::vector(384)
                    ELSE NULL
                END;
            ALTER TABLE core_embedding DROP COLUMN vector;
            ALTER TABLE core_embedding RENAME COLUMN vector_new TO vector;
        """)


def convert_to_vector_reverse(apps, schema_editor):
    """Convert Embedding.vector from vector(384) back to JSONField (Postgres only)."""
    if connection.vendor != 'postgresql':
        return
    
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            ALTER TABLE core_embedding ADD COLUMN vector_json jsonb;
            UPDATE core_embedding SET vector_json = 
                (SELECT jsonb_agg(elem) FROM unnest(vector::real[]) elem);
            ALTER TABLE core_embedding DROP COLUMN vector;
            ALTER TABLE core_embedding RENAME COLUMN vector_json TO vector;
        """)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_notificationtarget_networkpolicyrecommendation_and_more'),
    ]

    operations = [
        # Verify pgvector is available (Postgres only)
        migrations.RunPython(check_pgvector_available, migrations.RunPython.noop),
        
        # Enable pgvector extension (Postgres only)
        migrations.RunPython(enable_pgvector_forward, enable_pgvector_reverse),
        
        # Convert Embedding.vector from JSONField to VectorField (Postgres only)
        migrations.RunPython(convert_to_vector_forward, convert_to_vector_reverse),
    ]
