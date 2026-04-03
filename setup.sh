#!/bin/bash
# Setup script for Agent GW
# Creates Python virtual environment and installs dependencies

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$SCRIPT_DIR/venv"

echo "========================================"
echo "Agent GW - Environment Setup"
echo "========================================"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
REQUIRED_VERSION="3.8"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then 
    echo "Error: Python 3.8 or higher is required (found $PYTHON_VERSION)"
    exit 1
fi

echo "✓ Python version check passed ($PYTHON_VERSION)"

# Create virtual environment
if [ -d "$VENV_DIR" ]; then
    echo "✓ Virtual environment already exists at $VENV_DIR"
else
    echo "→ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "✓ Virtual environment created"
fi

# Activate virtual environment
echo "→ Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo "→ Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "→ Installing dependencies..."
pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "========================================"
echo "Setup completed successfully!"
echo "========================================"
echo ""
echo "To activate the virtual environment, run:"
echo "  source venv/bin/activate"
echo ""
echo "To start the application:"
echo "  python3 agent_gw.py"
echo ""
echo "To run tests:"
echo "  pytest"
echo ""
