#!/bin/bash
# Setup script for Cyberbrain Orchestrator

set -e

echo "🧠 Setting up Cyberbrain Orchestrator..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your configuration before starting services!"
fi

# Create necessary directories
echo "Creating directories for logs and uploads..."
mkdir -p logs uploads

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your configuration"
echo "2. Run: docker-compose up -d"
echo "3. Run: docker-compose exec web python manage.py migrate"
echo "4. Run: docker-compose exec web python manage.py createsuperuser"
echo "5. Access the application at http://192.168.1.3:9595/"
echo ""
echo "For local development without Docker:"
echo "1. Install dependencies: pip install -r requirements.txt"
echo "2. Update POSTGRES_HOST in .env to localhost"
echo "3. Run migrations: python manage.py migrate"
echo "4. Create superuser: python manage.py createsuperuser"
echo "5. Run server: python manage.py runserver"
