#!/bin/bash

echo "🚀 Starting AI Background Removal Tool..."

# Check if backend dependencies are installed
if ! python3 -c "import flask, rembg, PIL" 2>/dev/null; then
    echo "❌ Dependencies not found. Please run ./setup.sh first."
    exit 1
fi

echo "✅ Dependencies check passed!"

# Function to cleanup background processes
cleanup() {
    echo "🛑 Shutting down servers..."
    kill $(jobs -p) 2>/dev/null
    exit 0
}

# Set trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Start Flask backend in background
echo "🔧 Starting Flask backend on http://localhost:5000..."
python3 app.py &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 3

# Check if backend is running
if kill -0 $BACKEND_PID 2>/dev/null; then
    echo "✅ Backend started successfully!"
else
    echo "❌ Failed to start backend. Check for errors above."
    exit 1
fi

# Start frontend server
echo "🌐 Starting frontend server on http://localhost:8080..."
echo "📱 Open your browser and visit: http://localhost:8080"
echo "🛑 Press Ctrl+C to stop both servers"

python3 -m http.server 8080

# This will only be reached if the frontend server stops
wait