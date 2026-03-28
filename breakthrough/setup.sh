#!/bin/bash
# Breakthrough Session - Setup Script
# Run this once: bash setup.sh

echo "=== Breakthrough Session Setup ==="
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Install from python.org"
    exit 1
fi
echo "Python 3: $(python3 --version)"

# Check Claude Code
if ! command -v claude &> /dev/null; then
    echo "ERROR: Claude Code CLI not found. Install: npm install -g @anthropic-ai/claude-code"
    exit 1
fi
echo "Claude Code: found"

# Install brew dependencies (for audio)
echo ""
echo "Installing system dependencies..."
if command -v brew &> /dev/null; then
    brew install ffmpeg portaudio 2>/dev/null || true
else
    echo "WARNING: Homebrew not found. Install ffmpeg and portaudio manually."
fi

# Install Python packages
echo ""
echo "Installing Python packages..."
pip3 install --quiet faster-whisper edge-tts sounddevice numpy

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Run a session with:"
echo "  python3 breakthrough_session.py"
echo ""
echo "First run will download the Whisper model (~150MB) - takes a minute."
