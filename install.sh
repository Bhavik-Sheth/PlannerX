#!/bin/bash
set -e

echo "=================================================="
echo "          PlanBoard Installation Script           "
echo "=================================================="

# Check if uv is installed, otherwise fall back to standard python/pip
if command -v uv &> /dev/null; then
    echo "🚀 'uv' detected! Using uv for a faster installation..."
    echo "📦 Synchronizing virtual environment and dependencies..."
    if [ ! -d ".venv" ]; then
        uv venv .venv
    fi
    source .venv/bin/activate
    uv pip install -r requirements.txt
    uv pip install -e .
else
    echo "⚠️ 'uv' is not installed. Falling back to standard python3 venv and pip..."
    
    # Check if python3 is installed
    if ! command -v python3 &> /dev/null; then
        echo "❌ Error: python3 is not installed. Please install Python 3.14+."
        exit 1
    fi

    # Create virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        echo "⚙️ Creating virtual environment in .venv..."
        python3 -m venv .venv
    fi

    echo "⚙️ Activating virtual environment..."
    source .venv/bin/activate

    echo "📦 Upgrading pip..."
    pip install --upgrade pip

    echo "📦 Installing dependencies from requirements.txt..."
    pip install -r requirements.txt

    echo "📦 Installing PlanBoard in editable mode..."
    pip install -e .
fi

# Setup .env if it doesn't exist
if [ ! -f .env ]; then
    echo "⚙️ Creating .env configuration file..."
    cp .env.example .env
    echo "✅ .env created. Please configure your API key in .env or via the TUI."
else
    echo "ℹ️ .env file already exists, skipping."
fi

# Scaffold the PLANBOARD directory with empty files
echo "⚙️ Scaffolding fresh PLANBOARD directory structure..."
./.venv/bin/python -c "from planboard.tools.file_tools import scaffold_planboard; scaffold_planboard('.')"


echo "=================================================="
echo "🎉 PlanBoard setup complete!"
echo "To launch the interactive TUI, run:"
echo "    source .venv/bin/activate"
echo "    planboard"
echo "=================================================="
