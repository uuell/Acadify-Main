#!/usr/bin/env bash
# build.sh - Render build script
# Runs on every deploy: installs dependencies and applies DB migrations

set -o errexit  # Exit immediately if any command fails

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo "🗄️ Running database migrations..."
flask db upgrade

echo "✅ Build complete!"