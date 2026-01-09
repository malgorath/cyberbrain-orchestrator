# Cyberbrain Orchestrator - Production Deployment Guide

## Overview

This guide covers deploying Cyberbrain Orchestrator to production using Docker Compose with PostgreSQL.

## Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- Host system with Docker socket access (`/var/run/docker.sock`)
- Minimum 2GB RAM, 10GB storage
- LLM endpoint (local or remote)
- Optional: Prometheus for metrics collection

## Quick Start

```bash
# 1. Clone repository
git clone <repository-url>
cd cyberbrain-orchestrator

# 2. Create .env file
cp .env.example .env
# Edit .env with your configuration (see Environment Variables section)

# 3. Build and start services
docker-compose up -d

# 4. Apply migrations
docker-compose exec web python manage.py migrate

# 5. Verify deployment
curl http://localhost:9595/api/runs/
```

## Environment Variables

Create `.env` file in project root:

```bash
# Django Settings
DEBUG=False
SECRET_KEY=<generate-a-secure-random-key>
ALLOWED_HOSTS=your-domain.com,localhost

# Database
POSTGRES_DB=cyberbrain_db
POSTGRES_USER=cyberbrain_user
POSTGRES_PASSWORD=<secure-password>
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Paths
CYBER_BRAIN_LOGS=/path/to/logs
UPLOADS_DIR=/path/to/uploads

# Security
DEBUG_REDACTED_MODE=True

# LLM Configuration
LLM_ENDPOINT=http://llm-server:8000/v1

# Optional: Sentry error tracking
# SENTRY_DSN=https://...
```

## Docker Compose Configuration

### Production docker-compose.yml

```yaml
services:
  db:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - cyberbrain

  web:
    build: .
    command: >
      sh -c "/opt/venv/bin/python manage.py migrate &&
             /opt/venv/bin/python manage.py collectstatic --noinput &&
             /opt/venv/bin/daphne -b 0.0.0.0 -p 8000 cyberbrain_orchestrator.asgi:application"
    volumes:
      - ${CYBER_BRAIN_LOGS}:/logs
      - ${UPLOADS_DIR}:/uploads
      - /var/run/docker.sock:/var/run/docker.sock
      - static_files:/app/staticfiles
    ports:
      - "9595:8000"
    environment:
      - DEBUG=${DEBUG}
      - SECRET_KEY=${SECRET_KEY}
      - ALLOWED_HOSTS=${ALLOWED_HOSTS}
      - DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      - DEBUG_REDACTED_MODE=${DEBUG_REDACTED_MODE}
      - LLM_ENDPOINT=${LLM_ENDPOINT}
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - cyberbrain

  # Optional: Nginx reverse proxy
  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - static_files:/static:ro
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - web
    restart: unless-stopped
    networks:
      - cyberbrain

volumes:
  postgres_data:
  static_files:

networks:
  cyberbrain:
```

## Security Checklist

### Required Security Measures

- [ ] Set `DEBUG=False` in production
- [ ] Generate strong `SECRET_KEY` (use `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- [ ] Use strong PostgreSQL password
- [ ] Enable `DEBUG_REDACTED_MODE=True`
- [ ] Configure `ALLOWED_HOSTS` with actual domain names
- [ ] Enable HTTPS with SSL/TLS certificates
- [ ] Restrict Docker socket access (consider Docker socket proxy)
- [ ] Configure firewall rules (only allow necessary ports)
- [ ] Set up container allowlist before launching runs
- [ ] Regular security updates for Docker images

### Optional Security Enhancements

- [ ] Enable Django security middleware (SECURE_SSL_REDIRECT, SECURE_HSTS_SECONDS)
- [ ] Use Docker secrets for sensitive environment variables
- [ ] Implement rate limiting on API endpoints
- [ ] Set up WAF (Web Application Firewall)
- [ ] Enable audit logging
- [ ] Configure Fail2Ban for brute-force protection
- [ ] Use read-only container filesystem where possible

## Container Allowlist Setup

Before launching runs, add containers to the allowlist:

```bash
# Via API
curl -X POST http://localhost:9595/api/containers/ \
  -H "Content-Type: application/json" \
  -d '{
    "container_id": "abc123...",
    "name": "my-service",
    "description": "Production service container",
    "is_active": true
  }'

# Via Django admin
# Navigate to http://localhost:9595/admin/orchestrator/containerallowlist/
```

## Monitoring and Observability

### Prometheus Integration

Add to docker-compose.yml:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    restart: unless-stopped
    networks:
      - cyberbrain
```

prometheus.yml:
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'cyberbrain'
    static_configs:
      - targets: ['web:8000']
    metrics_path: '/metrics/'
```

### Grafana Dashboards

Add to docker-compose.yml:

```yaml
services:
  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=<secure-password>
    restart: unless-stopped
    networks:
      - cyberbrain
```

### Structured Logging

Configure Django logging in `settings.py`:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'orchestrator.structured_logging.JSONFormatter',
        },
    },
    'handlers': {
        'json_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/logs/cyberbrain.json',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10,
            'formatter': 'json',
        },
    },
    'loggers': {
        'orchestrator': {
            'handlers': ['json_file'],
            'level': 'INFO',
        },
        'core': {
            'handlers': ['json_file'],
            'level': 'INFO',
        },
    },
}
```

## Backup and Recovery

### Database Backups

```bash
# Backup
docker-compose exec db pg_dump -U cyberbrain_user cyberbrain_db > backup_$(date +%Y%m%d).sql

# Restore
docker-compose exec -T db psql -U cyberbrain_user cyberbrain_db < backup_20260108.sql
```

### Automated Backups

Add to crontab:

```bash
# Daily database backup at 2 AM
0 2 * * * cd /path/to/cyberbrain-orchestrator && docker-compose exec -T db pg_dump -U cyberbrain_user cyberbrain_db | gzip > /backups/db_$(date +\%Y\%m\%d).sql.gz

# Clean up backups older than 30 days
0 3 * * * find /backups -name "db_*.sql.gz" -mtime +30 -delete
```

### Artifact Backups

```bash
# Rsync logs directory
rsync -av --delete /path/to/logs/ /backups/logs/
```

## Scaling and Performance

### Horizontal Scaling

Currently, Cyberbrain Orchestrator runs as a single web process. For high-availability:

1. **Load Balancer**: Add nginx or HAProxy in front of multiple web instances
2. **Shared Storage**: Use NFS or S3 for `/logs` and `/uploads`
3. **Database Connection Pooling**: Use PgBouncer
4. **Redis Cache**: Add Redis for metrics storage (replace Django cache)

### Vertical Scaling

Update docker-compose.yml:

```yaml
services:
  web:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

## Troubleshooting

### Common Issues

**Issue**: Container access denied
**Solution**: Check Docker socket permissions and container allowlist

```bash
# Check socket permissions
ls -l /var/run/docker.sock

# Verify allowlist
curl http://localhost:9595/api/containers/
```

**Issue**: Database connection errors
**Solution**: Verify database is healthy

```bash
docker-compose logs db
docker-compose exec db pg_isready -U cyberbrain_user
```

**Issue**: LLM calls failing
**Solution**: Check LLM endpoint configuration

```bash
# Test LLM endpoint
curl ${LLM_ENDPOINT}/health

# Check logs
docker-compose logs web | grep llm_client
```

### Health Checks

```bash
# API health
curl http://localhost:9595/api/runs/

# Metrics health
curl http://localhost:9595/metrics/json/

# Database health
docker-compose exec web python manage.py dbshell -c "SELECT 1;"
```

## Maintenance

### Regular Tasks

- **Daily**: Check logs for errors
- **Weekly**: Review metrics and performance
- **Monthly**: Database vacuum and reindex, security updates
- **Quarterly**: Review and update container allowlist

### Updates

```bash
# 1. Backup database
docker-compose exec db pg_dump -U cyberbrain_user cyberbrain_db > backup.sql

# 2. Pull latest changes
git pull origin main

# 3. Rebuild images
docker-compose build

# 4. Apply migrations
docker-compose exec web python manage.py migrate

# 5. Restart services
docker-compose restart
```

## Support and Documentation

- **API Documentation**: http://localhost:9595/api/docs/ (Swagger UI)
- **Alternative Docs**: http://localhost:9595/api/redoc/ (ReDoc)
- **OpenAPI Schema**: http://localhost:9595/api/schema/
- **Metrics**: http://localhost:9595/metrics/json/

## License

MIT License - See LICENSE file for details
