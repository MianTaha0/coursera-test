#!/bin/bash

# Background Removal API Startup Script

echo "🎨 Starting Background Removal API..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Please run setup first."
    echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
echo "📦 Activating virtual environment..."
source venv/bin/activate

# Start the Flask application
echo "🚀 Starting Flask server..."
echo "📍 Server will be available at: http://localhost:5000"
echo "📄 Open frontend_example.html in your browser to test the UI"
echo "🛑 Press Ctrl+C to stop the server"
echo ""

python3 app.py