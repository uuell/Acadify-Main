
#!/usr/bin/env bash
# build.sh - Render build script

set -o errexit

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running production database migrations..."
export FLASK_APP='app:create_app("production")'
flask db upgrade

echo "Build complete!"
