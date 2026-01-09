FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/venv/bin:${PATH}"

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    gcc \
    python3-dev \
    musl-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into dedicated venv
COPY requirements.txt /app/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Create directories for logs and uploads
RUN mkdir -p /logs /uploads

# Collect static files using venv interpreter
RUN /opt/venv/bin/python manage.py collectstatic --noinput || true

# Expose port
EXPOSE 8000

# Run the application from venv PATH using ASGI (Daphne)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "cyberbrain_orchestrator.asgi:application"]
