# Cyberbrain Orchestrator

A Django 5-based orchestration system for managing Docker container tasks with Django REST Framework API and a simple WebUI.

## Features

- **Django 5 + Django REST Framework**: Modern web framework with powerful API capabilities
- **PostgreSQL Database**: Robust data storage for orchestrator state
- **Docker Integration**: Direct access to host Docker daemon via `/var/run/docker.sock`
- **Task Orchestration**: Support for multiple task types:
  - Log Triage
  - GPU Report
  - Service Map
- **WebUI Dashboard**: Simple, responsive web interface for managing runs
- **RESTful API**: Full API for programmatic access
- **Container Allowlist**: Security feature to control which containers can be accessed

## Architecture

### Database Models

- **Directive**: Task templates/configurations for orchestrator runs
- **Run**: Represents an orchestration run with status tracking
- **Job**: Individual tasks within a run (log_triage, gpu_report, service_map)
- **LLMCall**: Token count tracking for LLM API calls
- **ContainerAllowlist**: Whitelist of containers that can be accessed

### API Endpoints

- `POST /api/runs/launch/` - Launch a new orchestrator run
- `GET /api/runs/` - List all runs
- `GET /api/runs/{id}/` - Get run details
- `GET /api/runs/{id}/report/` - Fetch run report (markdown + JSON)
- `GET /api/directives/` - List/manage directives
- `GET /api/jobs/` - List all jobs
- `GET /api/containers/` - List/manage container allowlist

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Ports 9595 available on 192.168.1.3 (configurable)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/malgorath/cyberbrain-orchestrator.git
cd cyberbrain-orchestrator
```

2. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. Create local directories for volumes:
```bash
mkdir -p logs uploads
```

4. Start the services:
```bash
docker-compose up -d
```

5. Run migrations:
```bash
docker-compose exec web python manage.py migrate
```

6. Create a superuser for admin access:
```bash
docker-compose exec web python manage.py createsuperuser
```

7. Access the application:
- WebUI: http://192.168.1.3:9595/
- API: http://192.168.1.3:9595/api/
- Admin: http://192.168.1.3:9595/admin/

### Local Development (without Docker)

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up PostgreSQL (or use SQLite for development):
```bash
# Update POSTGRES_HOST in .env to localhost
# Or switch to SQLite in settings.py temporarily
```

3. Run migrations:
```bash
python manage.py migrate
```

4. Create superuser:
```bash
python manage.py createsuperuser
```

5. Run development server:
```bash
python manage.py runserver 0.0.0.0:8000
```

## Usage

### Launching Runs via API

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
  -d '{"tasks": ["log_triage", "gpu_report"]}'
```

### Listing Runs

```bash
curl http://192.168.1.3:9595/api/runs/
```

### Fetching Reports

```bash
curl http://192.168.1.3:9595/api/runs/1/report/
```

### Managing Container Allowlist

```bash
# List containers
curl http://192.168.1.3:9595/api/containers/

# Add container
curl -X POST http://192.168.1.3:9595/api/containers/ \
  -H "Content-Type: application/json" \
  -d '{"container_id": "abc123", "name": "my-container", "description": "Production container"}'
```

## Environment Variables

Key environment variables (see `.env.example` for all):

- `POSTGRES_DB`: Database name
- `POSTGRES_USER`: Database user
- `POSTGRES_PASSWORD`: Database password
- `DJANGO_SECRET_KEY`: Django secret key (change in production!)
- `DJANGO_DEBUG`: Debug mode (False in production)
- `CYBER_BRAIN_LOGS`: Path to logs directory
- `UPLOADS_DIR`: Path to uploads directory

## Docker Configuration

The `docker-compose.yml` file configures:

- **PostgreSQL** service on internal network
- **Django** web service exposed on `192.168.1.3:9595`
- Volume mounts:
  - `CYBER_BRAIN_LOGS` → `/logs`
  - `UPLOADS_DIR` → `/uploads`
  - `/var/run/docker.sock` → access to host Docker daemon
- Health checks and automatic restarts

## Security Notes

- **No Prompt Storage**: The system does not store LLM prompts, only token counts
- **Container Allowlist**: Use the ContainerAllowlist model to restrict container access
- **Debug Mode**: Set `DJANGO_DEBUG=False` in production
- **Secret Key**: Change `DJANGO_SECRET_KEY` in production
- **Docker Socket**: Mounting `/var/run/docker.sock` provides full Docker access - use with caution

## Development

### Running Tests

```bash
python manage.py test
```

### Creating Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### Accessing Django Shell

```bash
python manage.py shell
```

## Troubleshooting

### Port Binding Issues

If port 9595 on 192.168.1.3 is not available:
1. Edit `docker-compose.yml`
2. Change `"192.168.1.3:9595:8000"` to your desired IP:port

### Database Connection Issues

1. Check PostgreSQL is running: `docker-compose ps`
2. Check logs: `docker-compose logs db`
3. Verify environment variables in `.env`

### Docker Socket Permission Issues

If the web container cannot access Docker:
```bash
docker-compose exec web ls -la /var/run/docker.sock
# Ensure proper permissions
```

## License

MIT License

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.