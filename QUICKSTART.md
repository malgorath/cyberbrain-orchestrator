# Cyberbrain Orchestrator - Quick Start Guide

This guide will help you get the Cyberbrain Orchestrator up and running quickly.

## Prerequisites

- Docker and Docker Compose installed
- Port 9595 available on 192.168.1.3 (or modify docker-compose.yml)
- Access to host Docker socket at `/var/run/docker.sock`

## Option 1: Docker Compose (Recommended)

### 1. Initial Setup

```bash
# Clone the repository
git clone https://github.com/malgorath/cyberbrain-orchestrator.git
cd cyberbrain-orchestrator

# Run the setup script
./setup.sh

# Edit .env file with your configuration
nano .env
```

### 2. Start Services

```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f
```

### 3. Initialize Database

```bash
# Run migrations
docker-compose exec web python manage.py migrate

# Create a superuser for admin access
docker-compose exec web python manage.py createsuperuser
```

### 4. Access the Application

- **WebUI**: http://192.168.1.3:9595/
- **API Root**: http://192.168.1.3:9595/api/
- **Admin Panel**: http://192.168.1.3:9595/admin/

## Option 2: Local Development

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Database

For local development, you can either:

**A. Use PostgreSQL** (recommended for production-like environment):
```bash
# Install PostgreSQL and create database
createdb cyberbrain_db

# Update .env
POSTGRES_HOST=localhost
```

**B. Use SQLite** (quick testing):
Edit `cyberbrain_orchestrator/settings.py` and temporarily change the database to SQLite.

### 3. Run Migrations

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. Run Development Server

```bash
python manage.py runserver 0.0.0.0:8000
```

Access at: http://localhost:8000/

## Using the API

### Launch a Run

**Launch all tasks:**
```bash
curl -X POST http://192.168.1.3:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Launch specific tasks:**
```bash
curl -X POST http://192.168.1.3:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{"tasks": ["log_triage"]}'
```

### List Runs

```bash
curl http://192.168.1.3:9595/api/runs/
```

### Get Run Report

```bash
curl http://192.168.1.3:9595/api/runs/1/report/
```

### Manage Container Allowlist

```bash
# Add container to allowlist
curl -X POST http://192.168.1.3:9595/api/containers/ \
  -H "Content-Type: application/json" \
  -d '{
    "container_id": "abc123def456",
    "name": "my-container",
    "description": "Production container"
  }'

# List allowed containers
curl http://192.168.1.3:9595/api/containers/
```

## Running Tests

```bash
# Run all tests
python manage.py test --settings=cyberbrain_orchestrator.test_settings

# Run validation script
python validate.py
```

## Troubleshooting

### Port Already in Use

Edit `docker-compose.yml` and change:
```yaml
ports:
  - "192.168.1.3:9595:8000"  # Change 9595 to another port
```

### Database Connection Issues

```bash
# Check PostgreSQL is running
docker-compose ps

# View database logs
docker-compose logs db

# Restart services
docker-compose restart
```

### Docker Socket Permission Issues

```bash
# Check socket exists
ls -la /var/run/docker.sock

# May need to add user to docker group
sudo usermod -aG docker $USER
```

## Next Steps

1. Configure container allowlist in admin panel
2. Create custom directives for your workflows
3. Set up automated task execution
4. Monitor runs through the WebUI

## Support

For issues and questions, please visit:
https://github.com/malgorath/cyberbrain-orchestrator/issues
