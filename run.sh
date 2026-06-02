#!/bin/bash

# Quick start script for BCSFE Order System on Linux/macOS

echo ""
echo "========================================"
echo "  BCSFE Order System - Quick Start"
echo "========================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed"
    echo "Please install Python 3.8+ from https://www.python.org/"
    exit 1
fi

echo "[OK] Python found"
python3 --version
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
    echo "[OK] Virtual environment created"
    echo ""
fi

# Activate virtual environment
echo "[INFO] Activating virtual environment..."
source venv/bin/activate

# Install requirements
echo "[INFO] Installing dependencies..."
pip install -r requirements.txt -q
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install dependencies"
    exit 1
fi
echo "[OK] Dependencies installed"
echo ""

# Check if bcsfe is installed
echo "[INFO] Checking bcsfe installation..."
python -m bcsfe --version &> /dev/null
if [ $? -ne 0 ]; then
    echo "[WARNING] bcsfe might not be properly installed"
    echo "Trying to install bcsfe..."
    pip install bcsfe --upgrade
fi
echo ""

# Start server
echo "========================================"
echo "  Starting BCSFE Order System..."
echo "========================================"
echo ""
echo "[URL] Open: http://localhost:8000/static/bcsfe-order.html"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python main.py

